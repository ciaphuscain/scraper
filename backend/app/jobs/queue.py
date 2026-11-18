"""Persistent SQLite-backed job queue.

Lanes isolate resource classes so a slow transcription never blocks caption
downloads:

* ``network`` – discovery, metadata, captions, audio download (I/O bound)
* ``cpu``     – Whisper transcription (CPU heavy)
* ``llm``     – Ollama analysis (CPU/GPU heavy)
* ``general`` – exports and reports

Claiming is a single atomic ``UPDATE ... RETURNING`` so concurrent workers
never take the same job. A partial unique index on ``dedupe_key`` prevents
duplicate active work for the same video and stage.
"""
from __future__ import annotations

import logging
import random
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import DeferredError, StudioError
from app.models import Channel, Job, JobEvent
from app.models.entities import ACTIVE_JOB_STATUSES
from app.utils.time import utcnow

log = logging.getLogger(__name__)

JOB_LANES: dict[str, str] = {
    "discover_channel": "network",
    "fetch_transcript": "network",
    "download_audio": "network",
    "transcribe_audio": "cpu",
    "analyze_video": "llm",
    "channel_report": "llm",
    "cross_channel_report": "llm",
    "export": "general",
}

# Stage labels shown in the UI
STAGES = [
    "queued", "discovering", "fetching_metadata", "downloading_captions", "downloading_audio",
    "transcribing", "normalizing", "extracting_ideas", "combining_ideas", "analyzing", "exporting",
    "completed", "retry_scheduled", "failed", "paused", "cancelled",
]

CLAIMABLE = ("queued", "retry_scheduled")


def default_dedupe_key(job_type: str, channel_id: str | None, video_id: str | None, payload: dict[str, Any]) -> str:
    if video_id:
        return f"{job_type}:{video_id}"
    if channel_id:
        return f"{job_type}:{channel_id}"
    if job_type == "discover_channel":
        return f"{job_type}:{payload.get('input_url', '')}"
    return f"{job_type}:{random.getrandbits(64):x}"  # non-deduplicated job


def log_event(session: Session, job: Job, message: str, level: str = "info") -> None:
    session.add(JobEvent(job_id=job.id, video_id=job.video_id, level=level, message=message[:4000]))


def find_active(session: Session, dedupe_key: str) -> Job | None:
    return session.execute(
        select(Job).where(Job.dedupe_key == dedupe_key, Job.status.in_(ACTIVE_JOB_STATUSES))
    ).scalar_one_or_none()


def enqueue(
    session: Session,
    job_type: str,
    *,
    channel_id: str | None = None,
    video_id: str | None = None,
    priority: int | None = None,
    payload: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
    max_attempts: int = 4,
    delay_seconds: float = 0,
) -> Job:
    """Create a job unless an equivalent one is already active (idempotent)."""
    if job_type not in JOB_LANES:
        raise ValueError(f"unknown job type {job_type}")
    payload = payload or {}
    key = dedupe_key or default_dedupe_key(job_type, channel_id, video_id, payload)
    existing = find_active(session, key)
    channel = session.get(Channel, channel_id) if channel_id else None
    if priority is None:
        priority = channel.priority if channel else 0
    if existing:
        if priority > existing.priority:
            existing.priority = priority
        return existing
    status = "paused" if channel is not None and channel.paused else "queued"
    job = Job(
        job_type=job_type,
        lane=JOB_LANES[job_type],
        channel_id=channel_id,
        video_id=video_id,
        dedupe_key=key,
        priority=priority,
        status=status,
        stage="paused" if status == "paused" else "queued",
        payload=payload,
        checkpoint={},
        max_attempts=max_attempts,
        run_after=utcnow() + timedelta(seconds=delay_seconds),
    )
    try:
        with session.begin_nested():
            session.add(job)
            session.flush()
    except IntegrityError:
        # Lost a race with another process: return the winner.
        existing = find_active(session, key)
        if existing:
            return existing
        raise
    return job


def claim(session: Session, lane: str, worker_id: str) -> Job | None:
    """Atomically claim the highest-priority runnable job in ``lane``."""
    # Same text format SQLAlchemy uses for DateTime columns on SQLite, so string comparison is valid.
    now = utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")
    row = session.execute(
        text(
            """
            UPDATE jobs SET status='running', worker_id=:wid, started_at=COALESCE(started_at, :now),
                   heartbeat_at=:now, attempts=attempts+1, requested_action=NULL
            WHERE id = (
                SELECT j.id FROM jobs j
                LEFT JOIN channels c ON c.id = j.channel_id
                WHERE j.lane=:lane AND j.status IN ('queued','retry_scheduled') AND j.run_after <= :now
                  AND (c.id IS NULL OR c.paused = 0)
                ORDER BY j.priority DESC, j.created_at ASC, j.id ASC
                LIMIT 1
            ) AND status IN ('queued','retry_scheduled')
            RETURNING id
            """
        ),
        {"wid": worker_id, "now": now, "lane": lane},
    ).first()
    session.commit()
    if not row:
        return None
    job = session.get(Job, row[0])
    if job is not None:
        session.refresh(job)
        job.stage = job.stage if job.stage not in ("queued", "retry_scheduled", "paused") else "starting"
        log_event(session, job, f"started attempt {job.attempts} on {worker_id}")
        session.commit()
    return job


def backoff_seconds(attempt: int, base: float = 30.0, cap: float = 3600.0) -> float:
    return min(cap, base * (2 ** max(0, attempt - 1))) * random.uniform(0.85, 1.15)


def mark_completed(session: Session, job: Job, result: dict[str, Any] | None = None) -> None:
    job.status = "completed"
    job.stage = "completed"
    job.progress = 1.0
    job.result = result or {}
    job.finished_at = utcnow()
    job.error_message = None
    job.error_kind = None
    log_event(session, job, "completed")


def mark_failed(session: Session, job: Job, exc: BaseException) -> str:
    """Record a failure and decide retry vs. terminal. Returns the new status."""
    if isinstance(exc, DeferredError):
        job.status = "retry_scheduled"
        job.stage = "retry_scheduled"
        job.attempts = max(0, job.attempts - 1)  # deferral doesn't consume an attempt
        job.run_after = utcnow() + timedelta(seconds=exc.delay_seconds)
        job.error_kind = exc.kind
        job.error_message = exc.user_message
        log_event(session, job, f"deferred: {exc.user_message}", "warning")
        return job.status
    if isinstance(exc, StudioError):
        transient = exc.transient
        kind = exc.kind
        message = exc.user_message
        detail = str(exc)
    elif isinstance(exc, (TimeoutError, ConnectionError)):
        transient, kind, message, detail = True, "transient", f"{type(exc).__name__}: {exc}", repr(exc)
    else:
        # Unknown errors get bounded retries; they may be bugs or flukes.
        transient, kind, message, detail = True, "unexpected", f"Unexpected error: {type(exc).__name__}: {exc}", repr(exc)
    job.error_kind = kind
    job.error_message = message
    if transient and job.attempts < job.max_attempts:
        delay = backoff_seconds(job.attempts, base=120 if kind == "rate_limited" else 30)
        job.status = "retry_scheduled"
        job.stage = "retry_scheduled"
        job.run_after = utcnow() + timedelta(seconds=delay)
        log_event(session, job, f"attempt {job.attempts} failed ({kind}): {detail[:500]}; retry in {int(delay)}s",
                  "warning")
    else:
        job.status = "failed"
        job.stage = "failed"
        job.finished_at = utcnow()
        log_event(session, job, f"failed ({kind}): {detail[:1000]}", "error")
    return job.status


def recover_interrupted(session: Session, *, stale_after_seconds: int | None = None) -> int:
    """Requeue jobs left ``running`` by a crashed/stopped worker.

    Checkpoints are kept so handlers can resume where they left off.
    """
    q = select(Job).where(Job.status == "running")
    if stale_after_seconds is not None:
        q = q.where(Job.heartbeat_at < utcnow() - timedelta(seconds=stale_after_seconds))
    jobs = session.execute(q).scalars().all()
    for job in jobs:
        if job.requested_action == "cancel":
            job.status, job.stage, job.finished_at = "cancelled", "cancelled", utcnow()
        elif job.requested_action == "pause":
            job.status, job.stage = "paused", "paused"
        else:
            job.status = "queued"
            job.stage = "queued"
            job.run_after = utcnow()
            # An interrupted attempt is not the job's fault.
            job.attempts = max(0, job.attempts - 1)
        job.worker_id = None
        job.requested_action = None
        log_event(session, job, "recovered after interruption", "warning")
    session.flush()
    return len(jobs)


# ----------------------------------------------------------------- user controls

def pause_job(session: Session, job: Job) -> None:
    if job.status in ("queued", "retry_scheduled"):
        job.status, job.stage = "paused", "paused"
    elif job.status == "running":
        job.requested_action = "pause"


def resume_job(session: Session, job: Job) -> None:
    if job.status == "paused":
        job.status, job.stage, job.run_after = "queued", "queued", utcnow()


def cancel_job(session: Session, job: Job) -> None:
    if job.status in ("queued", "retry_scheduled", "paused"):
        job.status, job.stage, job.finished_at = "cancelled", "cancelled", utcnow()
    elif job.status == "running":
        job.requested_action = "cancel"


def retry_job(session: Session, job: Job) -> Job:
    """Re-run a failed/cancelled job (new attempt budget, checkpoint kept)."""
    if job.status not in ("failed", "cancelled", "completed"):
        return job
    if find_active(session, job.dedupe_key):
        return find_active(session, job.dedupe_key)  # type: ignore[return-value]
    job.status, job.stage = "queued", "queued"
    job.attempts = 0
    job.run_after = utcnow()
    job.finished_at = None
    job.error_message = None
    job.error_kind = None
    log_event(session, job, "manually retried")
    return job


def set_channel_paused(session: Session, channel: Channel, paused: bool) -> int:
    channel.paused = paused
    if paused:
        res = session.execute(
            update(Job).where(Job.channel_id == channel.id, Job.status.in_(CLAIMABLE))
            .values(status="paused", stage="paused")
        )
        session.execute(
            update(Job).where(Job.channel_id == channel.id, Job.status == "running").values(requested_action="pause")
        )
    else:
        res = session.execute(
            update(Job).where(Job.channel_id == channel.id, Job.status == "paused")
            .values(status="queued", stage="queued", run_after=utcnow())
        )
    return res.rowcount or 0


def set_channel_priority(session: Session, channel: Channel, priority: int) -> None:
    channel.priority = priority
    session.execute(
        update(Job).where(Job.channel_id == channel.id, Job.status.in_(ACTIVE_JOB_STATUSES)).values(priority=priority)
    )


def retry_failed(session: Session, *, channel_id: str | None = None, include_permanent: bool = False) -> int:
    q = select(Job).where(Job.status == "failed")
    if channel_id:
        q = q.where(Job.channel_id == channel_id)
    n = 0
    for job in session.execute(q).scalars().all():
        if not include_permanent and job.error_kind in ("unavailable", "private", "age_restricted",
                                                         "region_restricted", "members_only"):
            continue
        if find_active(session, job.dedupe_key):
            continue
        retry_job(session, job)
        n += 1
    return n


def counts(session: Session) -> dict[str, int]:
    rows = session.execute(select(Job.status, func.count()).group_by(Job.status)).all()
    return {status: n for status, n in rows}
