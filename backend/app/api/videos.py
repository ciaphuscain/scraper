from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.api.deps import bad_request, not_found
from app.api.serializers import idea_out, job_out, transcript_out, video_out
from app.database.session import get_db
from app.jobs import queue as Q
from app.jobs.pipeline import queue_analysis, queue_transcript
from app.models import Channel, Idea, IdeaAnnotation, Job, JobEvent, Transcript, Video
from app.schemas.requests import BatchAction, VideoCreate
from app.services.exports import records as R
from app.services.search.fts import search_video_segments, to_fts_query
from app.services.transcripts.captions import segments_to_vtt
from app.services.youtube.urls import InvalidYouTubeURL, parse_video_url
from app.utils.time import fmt_ts

router = APIRouter(prefix="/api/videos", tags=["videos"])

SORTS = {
    "newest": (Video.upload_date.desc().nulls_last(), Video.id),
    "oldest": (Video.upload_date.asc().nulls_last(), Video.id),
    "title": (Video.title.asc(), Video.id),
    "duration": (Video.duration.desc().nulls_last(), Video.id),
    "ideas": (Video.idea_count.desc(), Video.id),
    "discovered": (Video.discovered_at.desc(), Video.id),
}


@router.get("")
def list_videos(
    channel_id: str | None = None,
    video_type: str | None = None,
    transcript_status: str | None = None,
    analysis_status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    q: str | None = None,
    selected: bool | None = None,
    sort: str = "newest",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    stmt = select(Video)
    if channel_id:
        stmt = stmt.where(Video.channel_id == channel_id)
    if video_type:
        stmt = stmt.where(Video.video_type.in_(video_type.split(",")))
    if transcript_status:
        stmt = stmt.where(Video.transcript_status.in_(transcript_status.split(",")))
    if analysis_status:
        stmt = stmt.where(Video.analysis_status.in_(analysis_status.split(",")))
    if date_from:
        stmt = stmt.where(Video.upload_date >= date_from.replace("-", ""))
    if date_to:
        stmt = stmt.where(Video.upload_date <= date_to.replace("-", ""))
    if selected is not None:
        stmt = stmt.where(Video.selected.is_(selected))
    if q and q.strip():
        fq = to_fts_query(q)
        if fq:
            stmt = stmt.where(text("videos.rowid IN (SELECT rowid FROM videos_fts WHERE videos_fts MATCH :fq)")
                              .bindparams(fq=fq))
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    stmt = stmt.order_by(*SORTS.get(sort, SORTS["newest"])).offset((page - 1) * page_size).limit(page_size)
    vids = db.execute(stmt).scalars().all()
    names = dict(db.execute(select(Channel.id, Channel.name)).all())
    return {"total": total, "page": page, "page_size": page_size,
            "videos": [video_out(v, names.get(v.channel_id)) for v in vids]}


@router.post("", status_code=202)
def add_video(body: VideoCreate, db: Session = Depends(get_db)):
    try:
        ref = parse_video_url(body.url)
    except InvalidYouTubeURL as exc:
        raise bad_request(str(exc)) from exc
    v = db.get(Video, ref.video_id)
    created = v is None
    if v is None:
        v = Video(id=ref.video_id, url=R.watch_url(ref.video_id), title="", listing_sources=[],
                  video_type="short" if ref.is_short_url else "video",
                  type_source="url" if ref.is_short_url else "default")
        db.add(v)
        db.flush()
    job = queue_transcript(db, v, priority=20)
    db.commit()
    return {"video_id": v.id, "created": created, "job_id": job.id}


@router.post("/batch")
def batch(body: BatchAction, db: Session = Depends(get_db)):
    vids = db.execute(select(Video).where(Video.id.in_(body.ids))).scalars().all()
    n = 0
    for v in vids:
        if body.action == "process":
            queue_transcript(db, v)
        elif body.action == "reprocess":
            queue_transcript(db, v, force=True)
        elif body.action == "analyze":
            if v.transcript_status != "completed":
                continue
            queue_analysis(db, v, force=True)
        elif body.action == "select":
            v.selected = True
        elif body.action == "deselect":
            v.selected = False
        elif body.action == "retry":
            for j in db.execute(select(Job).where(Job.video_id == v.id, Job.status == "failed")).scalars():
                Q.retry_job(db, j)
        elif body.action == "priority":
            for j in db.execute(select(Job).where(Job.video_id == v.id, Job.status.in_(Q.CLAIMABLE + ("paused",)))).scalars():
                j.priority = body.priority or 0
        n += 1
    db.commit()
    return {"affected": n}


@router.get("/{video_id}")
def get_video(video_id: str, db: Session = Depends(get_db)):
    v = db.get(Video, video_id)
    if not v:
        raise not_found("video")
    ch = db.get(Channel, v.channel_id) if v.channel_id else None
    transcripts = db.execute(select(Transcript).where(Transcript.video_id == video_id).order_by(Transcript.id.desc())).scalars().all()
    a = R.current_analysis(db, video_id)
    jobs = db.execute(select(Job).where(Job.video_id == video_id).order_by(Job.id.desc()).limit(30)).scalars().all()
    orphan_notes = db.execute(select(IdeaAnnotation).where(IdeaAnnotation.video_id == video_id,
                                                           IdeaAnnotation.idea_id.is_(None))).scalars().all()
    return {
        **video_out(v, ch.name if ch else None),
        "description": v.description,
        "tags": v.tags,
        "subtitle_languages": v.subtitle_languages,
        "listing_sources": v.listing_sources,
        "channel": {"id": ch.id, "name": ch.name, "url": ch.url} if ch else None,
        "transcripts": [transcript_out(t) for t in transcripts],
        "analysis": None if a is None else {
            "id": a.id, "model": a.model, "analysis_version": a.analysis_version, "prompt_versions": a.prompt_versions,
            "main_theme": a.main_theme, "central_thesis": a.central_thesis, "summary": a.summary, "topics": a.topics,
            "takeaways": a.takeaways, "relationships": a.relationships, "validation": a.validation,
            "chunk_count": a.chunk_count, "raw_idea_count": a.raw_idea_count, "created_at": a.created_at},
        "jobs": [job_out(j) for j in jobs],
        "orphaned_annotations": [{"id": o.id, "idea_title": o.idea_title_snapshot, "note": o.note, "tags": o.tags,
                                  "bookmarked": o.bookmarked} for o in orphan_notes],
    }


def _transcript(db: Session, video_id: str, transcript_id: int | None, kind: str) -> Transcript:
    if transcript_id:
        t = db.get(Transcript, transcript_id)
        if not t or t.video_id != video_id:
            raise not_found("transcript")
        return t
    t = db.execute(select(Transcript).where(Transcript.video_id == video_id, Transcript.kind == kind,
                                            Transcript.is_current.is_(True)).order_by(Transcript.id.desc())).scalars().first()
    if not t:
        raise not_found("transcript")
    return t


@router.get("/{video_id}/transcript")
def get_transcript(video_id: str, transcript_id: int | None = None, kind: str = "source", db: Session = Depends(get_db)):
    return transcript_out(_transcript(db, video_id, transcript_id, kind), include_segments=True)


@router.get("/{video_id}/transcript/search")
def transcript_search(video_id: str, q: str, db: Session = Depends(get_db)):
    return {"matches": search_video_segments(db, video_id, q)}


@router.get("/{video_id}/transcript/download")
def download_transcript(video_id: str, format: str = "txt", transcript_id: int | None = None,
                        kind: str = "source", db: Session = Depends(get_db)):
    v = db.get(Video, video_id)
    if not v:
        raise not_found("video")
    t = _transcript(db, video_id, transcript_id, kind)
    segs = [{"start": s.start, "end": s.end, "text": s.text} for s in t.segments]
    fname = f"{video_id}_transcript"
    if format == "txt":
        body, mt = R.transcript_txt(t), "text/plain"
    elif format == "timestamped":
        body, mt = "\n".join(f"[{fmt_ts(s['start'])}] {s['text']}" for s in segs), "text/plain"
    elif format == "vtt":
        body, mt = (t.raw_caption if t.raw_format == "vtt" and t.raw_caption else segments_to_vtt(segs)), "text/vtt"
    elif format == "json":
        body, mt = json.dumps(R.transcript_payload(v, t), ensure_ascii=False, indent=2, default=str), "application/json"
    elif format == "original" and t.raw_caption:
        body, mt = t.raw_caption, "text/plain"
        format = t.raw_format or "txt"
    else:
        raise bad_request("unsupported format")
    ext = {"timestamped": "txt"}.get(format, format)
    return Response(body, media_type=f"{mt}; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{fname}.{ext}"'})


@router.get("/{video_id}/ideas")
def video_ideas(video_id: str, db: Session = Depends(get_db)):
    v = db.get(Video, video_id)
    if not v:
        raise not_found("video")
    ideas = db.execute(select(Idea).where(Idea.video_id == video_id).order_by(Idea.ordinal)).scalars().all()
    anns = {a.idea_id: a for a in db.execute(select(IdeaAnnotation).where(IdeaAnnotation.video_id == video_id)).scalars()}
    ch = db.get(Channel, v.channel_id) if v.channel_id else None
    return {"ideas": [idea_out(i, video_title=v.title, channel_name=ch.name if ch else None, annotation=anns.get(i.id))
                      for i in ideas]}


@router.get("/{video_id}/summary.md", response_class=PlainTextResponse)
def summary_md(video_id: str, db: Session = Depends(get_db)):
    v = db.get(Video, video_id)
    if not v:
        raise not_found("video")
    ch = db.get(Channel, v.channel_id) if v.channel_id else None
    return R.summary_markdown(v, ch, R.current_analysis(db, video_id), R.video_ideas(db, video_id))


@router.post("/{video_id}/process", status_code=202)
def process(video_id: str, force: bool = False, db: Session = Depends(get_db)):
    v = db.get(Video, video_id)
    if not v:
        raise not_found("video")
    job = queue_transcript(db, v, force=force, priority=20)
    db.commit()
    return {"job_id": job.id}


@router.post("/{video_id}/analyze", status_code=202)
def analyze(video_id: str, db: Session = Depends(get_db)):
    v = db.get(Video, video_id)
    if not v:
        raise not_found("video")
    if v.transcript_status != "completed":
        raise bad_request("collect a transcript before running analysis")
    job = queue_analysis(db, v, force=True, priority=20)
    db.commit()
    return {"job_id": job.id}


@router.get("/{video_id}/history")
def history(video_id: str, db: Session = Depends(get_db)):
    events = db.execute(select(JobEvent).where(JobEvent.video_id == video_id).order_by(JobEvent.id.desc()).limit(300)).scalars().all()
    return {"events": [{"id": e.id, "job_id": e.job_id, "level": e.level, "message": e.message,
                        "created_at": e.created_at} for e in events]}
