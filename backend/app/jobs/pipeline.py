"""Helpers to queue work for videos/channels (used by API and handlers)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_store import load_settings
from app.jobs.queue import enqueue
from app.models import Channel, Job, Video


def queue_transcript(session: Session, video: Video, *, force: bool = False, priority: int | None = None) -> Job:
    settings = load_settings(session)
    job = enqueue(session, "fetch_transcript", channel_id=video.channel_id, video_id=video.id,
                  priority=priority, payload={"force": force}, max_attempts=settings.max_retries)
    if video.transcript_status not in ("completed",) or force:
        video.transcript_status = "queued"
    return job


def queue_analysis(session: Session, video: Video, *, force: bool = False, priority: int | None = None) -> Job:
    settings = load_settings(session)
    job = enqueue(session, "analyze_video", channel_id=video.channel_id, video_id=video.id, priority=priority,
                  payload={"force": force}, max_attempts=settings.max_retries)
    video.analysis_status = "queued"
    return job


def queue_discovery(session: Session, *, input_url: str | None = None, channel: Channel | None = None,
                    full: bool = False, since: str | None = None, priority: int | None = None) -> Job:
    payload = {"input_url": input_url, "full": full, "since": since}
    if channel is not None:
        return enqueue(session, "discover_channel", channel_id=channel.id, payload=payload, priority=priority,
                       dedupe_key=f"discover_channel:{channel.id}")
    return enqueue(session, "discover_channel", payload=payload, priority=priority if priority is not None else 10)


def queue_pending_for_channel(session: Session, channel: Channel) -> int:
    """Queue transcript collection for selected videos that have not been processed."""
    vids = session.execute(
        select(Video).where(Video.channel_id == channel.id, Video.selected.is_(True),
                            Video.transcript_status.in_(("pending",)))
    ).scalars().all()
    for v in vids:
        if channel.scan_since and v.upload_date and v.upload_date < channel.scan_since:
            continue
        queue_transcript(session, v)
    return len(vids)
