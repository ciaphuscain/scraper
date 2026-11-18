from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import not_found
from app.database.session import get_db
from app.jobs.queue import enqueue
from app.models import Channel, ChannelReport, CrossChannelReport
from app.schemas.requests import CrossChannelRequest

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _rep(r: ChannelReport) -> dict:
    return {"id": r.id, "channel_id": r.channel_id, "data": r.data, "narrative": r.narrative, "markdown": r.markdown,
            "model": r.model, "prompt_version": r.prompt_version, "created_at": r.created_at}


@router.get("/channels/{channel_id}")
def latest_channel_report(channel_id: str, db: Session = Depends(get_db)):
    r = db.execute(select(ChannelReport).where(ChannelReport.channel_id == channel_id)
                   .order_by(ChannelReport.id.desc())).scalars().first()
    return {"report": _rep(r) if r else None}


@router.post("/channels/{channel_id}", status_code=202)
def generate_channel_report(channel_id: str, use_llm: bool = True, db: Session = Depends(get_db)):
    if not db.get(Channel, channel_id):
        raise not_found("channel")
    job = enqueue(db, "channel_report", channel_id=channel_id, payload={"use_llm": use_llm}, priority=30)
    db.commit()
    return {"job_id": job.id}


@router.post("/cross-channel", status_code=202)
def cross_channel(body: CrossChannelRequest, db: Session = Depends(get_db)):
    ids = sorted(set(body.channel_ids))
    job = enqueue(db, "cross_channel_report", payload={"channel_ids": ids, "validate": body.validate_semantics,
                                                       "max_pairs": body.max_pairs},
                  dedupe_key="cross_channel_report:" + ",".join(ids), priority=30)
    db.commit()
    return {"job_id": job.id}


@router.get("/cross-channel")
def list_cross(db: Session = Depends(get_db)):
    rows = db.execute(select(CrossChannelReport).order_by(CrossChannelReport.id.desc()).limit(50)).scalars().all()
    return {"reports": [{"id": r.id, "channel_ids": r.channel_ids, "created_at": r.created_at, "model": r.model,
                         "semantic_validation": r.semantic_validation,
                         "channels": r.data.get("channels", [])} for r in rows]}


@router.get("/cross-channel/{report_id}")
def get_cross(report_id: int, db: Session = Depends(get_db)):
    r = db.get(CrossChannelReport, report_id)
    if not r:
        raise not_found("report")
    return {"id": r.id, "channel_ids": r.channel_ids, "data": r.data, "markdown": r.markdown, "model": r.model,
            "semantic_validation": r.semantic_validation, "created_at": r.created_at}
