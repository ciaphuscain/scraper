"""Thin wrapper around yt-dlp.

All network access to YouTube goes through :class:`YtDlpClient`, which applies
a polite global rate limit and maps yt-dlp errors onto the studio error
taxonomy. Access restrictions (login walls, age gates, bot checks, region
blocks) are *never* bypassed: they are reported and the item is skipped.

Tests replace the client with a fixture-backed fake via :func:`set_client`.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

import httpx

from app.core.errors import (
    DependencyMissingError,
    PermanentError,
    RateLimitedError,
    TransientError,
    VideoUnavailableError,
)
from app.services.youtube.ratelimit import youtube_limiter
from app.services.youtube.urls import ChannelRef, watch_url

log = logging.getLogger(__name__)

_PERMANENT_PATTERNS = [
    (r"private video", "private", "The video is private."),
    (r"video unavailable|this video is no longer available|has been removed|account .* terminated|does not exist",
     "unavailable", "The video is unavailable or was removed."),
    (r"confirm your age|age[- ]restricted|inappropriate for some users", "age_restricted",
     "The video is age-restricted. Access restrictions are not bypassed."),
    (r"not (made )?available in your country|geo[- ]?restrict|blocked it in your country", "region_restricted",
     "The video is not available in your region."),
    (r"members[- ]only|join this channel", "members_only", "The video is members-only."),
    (r"premieres? in|live event will begin|this live event", "upcoming", "The video has not been released yet."),
    (r"requested format is not available", "format_unavailable", "No downloadable audio format is available."),
]
_RATE_PATTERNS = [r"http error 429", r"too many requests", r"confirm you.?re not a bot", r"rate.?limit"]


def map_ytdlp_error(exc: Exception) -> Exception:
    msg = str(exc)
    low = msg.lower()
    for pat in _RATE_PATTERNS:
        if re.search(pat, low):
            youtube_limiter.penalize(120)
            return RateLimitedError(msg, user_message="YouTube is throttling requests (rate limit / bot check). "
                                                      "The job will retry later with a longer delay.")
    for pat, kind, user in _PERMANENT_PATTERNS:
        if re.search(pat, low):
            err = VideoUnavailableError(msg, user_message=user)
            err.kind = kind
            return err
    if "ffmpeg" in low and ("not found" in low or "not installed" in low):
        return DependencyMissingError(msg, user_message="FFmpeg is not installed or not on PATH.")
    if re.search(r"unable to download|timed out|connection|network|temporary failure|http error 5\d\d", low):
        return TransientError(msg, user_message="Network error while contacting YouTube.")
    if "unsupported url" in low or "incomplete youtube id" in low:
        return PermanentError(msg, user_message="The URL is not supported.")
    return TransientError(msg)


class YouTubeClient(Protocol):
    def resolve_channel(self, ref: ChannelRef) -> dict[str, Any]: ...
    def iter_tab(self, ref: ChannelRef, tab: str) -> Iterator[dict[str, Any]]: ...
    def video_info(self, video_id: str) -> dict[str, Any]: ...
    def fetch_text(self, url: str) -> str: ...
    def download_audio(self, video_id: str, dest_dir: Path) -> Path: ...


class YtDlpClient:
    def __init__(self, request_delay: float = 2.0):
        youtube_limiter.min_interval = request_delay

    def _opts(self, **extra: Any) -> dict[str, Any]:
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "skip_download": True,
            "socket_timeout": 30,
            "retries": 3,
            "extractor_retries": 2,
            "sleep_interval_requests": 0,
            "ignoreerrors": False,
            "noplaylist": True,
            "logger": log,
        }
        opts.update(extra)
        return opts

    def _extract(self, url: str, **extra: Any) -> dict[str, Any]:
        import yt_dlp

        youtube_limiter.wait()
        try:
            with yt_dlp.YoutubeDL(self._opts(**extra)) as ydl:
                info = ydl.extract_info(url, download=False)
                return ydl.sanitize_info(info) if info else {}
        except yt_dlp.utils.DownloadError as exc:
            raise map_ytdlp_error(exc) from exc
        except yt_dlp.utils.ExtractorError as exc:
            raise map_ytdlp_error(exc) from exc

    def resolve_channel(self, ref: ChannelRef) -> dict[str, Any]:
        info = self._extract(ref.tab_url("videos"), extract_flat="in_playlist", playlistend=1, noplaylist=False)
        return info

    def iter_tab(self, ref: ChannelRef, tab: str) -> Iterator[dict[str, Any]]:
        """Yield flat entries of a channel tab lazily (newest first)."""
        import yt_dlp

        youtube_limiter.wait()
        opts = self._opts(
            extract_flat="in_playlist",
            noplaylist=False,
            lazy_playlist=True,
            extractor_args={"youtubetab": {"approximate_date": [""]}},
        )
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(ref.tab_url(tab), download=False, process=False)
                if not info:
                    return
                entries = info.get("entries") or []
                for entry in entries:
                    if entry:
                        yield dict(entry)
        except yt_dlp.utils.DownloadError as exc:
            mapped = map_ytdlp_error(exc)
            # A channel without a Shorts/Videos tab is not an error.
            if "does not have a" in str(exc).lower() and "tab" in str(exc).lower():
                return
            raise mapped from exc

    def video_info(self, video_id: str) -> dict[str, Any]:
        return self._extract(watch_url(video_id))

    def fetch_text(self, url: str) -> str:
        youtube_limiter.wait()
        try:
            r = httpx.get(url, timeout=60, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        except httpx.HTTPError as exc:
            raise TransientError(f"caption download failed: {exc}") from exc
        if r.status_code == 429:
            youtube_limiter.penalize(120)
            raise RateLimitedError("HTTP 429 fetching captions", user_message="YouTube rate-limited caption download.")
        if r.status_code >= 500:
            raise TransientError(f"HTTP {r.status_code} fetching captions")
        if r.status_code >= 400:
            raise PermanentError(f"HTTP {r.status_code} fetching captions")
        r.encoding = r.encoding or "utf-8"
        return r.text

    def download_audio(self, video_id: str, dest_dir: Path) -> Path:
        import shutil

        import yt_dlp

        dest_dir.mkdir(parents=True, exist_ok=True)
        youtube_limiter.wait()
        # Prefer audio-only m4a/webm; no re-encoding needed since faster-whisper
        # decodes via PyAV. FFmpeg is only required if post-processing is needed.
        opts = self._opts(
            skip_download=False,
            format="bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best",
            outtmpl=str(dest_dir / f"{video_id}.%(ext)s"),
            overwrites=True,
            continuedl=True,
        )
        if shutil.which("ffmpeg") is None:
            log.info("ffmpeg not found; downloading audio without post-processing")
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(watch_url(video_id), download=True)
                path = Path(ydl.prepare_filename(info))
        except yt_dlp.utils.DownloadError as exc:
            raise map_ytdlp_error(exc) from exc
        if not path.exists():
            candidates = sorted(dest_dir.glob(f"{video_id}.*"))
            candidates = [c for c in candidates if not c.name.endswith((".part", ".ytdl"))]
            if not candidates:
                raise TransientError("audio download produced no file")
            path = candidates[0]
        return path


_client: YouTubeClient | None = None


def get_client(request_delay: float | None = None) -> YouTubeClient:
    global _client
    if _client is None:
        _client = YtDlpClient(request_delay if request_delay is not None else 2.0)
    elif request_delay is not None:
        youtube_limiter.min_interval = request_delay
    return _client


def set_client(client: YouTubeClient | None) -> None:
    global _client
    _client = client
