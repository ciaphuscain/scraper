"""Full-text search over videos, transcript segments, ideas and channels (SQLite FTS5)."""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.youtube.urls import watch_url

KINDS = ("videos", "segments", "ideas", "channels")


def to_fts_query(q: str) -> str:
    """Turn free user input into a safe FTS5 query.

    Supports "quoted phrases", trailing * prefix, and OR. Everything else is
    quoted so FTS syntax characters in user input never raise errors.
    """
    q = (q or "").strip()
    if not q:
        return ""
    parts: list[str] = []
    for m in re.finditer(r'"([^"]+)"|(\S+)', q):
        phrase, word = m.group(1), m.group(2)
        if phrase:
            cleaned = phrase.replace('"', " ").strip()
            if cleaned:
                parts.append(f'"{cleaned}"')
            continue
        if word.upper() == "OR" and parts:
            parts.append("OR")
            continue
        prefix = word.endswith("*")
        w = re.sub(r"[^\w'-]", " ", word).strip()
        for tok in w.split():
            tok = tok.replace('"', "")
            parts.append(f'"{tok}"' + ("*" if prefix else ""))
    while parts and parts[-1] == "OR":
        parts.pop()
    return " ".join(parts)


def search(
    session: Session,
    q: str,
    *,
    kinds: list[str] | None = None,
    channel_id: str | None = None,
    video_id: str | None = None,
    video_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str = "relevance",
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    fq = to_fts_query(q)
    if not fq:
        return {"query": q, "results": [], "counts": {}}
    kinds = [k for k in (kinds or list(KINDS)) if k in KINDS]
    params: dict[str, Any] = {"q": fq, "limit": limit, "offset": offset}
    vfilters = []
    if channel_id:
        vfilters.append("v.channel_id = :channel_id")
        params["channel_id"] = channel_id
    if video_id:
        vfilters.append("v.id = :video_id")
        params["video_id"] = video_id
    if video_type:
        vfilters.append("v.video_type = :video_type")
        params["video_type"] = video_type
    if date_from:
        vfilters.append("v.upload_date >= :date_from")
        params["date_from"] = date_from.replace("-", "")
    if date_to:
        vfilters.append("v.upload_date <= :date_to")
        params["date_to"] = date_to.replace("-", "")
    vwhere = (" AND " + " AND ".join(vfilters)) if vfilters else ""
    order = "rank" if sort == "relevance" else ("v.upload_date DESC" if sort == "newest" else "v.upload_date ASC")

    results: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    def run(kind: str, sql: str, count_sql: str) -> None:
        rows = session.execute(text(sql), params).mappings().all()
        counts[kind] = session.execute(text(count_sql), params).scalar() or 0
        for r in rows:
            d = dict(r)
            d["kind"] = kind
            results.append(d)

    if "ideas" in kinds:
        base = f"""FROM ideas_fts f JOIN ideas i ON i.id = f.rowid JOIN videos v ON v.id = i.video_id
                   LEFT JOIN channels c ON c.id = v.channel_id WHERE ideas_fts MATCH :q{vwhere}"""
        run("ideas", f"""SELECT i.id AS idea_id, i.title AS title, snippet(ideas_fts, 1, '[[', ']]', '…', 24) AS snippet,
                 i.idea_type, i.topic, i.start_time AS start, v.id AS video_id, v.title AS video_title,
                 v.upload_date, v.video_type, c.id AS channel_id, c.name AS channel_name, bm25(ideas_fts) AS rank
                 {base} ORDER BY {order} LIMIT :limit OFFSET :offset""", f"SELECT count(*) {base}")
    if "segments" in kinds:
        base = f"""FROM segments_fts f JOIN transcript_segments s ON s.id = f.rowid
                   JOIN transcripts t ON t.id = s.transcript_id AND t.is_current = 1
                   JOIN videos v ON v.id = s.video_id LEFT JOIN channels c ON c.id = v.channel_id
                   WHERE segments_fts MATCH :q{vwhere}"""
        run("segments", f"""SELECT s.id AS segment_id, s.seg_key, snippet(segments_fts, 0, '[[', ']]', '…', 24) AS snippet,
                 s.start AS start, s.end AS end, t.kind AS transcript_kind, v.id AS video_id, v.title AS video_title,
                 v.upload_date, v.video_type, c.id AS channel_id, c.name AS channel_name, bm25(segments_fts) AS rank
                 {base} ORDER BY {order} LIMIT :limit OFFSET :offset""", f"SELECT count(*) {base}")
    if "videos" in kinds:
        base = f"""FROM videos_fts f JOIN videos v ON v.rowid = f.rowid LEFT JOIN channels c ON c.id = v.channel_id
                   WHERE videos_fts MATCH :q{vwhere}"""
        run("videos", f"""SELECT v.id AS video_id, v.title AS title, v.title AS video_title,
                 snippet(videos_fts, 1, '[[', ']]', '…', 24) AS snippet, v.upload_date, v.video_type,
                 v.thumbnail_url, c.id AS channel_id, c.name AS channel_name, bm25(videos_fts) AS rank
                 {base} ORDER BY {order} LIMIT :limit OFFSET :offset""", f"SELECT count(*) {base}")
    if "channels" in kinds and not video_id:
        cf = " AND c.id = :channel_id" if channel_id else ""
        base = f"FROM channels_fts f JOIN channels c ON c.rowid = f.rowid WHERE channels_fts MATCH :q{cf}"
        run("channels", f"""SELECT c.id AS channel_id, c.name AS title, c.name AS channel_name,
                 snippet(channels_fts, 1, '[[', ']]', '…', 24) AS snippet, c.thumbnail_url, bm25(channels_fts) AS rank
                 {base} ORDER BY rank LIMIT :limit OFFSET :offset""", f"SELECT count(*) {base}")

    for r in results:
        if r.get("video_id"):
            r["url"] = watch_url(r["video_id"], r.get("start"))
    if sort == "relevance":
        results.sort(key=lambda r: r.get("rank") or 0)
    return {"query": q, "fts_query": fq, "results": results, "counts": counts}


def search_video_segments(session: Session, video_id: str, q: str, limit: int = 500) -> list[dict[str, Any]]:
    fq = to_fts_query(q)
    if not fq:
        return []
    rows = session.execute(text(
        """SELECT s.seg_key, s.start, s.end, s.text FROM segments_fts f JOIN transcript_segments s ON s.id = f.rowid
           JOIN transcripts t ON t.id = s.transcript_id AND t.is_current = 1 AND t.kind = 'source'
           WHERE segments_fts MATCH :q AND s.video_id = :vid ORDER BY s.start LIMIT :limit"""),
        {"q": fq, "vid": video_id, "limit": limit}).mappings().all()
    return [dict(r) for r in rows]
