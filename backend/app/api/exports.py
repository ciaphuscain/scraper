from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import bad_request, not_found
from app.database.session import get_db
from app.jobs.queue import enqueue
from app.models import ExportRecord
from app.schemas.requests import ExportRequest

router = APIRouter(prefix="/api/exports", tags=["exports"])


def _out(r: ExportRecord) -> dict:
    return {"id": r.id, "job_id": r.job_id, "scope": r.scope, "target_ids": r.target_ids, "content": r.content,
            "format": r.format, "status": r.status, "file_name": Path(r.file_path).name if r.file_path else None,
            "size_bytes": r.size_bytes, "item_count": r.item_count, "error": r.error, "created_at": r.created_at,
            "finished_at": r.finished_at}


@router.post("", status_code=202)
def create_export(body: ExportRequest, db: Session = Depends(get_db)):
    if body.scope != "all" and body.format != "sqlite" and not body.ids:
        raise bad_request("select at least one item to export")
    if body.scope in ("video",) and len(body.ids) != 1:
        raise bad_request("scope 'video' takes exactly one id")
    rec = ExportRecord(scope=body.scope, target_ids=body.ids, content=list(body.content), format=body.format)
    db.add(rec)
    db.flush()
    job = enqueue(db, "export", payload={"export_id": rec.id}, dedupe_key=f"export:{rec.id}", priority=40)
    rec.job_id = job.id
    db.commit()
    return _out(rec)


@router.get("")
def list_exports(db: Session = Depends(get_db)):
    rows = db.execute(select(ExportRecord).order_by(ExportRecord.id.desc()).limit(100)).scalars().all()
    return {"exports": [_out(r) for r in rows]}


@router.get("/{export_id}")
def get_export(export_id: int, db: Session = Depends(get_db)):
    r = db.get(ExportRecord, export_id)
    if not r:
        raise not_found("export")
    return _out(r)


@router.get("/{export_id}/download")
def download(export_id: int, db: Session = Depends(get_db)):
    r = db.get(ExportRecord, export_id)
    if not r or r.status != "completed" or not r.file_path:
        raise not_found("completed export")
    p = Path(r.file_path)
    if not p.exists():
        raise not_found("export file")
    return FileResponse(p, filename=p.name)
