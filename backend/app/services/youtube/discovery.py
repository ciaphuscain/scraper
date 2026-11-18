"""Channel resolution and video/Shorts discovery."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import PermanentError
from app.models import Channel, Video
from app.services.youtube.client import YouTubeClient
from app.services.youtube.urls import ChannelRef, channel_url, parse_channel_url, watch_url
from app.utils.time import utcnow

log = logging.getLogger(__name__)

# Stop an incremental scan after this many consecutive already-known uploads.
KNOWN_STOP_THRESHOLD = 30
# Approximate dates can be off by days; stop "since" scans only after a run of older items.
OLDER_STOP_THRESHOLD = 15


def _best_thumb(info: dict[str, Any]) -> str | None:
    thumbs = info.get("thumbnails") or []
    best = None
    best_area = -1
    for t in thumbs:
        if not isinstance(t, dict) or not t.get("url"):
            continue
        area = (t.get("width") or 0) * (t.get("height") or 0)
        if area >= best_area:
            best, best_area = t["url"], area
    return best or info.get("thumbnail")


def _entry_date(entry: dict[str, Any]) -> tuple[str | None, bool]:
    d = entry.get("upload_date")
    if d and len(str(d)) == 8:
        return str(d), False
    ts = entry.get("timestamp") or entry.get("release_timestamp")
    if ts:
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y%m%d"), True
        except (OverflowError, OSError, ValueError):
            return None, False
    return None, False


def channel_fields_from_info(info: dict[str, Any], ref: ChannelRef) -> dict[str, Any]:
    cid = info.get("channel_id") or (info.get("id") if str(info.get("id", "")).startswith("UC") else None)
    if not cid:
        raise PermanentError("could not resolve channel ID", user_message="Could not resolve the channel ID.")
    handle = info.get("uploader_id") if str(info.get("uploader_id") or "").startswith("@") else None
    if ref.kind == "handle":
        handle = handle or ref.value
    name = info.get("channel") or info.get("uploader") or info.get("title") or cid
    for suffix in (" - Videos", " - Shorts"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    return {
        "id": cid,
        "name": name,
        "handle": handle,
        "url": info.get("channel_url") or channel_url(cid),
        "description": info.get("description"),
        "thumbnail_url": _best_thumb(info),
        "subscriber_count": info.get("channel_follower_count"),
    }


def upsert_channel(session: Session, fields: dict[str, Any], input_url: str | None) -> Channel:
    ch = session.get(Channel, fields["id"])
    if ch is None:
        ch = Channel(id=fields["id"], url=fields["url"], input_url=input_url)
        session.add(ch)
    for k, v in fields.items():
        if k != "id" and v is not None:
            setattr(ch, k, v)
    if not ch.active:
        ch.active = True
    session.flush()
    return ch


def resolve_channel(session: Session, client: YouTubeClient, input_url: str) -> Channel:
    ref = parse_channel_url(input_url)
    info = client.resolve_channel(ref)
    return upsert_channel(session, channel_fields_from_info(info, ref), input_url)


def upsert_video_from_entry(
    session: Session, channel_id: str, entry: dict[str, Any], tab: str
) -> tuple[Video, bool]:
    """Insert or update a discovered video. Returns (video, created)."""
    vid = entry.get("id")
    if not vid or len(vid) != 11:
        raise ValueError(f"invalid video id in entry: {vid!r}")
    video = session.get(Video, vid)
    created = video is None
    upload_date, approx = _entry_date(entry)
    if video is None:
        video = Video(
            id=vid,
            channel_id=channel_id,
            title=entry.get("title") or "",
            url=watch_url(vid),
            listing_sources=[],
            video_type="video",
            type_source="listing",
        )
        session.add(video)
    sources = list(video.listing_sources or [])
    if tab not in sources:
        sources.append(tab)
        video.listing_sources = sources
    # Classification is driven by listing context: appearing in /shorts makes it a Short.
    if tab == "shorts" or "/shorts/" in str(entry.get("url") or ""):
        video.video_type = "short"
        video.type_source = "listing"
    if entry.get("title") and not video.title:
        video.title = entry["title"]
    if entry.get("duration") and not video.duration:
        video.duration = float(entry["duration"])
    if entry.get("view_count") is not None:
        video.view_count = entry.get("view_count")
    thumb = _best_thumb(entry)
    if thumb and not video.thumbnail_url:
        video.thumbnail_url = thumb
    if upload_date and (not video.upload_date or video.upload_date_approximate):
        video.upload_date = upload_date
        video.upload_date_approximate = approx
    if entry.get("description") and not video.description:
        video.description = entry["description"]
    avail = entry.get("availability")
    if avail and video.availability == "unknown":
        video.availability = avail
    if video.channel_id is None:
        video.channel_id = channel_id
    return video, created


def scan_channel(
    session: Session,
    client: YouTubeClient,
    channel: Channel,
    *,
    tabs: tuple[str, ...] = ("videos", "shorts"),
    since: str | None = None,
    incremental: bool = True,
    progress: Callable[[str, int], None] | None = None,
    commit_every: int = 100,
) -> dict[str, Any]:
    """Discover uploads for each tab. Idempotent and safe to restart."""
    ref = parse_channel_url(channel_url(channel.id))
    known: set[str] = set(session.execute(select(Video.id).where(Video.channel_id == channel.id)).scalars())
    use_known_stop = incremental and channel.last_sync_at is not None
    since_cut = None
    if since:
        since_cut = (datetime.strptime(since, "%Y%m%d") - timedelta(days=7)).strftime("%Y%m%d")
    stats: dict[str, Any] = {"new_video_ids": [], "seen": 0, "skipped_older": 0, "tabs": {}}
    for tab in tabs:
        tab_stats = {"seen": 0, "new": 0, "stopped_early": False}
        consecutive_known = 0
        consecutive_older = 0
        n_since_commit = 0
        for entry in client.iter_tab(ref, tab):
            vid = entry.get("id")
            if not vid or len(str(vid)) != 11:
                continue
            tab_stats["seen"] += 1
            stats["seen"] += 1
            udate, _approx = _entry_date(entry)
            if since and udate and udate < since:
                stats["skipped_older"] += 1
                consecutive_older += 1
                if since_cut and udate < since_cut and consecutive_older >= OLDER_STOP_THRESHOLD:
                    tab_stats["stopped_early"] = True
                    break
                if vid not in known:
                    continue
            else:
                consecutive_older = 0
            was_known = vid in known
            _video, created = upsert_video_from_entry(session, channel.id, entry, tab)
            if created:
                tab_stats["new"] += 1
                stats["new_video_ids"].append(vid)
                known.add(vid)
                consecutive_known = 0
            elif was_known:
                consecutive_known += 1
            n_since_commit += 1
            if n_since_commit >= commit_every:
                session.commit()
                n_since_commit = 0
                if progress:
                    progress(tab, tab_stats["seen"])
            if use_known_stop and consecutive_known >= KNOWN_STOP_THRESHOLD:
                tab_stats["stopped_early"] = True
                break
        session.commit()
        if progress:
            progress(tab, tab_stats["seen"])
        stats["tabs"][tab] = tab_stats
    return stats


def apply_video_info(video: Video, info: dict[str, Any]) -> None:
    """Merge full yt-dlp metadata into a video record."""
    video.title = info.get("title") or video.title
    video.description = info.get("description") if info.get("description") is not None else video.description
    if info.get("upload_date"):
        video.upload_date = str(info["upload_date"])
        video.upload_date_approximate = False
    if info.get("duration"):
        video.duration = float(info["duration"])
    video.thumbnail_url = _best_thumb(info) or video.thumbnail_url
    video.view_count = info.get("view_count", video.view_count)
    video.tags = info.get("tags") or video.tags
    video.language = info.get("language") or video.language
    video.availability = info.get("availability") or "public"
    subs = info.get("subtitles") or {}
    autos = info.get("automatic_captions") or {}
    video.has_manual_subs = bool([k for k in subs if k != "live_chat"])
    video.has_auto_subs = bool(autos)
    video.subtitle_languages = sorted(k for k in subs if k != "live_chat")
    media_type = info.get("media_type")
    if media_type == "short" or "/shorts/" in str(info.get("original_url") or ""):
        video.video_type = "short"
        if video.type_source != "listing":
            video.type_source = "metadata"
    elif info.get("live_status") in ("is_live", "was_live", "post_live") and video.video_type != "short":
        video.video_type = "live"
        video.type_source = "metadata"
    if not video.channel_id and info.get("channel_id"):
        video.channel_id = info["channel_id"]
    video.metadata_fetched_at = utcnow()
