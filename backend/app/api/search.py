from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.services.search.fts import search as fts_search

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("")
def search(
    q: str,
    kinds: str | None = None,
    channel_id: str | None = None,
    video_id: str | None = None,
    video_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sort: str = "relevance",
    limit: int = Query(30, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    return fts_search(db, q, kinds=kinds.split(",") if kinds else None, channel_id=channel_id, video_id=video_id,
                      video_type=video_type, date_from=date_from, date_to=date_to, sort=sort, limit=limit, offset=offset)
