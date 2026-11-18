from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Float, Integer, func, select, text
from sqlalchemy.orm import Session

from app.api.deps import not_found
from app.api.serializers import annotation_out, idea_out
from app.database.session import get_db
from app.models import Channel, Idea, IdeaAnnotation, Transcript, TranscriptSegment, Video
from app.schemas.requests import AnnotationUpdate
from app.services.search.fts import to_fts_query
from app.services.youtube.urls import watch_url

router = APIRouter(prefix="/api/ideas", tags=["ideas"])


@router.get("")
def list_ideas(
    q: str | None = None,
    channel_id: str | None = None,
    video_id: str | None = None,
    topic: str | None = None,
    idea_type: str | None = None,
    video_type: str | None = None,
    statement_kind: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    bookmarked: bool | None = None,
    tag: str | None = None,
    sort: str = "newest",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    stmt = select(Idea, IdeaAnnotation).outerjoin(IdeaAnnotation, IdeaAnnotation.idea_id == Idea.id)
    if channel_id:
        stmt = stmt.where(Idea.channel_id.in_(channel_id.split(",")))
    if video_id:
        stmt = stmt.where(Idea.video_id == video_id)
    if topic:
        stmt = stmt.where(Idea.topic.in_(topic.split("|")))
    if idea_type:
        stmt = stmt.where(Idea.idea_type.in_(idea_type.split(",")))
    if video_type:
        stmt = stmt.where(Idea.video_type.in_(video_type.split(",")))
    if statement_kind:
        stmt = stmt.where(Idea.statement_kind == statement_kind)
    if date_from:
        stmt = stmt.where(Idea.upload_date >= date_from.replace("-", ""))
    if date_to:
        stmt = stmt.where(Idea.upload_date <= date_to.replace("-", ""))
    if bookmarked:
        stmt = stmt.where(IdeaAnnotation.bookmarked.is_(True))
    if tag:
        stmt = stmt.where(text("EXISTS (SELECT 1 FROM json_each(idea_annotations.tags) WHERE lower(value) = lower(:tag))")
                          .bindparams(tag=tag))
    use_rank = False
    if q and q.strip():
        fq = to_fts_query(q)
        if fq:
            fts = (text("SELECT rowid AS rid, bm25(ideas_fts) AS rank FROM ideas_fts WHERE ideas_fts MATCH :fq")
                   .bindparams(fq=fq).columns(rid=Integer, rank=Float).subquery("fts"))
            stmt = stmt.join(fts, fts.c.rid == Idea.id)
            use_rank = sort == "relevance"
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    if use_rank:
        stmt = stmt.order_by(fts.c.rank)
    elif sort == "oldest":
        stmt = stmt.order_by(Idea.upload_date.asc().nulls_last(), Idea.video_id, Idea.ordinal)
    elif sort == "confidence":
        stmt = stmt.order_by(Idea.confidence.desc().nulls_last(), Idea.id)
    elif sort == "title":
        stmt = stmt.order_by(Idea.title)
    else:
        stmt = stmt.order_by(Idea.upload_date.desc().nulls_last(), Idea.video_id, Idea.ordinal)
    rows = db.execute(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    vids = {i.video_id for i, _ in rows}
    titles = dict(db.execute(select(Video.id, Video.title).where(Video.id.in_(vids))).all()) if vids else {}
    names = dict(db.execute(select(Channel.id, Channel.name)).all())
    return {"total": total, "page": page, "page_size": page_size,
            "ideas": [idea_out(i, video_title=titles.get(i.video_id), channel_name=names.get(i.channel_id), annotation=a)
                      for i, a in rows]}


@router.get("/facets")
def facets(channel_id: str | None = None, db: Session = Depends(get_db)):
    base = select(Idea.topic, func.count()).group_by(Idea.topic).order_by(func.count().desc())
    types = select(Idea.idea_type, func.count()).group_by(Idea.idea_type).order_by(func.count().desc())
    if channel_id:
        base = base.where(Idea.channel_id.in_(channel_id.split(",")))
        types = types.where(Idea.channel_id.in_(channel_id.split(",")))
    tags = db.execute(text("SELECT value, count(*) FROM idea_annotations, json_each(idea_annotations.tags) "
                           "GROUP BY lower(value) ORDER BY count(*) DESC LIMIT 200")).all()
    return {"topics": [{"value": t or "General", "count": n} for t, n in db.execute(base.limit(300)).all()],
            "idea_types": [{"value": t, "count": n} for t, n in db.execute(types).all()],
            "tags": [{"value": t, "count": n} for t, n in tags]}


@router.get("/{idea_id}")
def get_idea(idea_id: int, db: Session = Depends(get_db)):
    i = db.get(Idea, idea_id)
    if not i:
        raise not_found("idea")
    v = db.get(Video, i.video_id)
    ch = db.get(Channel, i.channel_id) if i.channel_id else None
    ann = db.execute(select(IdeaAnnotation).where(IdeaAnnotation.idea_id == idea_id)).scalar_one_or_none()
    segs = []
    if i.transcript_id and i.segment_keys:
        rows = db.execute(select(TranscriptSegment).where(TranscriptSegment.transcript_id == i.transcript_id,
                                                          TranscriptSegment.seg_key.in_(i.segment_keys))
                          .order_by(TranscriptSegment.idx)).scalars().all()
        segs = [{"id": s.seg_key, "start": s.start, "end": s.end, "text": s.text, "url": watch_url(i.video_id, s.start)}
                for s in rows]
    return {**idea_out(i, video_title=v.title if v else None, channel_name=ch.name if ch else None, annotation=ann),
            "source_segments": segs}


@router.put("/{idea_id}/annotation")
def annotate(idea_id: int, body: AnnotationUpdate, db: Session = Depends(get_db)):
    i = db.get(Idea, idea_id)
    if not i:
        raise not_found("idea")
    ann = db.execute(select(IdeaAnnotation).where(IdeaAnnotation.idea_id == idea_id)).scalar_one_or_none()
    if ann is None:
        ann = IdeaAnnotation(idea_id=idea_id, video_id=i.video_id, idea_title_snapshot=i.title,
                             segment_keys_snapshot=list(i.segment_keys or []), tags=[], bookmarked=False)
        db.add(ann)
    if body.note is not None:
        ann.note = body.note
    if body.tags is not None:
        ann.tags = body.tags
    if body.bookmarked is not None:
        ann.bookmarked = body.bookmarked
    ann.idea_title_snapshot = i.title
    ann.segment_keys_snapshot = list(i.segment_keys or [])
    db.commit()
    return annotation_out(ann)


@router.post("/export")
def export_ideas(body: dict, db: Session = Depends(get_db)):
    """Export a hand-picked set of ideas (JSON, CSV or Markdown), with attribution."""
    import json

    from fastapi.responses import Response

    from app.services.exports.archive import ideas_csv
    from app.services.exports.records import idea_dict
    from app.utils.time import fmt_ts

    ids = [int(x) for x in (body.get("ids") or [])][:10000]
    fmt = body.get("format", "json")
    if not ids:
        from app.api.deps import bad_request

        raise bad_request("no ideas selected")
    ideas = db.execute(select(Idea).where(Idea.id.in_(ids)).order_by(Idea.video_id, Idea.ordinal)).scalars().all()
    vids = {i.video_id for i in ideas}
    videos = {v.id: v for v in db.execute(select(Video).where(Video.id.in_(vids))).scalars()} if vids else {}
    names = dict(db.execute(select(Channel.id, Channel.name)).all())
    anns = {a.idea_id: a for a in db.execute(select(IdeaAnnotation).where(IdeaAnnotation.idea_id.in_(ids))).scalars()}
    rows = []
    for i in ideas:
        d = idea_dict(i, videos.get(i.video_id), names.get(i.channel_id))
        a = anns.get(i.id)
        d["note"], d["tags"], d["bookmarked"] = (a.note, a.tags, a.bookmarked) if a else (None, [], False)
        rows.append(d)
    if fmt == "csv":
        content, mt, ext = ideas_csv(rows), "text/csv", "csv"
    elif fmt == "md":
        lines = ["# Selected ideas", ""]
        for d in rows:
            ts = fmt_ts(d["start_time"]) if d["start_time"] is not None else "?"
            lines += [f"## {d['title']}", f"*{d['idea_type']} · {d['topic']} · {d['channel_name']} — "
                      f"[{d['video_title']} @ {ts}]({d['timestamp_url']})*", "", d["explanation"], ""]
            lines += [f"> {e.get('text', '')}" for e in d["excerpts"][:2]]
            if d["note"]:
                lines += ["", f"**Note:** {d['note']}"]
            lines.append("")
        content, mt, ext = "\n".join(lines), "text/markdown", "md"
    else:
        content, mt, ext = json.dumps({"count": len(rows), "ideas": rows}, ensure_ascii=False, indent=2, default=str), "application/json", "json"
    return Response(content, media_type=f"{mt}; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="ideas_export.{ext}"'})
