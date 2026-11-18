from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import not_found
from app.api.serializers import job_out
from app.core.settings_store import save_settings
from app.database.session import get_db
from app.jobs import queue as Q
from app.models import Channel, Job, JobEvent, Video
from app.schemas.requests import PriorityUpdate

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    status: str | None = None,
    lane: str | None = None,
    job_type: str | None = None,
    channel_id: str | None = None,
    video_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    stmt = select(Job)
    if status:
        stmt = stmt.where(Job.status.in_(status.split(",")))
    if lane:
        stmt = stmt.where(Job.lane == lane)
    if job_type:
        stmt = stmt.where(Job.job_type.in_(job_type.split(",")))
    if channel_id:
        stmt = stmt.where(Job.channel_id == channel_id)
    if video_id:
        stmt = stmt.where(Job.video_id == video_id)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    # running first, then by priority / recency
    order = func.instr("running,queued,retry_scheduled,paused,failed,cancelled,completed", Job.status)
    jobs = db.execute(stmt.order_by(order, Job.priority.desc(), Job.id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).scalars().all()
    vids = {j.video_id for j in jobs if j.video_id}
    titles = dict(db.execute(select(Video.id, Video.title).where(Video.id.in_(vids))).all()) if vids else {}
    names = dict(db.execute(select(Channel.id, Channel.name)).all())
    return {"total": total, "page": page, "page_size": page_size,
            "jobs": [job_out(j, video_title=titles.get(j.video_id), channel_name=names.get(j.channel_id)) for j in jobs]}


@router.get("/counts")
def job_counts(db: Session = Depends(get_db)):
    by_status = Q.counts(db)
    by_lane = {f"{lane}:{st}": n for lane, st, n in db.execute(
        select(Job.lane, Job.status, func.count()).where(Job.status.in_(("queued", "running", "retry_scheduled")))
        .group_by(Job.lane, Job.status)).all()}
    return {"by_status": by_status, "by_lane": by_lane}


def _get(db: Session, job_id: int) -> Job:
    j = db.get(Job, job_id)
    if not j:
        raise not_found("job")
    return j


@router.get("/{job_id}")
def get_job(job_id: int, db: Session = Depends(get_db)):
    j = _get(db, job_id)
    events = db.execute(select(JobEvent).where(JobEvent.job_id == job_id).order_by(JobEvent.id)).scalars().all()
    return {**job_out(j), "checkpoint_keys": list((j.checkpoint or {}).keys()),
            "events": [{"level": e.level, "message": e.message, "created_at": e.created_at} for e in events]}


@router.post("/{job_id}/pause")
def pause(job_id: int, db: Session = Depends(get_db)):
    j = _get(db, job_id)
    Q.pause_job(db, j)
    db.commit()
    return job_out(j)


@router.post("/{job_id}/resume")
def resume(job_id: int, db: Session = Depends(get_db)):
    j = _get(db, job_id)
    Q.resume_job(db, j)
    db.commit()
    return job_out(j)


@router.post("/{job_id}/cancel")
def cancel(job_id: int, db: Session = Depends(get_db)):
    j = _get(db, job_id)
    Q.cancel_job(db, j)
    db.commit()
    return job_out(j)


@router.post("/{job_id}/retry")
def retry(job_id: int, db: Session = Depends(get_db)):
    j = Q.retry_job(db, _get(db, job_id))
    db.commit()
    return job_out(j)


@router.put("/{job_id}/priority")
def priority(job_id: int, body: PriorityUpdate, db: Session = Depends(get_db)):
    j = _get(db, job_id)
    j.priority = body.priority
    db.commit()
    return job_out(j)


@router.post("/pause-all")
def pause_all(db: Session = Depends(get_db)):
    save_settings(db, {"queue_paused": True})
    db.commit()
    return {"queue_paused": True}


@router.post("/resume-all")
def resume_all(db: Session = Depends(get_db)):
    save_settings(db, {"queue_paused": False})
    db.commit()
    return {"queue_paused": False}


@router.post("/retry-failed")
def retry_failed(include_permanent: bool = False, db: Session = Depends(get_db)):
    n = Q.retry_failed(db, include_permanent=include_permanent)
    db.commit()
    return {"retried": n}


@router.post("/clear-finished")
def clear_finished(db: Session = Depends(get_db)):
    from sqlalchemy import delete

    res = db.execute(delete(Job).where(Job.status.in_(("completed", "cancelled"))))
    db.commit()
    return {"deleted": res.rowcount}
