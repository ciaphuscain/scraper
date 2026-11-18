from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import case, delete, func, select
from sqlalchemy.orm import Session

from app.api.deps import bad_request, not_found
from app.api.serializers import channel_out, job_out
from app.database.session import get_db
from app.jobs import queue as Q
from app.jobs.pipeline import queue_discovery, queue_pending_for_channel
from app.models import Channel, ChannelReport, Job, Video
from app.schemas.requests import ChannelCreate, ChannelsBulkCreate, ChannelUpdate, PriorityUpdate, ScanRequest
from app.services.youtube.urls import InvalidYouTubeURL, parse_channel_url

router = APIRouter(prefix="/api/channels", tags=["channels"])


def channel_stats(db: Session, channel_ids: list[str] | None = None) -> dict[str, dict[str, Any]]:
    q = select(
        Video.channel_id,
        func.sum(case((Video.video_type != "short", 1), else_=0)).label("videos"),
        func.sum(case((Video.video_type == "short", 1), else_=0)).label("shorts"),
        func.sum(case((Video.transcript_status == "completed", 1), else_=0)).label("transcripts"),
        func.sum(case((Video.analysis_status == "completed", 1), else_=0)).label("analysed"),
        func.sum(case((Video.transcript_status.in_(("failed",)), 1), else_=0)).label("failed"),
        func.sum(case((Video.transcript_status == "unavailable", 1), else_=0)).label("unavailable"),
        func.sum(case((Video.transcript_status.in_(("pending", "queued", "in_progress")), 1), else_=0)).label("pending"),
        func.sum(Video.idea_count).label("ideas"),
    ).group_by(Video.channel_id)
    if channel_ids is not None:
        q = q.where(Video.channel_id.in_(channel_ids))
    out: dict[str, dict[str, Any]] = {}
    for r in db.execute(q).mappings():
        d = {k: int(r[k] or 0) for k in ("videos", "shorts", "transcripts", "analysed", "failed", "unavailable",
                                         "pending", "ideas")}
        total = d["videos"] + d["shorts"]
        d["processed"] = d["transcripts"]
        d["progress"] = round((d["transcripts"] + d["unavailable"]) / total, 4) if total else 0.0
        out[r["channel_id"]] = d
    jq = select(Job.channel_id, func.count()).where(Job.status.in_(("queued", "running", "retry_scheduled"))).group_by(Job.channel_id)
    for cid, n in db.execute(jq).all():
        if cid in out:
            out[cid]["active_jobs"] = n
    return out


EMPTY = {"videos": 0, "shorts": 0, "transcripts": 0, "analysed": 0, "failed": 0, "unavailable": 0, "pending": 0,
         "ideas": 0, "processed": 0, "progress": 0.0, "active_jobs": 0}


@router.get("")
def list_channels(include_inactive: bool = False, db: Session = Depends(get_db)):
    q = select(Channel).order_by(Channel.name)
    if not include_inactive:
        q = q.where(Channel.active.is_(True))
    chans = db.execute(q).scalars().all()
    stats = channel_stats(db)
    pending_adds = db.execute(select(Job).where(Job.job_type == "discover_channel", Job.channel_id.is_(None),
                                                Job.status.in_(Q.CLAIMABLE + ("running", "failed")))).scalars().all()
    return {"channels": [channel_out(c, {**EMPTY, **stats.get(c.id, {})}) for c in chans],
            "pending_additions": [job_out(j) for j in pending_adds]}


def _add(db: Session, url: str, scan_since: str | None, priority: int, auto_process: bool) -> dict[str, Any]:
    try:
        ref = parse_channel_url(url)
    except InvalidYouTubeURL as exc:
        raise bad_request(str(exc)) from exc
    if ref.kind == "channel_id":
        existing = db.get(Channel, ref.value)
        if existing:
            existing.active = True
            job = queue_discovery(db, channel=existing)
            return {"channel_id": existing.id, "job_id": job.id, "existing": True}
    job = queue_discovery(db, input_url=ref.base_url, since=scan_since, priority=10 + priority)
    job.payload = {**job.payload, "channel_settings": {"scan_since": scan_since, "priority": priority,
                                                       "auto_process": auto_process}}
    return {"channel_id": None, "job_id": job.id, "existing": False}


@router.post("", status_code=202)
def add_channel(body: ChannelCreate, db: Session = Depends(get_db)):
    res = _add(db, body.url, body.scan_since, body.priority, body.auto_process)
    db.commit()
    return res


@router.post("/bulk", status_code=202)
def add_channels(body: ChannelsBulkCreate, db: Session = Depends(get_db)):
    results, errors = [], []
    for url in body.urls:
        url = url.strip()
        if not url:
            continue
        try:
            results.append(_add(db, url, body.scan_since, 0, body.auto_process))
        except Exception as exc:  # noqa: BLE001
            errors.append({"url": url, "error": getattr(exc, "detail", str(exc))})
    db.commit()
    return {"queued": results, "errors": errors}


@router.get("/{channel_id}")
def get_channel(channel_id: str, db: Session = Depends(get_db)):
    c = db.get(Channel, channel_id)
    if not c:
        raise not_found("channel")
    stats = channel_stats(db, [channel_id]).get(channel_id, {})
    report = db.execute(select(ChannelReport.id, ChannelReport.created_at).where(ChannelReport.channel_id == channel_id)
                        .order_by(ChannelReport.id.desc())).first()
    jobs = db.execute(select(Job).where(Job.channel_id == channel_id).order_by(Job.id.desc()).limit(20)).scalars().all()
    return {**channel_out(c, {**EMPTY, **stats}),
            "latest_report": {"id": report[0], "created_at": report[1]} if report else None,
            "recent_jobs": [job_out(j) for j in jobs]}


@router.patch("/{channel_id}")
def update_channel(channel_id: str, body: ChannelUpdate, db: Session = Depends(get_db)):
    c = db.get(Channel, channel_id)
    if not c:
        raise not_found("channel")
    if body.priority is not None:
        Q.set_channel_priority(db, c, body.priority)
    if body.clear_scan_since:
        c.scan_since = None
    elif body.scan_since is not None:
        c.scan_since = body.scan_since
    if body.auto_process is not None:
        c.auto_process = body.auto_process
    db.commit()
    return channel_out(c)


@router.delete("/{channel_id}")
def remove_channel(channel_id: str, purge: bool = False, db: Session = Depends(get_db)):
    """Remove from the active library. With purge=true all stored data for the channel is deleted."""
    c = db.get(Channel, channel_id)
    if not c:
        raise not_found("channel")
    for j in db.execute(select(Job).where(Job.channel_id == channel_id, Job.status.in_(Q.CLAIMABLE + ("paused", "running")))).scalars():
        Q.cancel_job(db, j)
    if purge:
        db.execute(delete(Video).where(Video.channel_id == channel_id))
        db.delete(c)
    else:
        c.active = False
        c.paused = True
    db.commit()
    return {"removed": channel_id, "purged": purge}


@router.post("/{channel_id}/restore")
def restore_channel(channel_id: str, db: Session = Depends(get_db)):
    c = db.get(Channel, channel_id)
    if not c:
        raise not_found("channel")
    c.active = True
    Q.set_channel_paused(db, c, False)
    db.commit()
    return channel_out(c)


@router.post("/{channel_id}/scan", status_code=202)
def scan(channel_id: str, body: ScanRequest | None = None, db: Session = Depends(get_db)):
    c = db.get(Channel, channel_id)
    if not c:
        raise not_found("channel")
    body = body or ScanRequest()
    job = queue_discovery(db, channel=c, full=body.full, since=body.since)
    db.commit()
    return {"job_id": job.id}


@router.post("/scan-all", status_code=202)
def scan_all(db: Session = Depends(get_db)):
    ids = []
    for c in db.execute(select(Channel).where(Channel.active.is_(True))).scalars():
        ids.append(queue_discovery(db, channel=c).id)
    db.commit()
    return {"job_ids": ids}


@router.post("/{channel_id}/pause")
def pause(channel_id: str, db: Session = Depends(get_db)):
    c = db.get(Channel, channel_id)
    if not c:
        raise not_found("channel")
    n = Q.set_channel_paused(db, c, True)
    db.commit()
    return {"paused": True, "jobs_affected": n}


@router.post("/{channel_id}/resume")
def resume(channel_id: str, db: Session = Depends(get_db)):
    c = db.get(Channel, channel_id)
    if not c:
        raise not_found("channel")
    n = Q.set_channel_paused(db, c, False)
    db.commit()
    return {"paused": False, "jobs_affected": n}


@router.post("/{channel_id}/retry")
def retry(channel_id: str, include_permanent: bool = False, db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise not_found("channel")
    n = Q.retry_failed(db, channel_id=channel_id, include_permanent=include_permanent)
    db.commit()
    return {"retried": n}


@router.post("/{channel_id}/process-pending")
def process_pending(channel_id: str, db: Session = Depends(get_db)):
    c = db.get(Channel, channel_id)
    if not c:
        raise not_found("channel")
    n = queue_pending_for_channel(db, c)
    db.commit()
    return {"queued": n}


@router.put("/{channel_id}/priority")
def set_priority(channel_id: str, body: PriorityUpdate, db: Session = Depends(get_db)):
    c = db.get(Channel, channel_id)
    if not c:
        raise not_found("channel")
    Q.set_channel_priority(db, c, body.priority)
    db.commit()
    return {"priority": body.priority}
