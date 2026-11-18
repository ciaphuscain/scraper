"""YouTube URL parsing and normalisation (pure functions, no network)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "www.youtu.be"}
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
HANDLE_RE = re.compile(r"^@[\w.\-·\u0080-￿]{1,100}$")
TABS = {"videos", "shorts", "streams", "featured", "playlists", "about", "community", "live", "podcasts", "releases"}


class InvalidYouTubeURL(ValueError):
    pass


@dataclass(frozen=True)
class ChannelRef:
    kind: str  # handle | channel_id | custom | user
    value: str
    tab: str | None = None

    @property
    def base_url(self) -> str:
        if self.kind == "handle":
            return f"https://www.youtube.com/{self.value}"
        if self.kind == "channel_id":
            return f"https://www.youtube.com/channel/{self.value}"
        if self.kind == "custom":
            return f"https://www.youtube.com/c/{self.value}"
        return f"https://www.youtube.com/user/{self.value}"

    def tab_url(self, tab: str) -> str:
        return f"{self.base_url}/{tab}"


@dataclass(frozen=True)
class VideoRef:
    video_id: str
    is_short_url: bool = False

    @property
    def url(self) -> str:
        if self.is_short_url:
            return f"https://www.youtube.com/shorts/{self.video_id}"
        return f"https://www.youtube.com/watch?v={self.video_id}"


def _prepare(url: str) -> tuple[str, list[str], dict[str, list[str]]]:
    raw = (url or "").strip()
    if not raw:
        raise InvalidYouTubeURL("URL is empty")
    if raw.startswith("@") and HANDLE_RE.match(raw.split("/")[0]):
        raw = "https://www.youtube.com/" + raw
    if not re.match(r"^[a-z]+://", raw, re.I):
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = (parsed.hostname or "").lower()
    if host not in YT_HOSTS:
        raise InvalidYouTubeURL(f"Not a YouTube URL: {url}")
    parts = [unquote(p) for p in parsed.path.split("/") if p]
    return host, parts, parse_qs(parsed.query)


def parse_channel_url(url: str) -> ChannelRef:
    host, parts, _q = _prepare(url)
    if host.endswith("youtu.be") or not parts:
        raise InvalidYouTubeURL(f"Not a channel URL: {url}")
    tab = None
    first = parts[0]
    if first.startswith("@"):
        if not HANDLE_RE.match(first):
            raise InvalidYouTubeURL(f"Invalid handle in URL: {url}")
        ref_kind, value, rest = "handle", first, parts[1:]
    elif first == "channel" and len(parts) >= 2:
        if not CHANNEL_ID_RE.match(parts[1]):
            raise InvalidYouTubeURL(f"Invalid channel ID in URL: {url}")
        ref_kind, value, rest = "channel_id", parts[1], parts[2:]
    elif first == "c" and len(parts) >= 2:
        ref_kind, value, rest = "custom", parts[1], parts[2:]
    elif first == "user" and len(parts) >= 2:
        ref_kind, value, rest = "user", parts[1], parts[2:]
    elif first in ("watch", "shorts", "embed", "live", "playlist", "results", "feed"):
        raise InvalidYouTubeURL(f"This looks like a video/playlist URL, not a channel: {url}")
    elif len(parts) == 1 and re.match(r"^[\w.-]+$", first):
        # Legacy vanity URL youtube.com/name
        ref_kind, value, rest = "custom", first, parts[1:]
    else:
        raise InvalidYouTubeURL(f"Unrecognised channel URL: {url}")
    if rest and rest[0].lower() in TABS:
        tab = rest[0].lower()
    return ChannelRef(ref_kind, value, tab)


def parse_video_url(url: str) -> VideoRef:
    raw = (url or "").strip()
    if VIDEO_ID_RE.match(raw):
        return VideoRef(raw)
    host, parts, q = _prepare(raw)
    if host.endswith("youtu.be"):
        if parts and VIDEO_ID_RE.match(parts[0]):
            return VideoRef(parts[0])
    elif parts and parts[0] == "watch" and VIDEO_ID_RE.match((q.get("v") or [""])[0]):
        return VideoRef(q["v"][0])
    elif len(parts) >= 2 and parts[0] in ("shorts", "embed", "live", "v") and VIDEO_ID_RE.match(parts[1]):
        return VideoRef(parts[1], is_short_url=parts[0] == "shorts")
    raise InvalidYouTubeURL(f"Not a YouTube video URL: {url}")


def watch_url(video_id: str, t: float | None = None) -> str:
    base = f"https://www.youtube.com/watch?v={video_id}"
    if t is not None and t >= 0:
        return f"{base}&t={int(t)}s"
    return base


def channel_url(channel_id: str) -> str:
    return f"https://www.youtube.com/channel/{channel_id}"
