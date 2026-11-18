from __future__ import annotations

import platform
import shutil
import sys

from fastapi import APIRouter, Depends
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import bad_request, not_found
from app.api.serializers import channel_out, job_out
from app.core.config import get_env
from app.core.settings_store import AppSettings, load_settings, save_settings
from app.database.session import get_db
from app.jobs import queue as Q
from app.models import AppSetting, Channel, Idea, Job, PromptTemplate, Transcript, Video
from app.schemas.requests import OllamaTest, PromptUpdate
from app.services.ai import prompts as P
from app.services.ai.ollama import OllamaClient
from app.workers.runner import HEARTBEAT_KEY, worker_online

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/system/status")
def system_status(db: Session = Depends(get_db)):
    st = load_settings(db)
    env = get_env()
    hb = db.get(AppSetting, HEARTBEAT_KEY)
    ollama = OllamaClient(st.ollama_url)
    version = ollama.version()
    try:
        import faster_whisper  # noqa: F401

        fw = True
    except ImportError:
        fw = False
    try:
        import yt_dlp

        ytv = yt_dlp.version.__version__
    except Exception:  # pragma: no cover
        ytv = None
    disk = shutil.disk_usage(env.archive_dir)
    return {
        "worker": {"online": worker_online(hb.value if hb else None), "status": hb.value if hb else None},
        "ollama": {"online": version is not None, "version": version, "url": st.ollama_url, "model": st.ollama_model},
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "faster_whisper": fw,
        "yt_dlp": ytv,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "database": str(env.db_path),
        "archive_dir": str(st.archive_root),
        "disk_free_gb": round(disk.free / 1e9, 1),
        "queue_paused": st.queue_paused,
    }


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    def count(q):
        return db.execute(q).scalar() or 0

    jobs = Q.counts(db)
    active = db.execute(select(Job).where(Job.status == "running").order_by(Job.started_at)).scalars().all()
    titles = dict(db.execute(select(Video.id, Video.title).where(Video.id.in_([j.video_id for j in active if j.video_id]))).all())
    names = dict(db.execute(select(Channel.id, Channel.name)).all())
    recent = db.execute(select(Channel).where(Channel.active.is_(True)).order_by(Channel.updated_at.desc()).limit(6)).scalars().all()
    recent_fail = db.execute(select(Job).where(Job.status == "failed").order_by(Job.finished_at.desc()).limit(5)).scalars().all()
    return {
        "channels": count(select(func.count()).select_from(Channel).where(Channel.active.is_(True))),
        "videos": count(select(func.count()).select_from(Video).where(Video.video_type != "short")),
        "shorts": count(select(func.count()).select_from(Video).where(Video.video_type == "short")),
        "transcripts": count(select(func.count(func.distinct(Transcript.video_id))).where(Transcript.kind == "source")),
        "ideas": count(select(func.count()).select_from(Idea)),
        "analysed_videos": count(select(func.count()).select_from(Video).where(Video.analysis_status == "completed")),
        "unavailable": count(select(func.count()).select_from(Video).where(Video.transcript_status == "unavailable")),
        "jobs": {"pending": jobs.get("queued", 0) + jobs.get("retry_scheduled", 0), "active": jobs.get("running", 0),
                 "failed": jobs.get("failed", 0), "completed": jobs.get("completed", 0), "paused": jobs.get("paused", 0),
                 "retry_scheduled": jobs.get("retry_scheduled", 0)},
        "active_jobs": [job_out(j, video_title=titles.get(j.video_id), channel_name=names.get(j.channel_id)) for j in active],
        "recent_failures": [job_out(j, channel_name=names.get(j.channel_id)) for j in recent_fail],
        "recent_channels": [channel_out(c) for c in recent],
    }


# -------------------------------------------------------------- settings

@router.get("/settings")
def get_settings(db: Session = Depends(get_db)):
    st = load_settings(db)
    schema = AppSettings.model_json_schema()
    return {"values": st.model_dump(), "schema": schema["properties"], "effective_archive_dir": str(st.archive_root)}


@router.put("/settings")
def put_settings(body: dict, db: Session = Depends(get_db)):
    try:
        st = save_settings(db, body)
    except ValidationError as exc:
        errors = [{"field": ".".join(str(x) for x in e["loc"]) or "settings", "message": e["msg"]} for e in exc.errors()]
        from fastapi import HTTPException

        raise HTTPException(status_code=422, detail={"errors": errors}) from exc
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    except OSError as exc:
        raise bad_request(f"could not create output directory: {exc}") from exc
    db.commit()
    return {"values": st.model_dump(), "effective_archive_dir": str(st.archive_root)}


# -------------------------------------------------------------- prompts

@router.get("/prompts")
def list_prompts(db: Session = Depends(get_db)):
    out = []
    for key in P.DEFAULT_PROMPTS:
        p = P.get_active(db, key)
        out.append({"key": key, "description": P.PROMPT_DESCRIPTIONS[key], "version": p.version, "body": p.body,
                    "is_default": p.body == P.DEFAULT_PROMPTS[key], "updated_at": p.created_at})
    db.commit()
    return {"prompts": out}


@router.get("/prompts/{key}/versions")
def prompt_versions(key: str, db: Session = Depends(get_db)):
    if key not in P.DEFAULT_PROMPTS:
        raise not_found("prompt")
    rows = db.execute(select(PromptTemplate).where(PromptTemplate.key == key).order_by(PromptTemplate.version.desc())).scalars().all()
    return {"versions": [{"version": r.version, "is_active": r.is_active, "is_default": r.is_default,
                          "created_at": r.created_at, "body": r.body} for r in rows]}


@router.put("/prompts/{key}")
def update_prompt(key: str, body: PromptUpdate, db: Session = Depends(get_db)):
    if key not in P.DEFAULT_PROMPTS:
        raise not_found("prompt")
    try:
        p = P.save_new_version(db, key, body.body)
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    db.commit()
    return {"key": key, "version": p.version}


@router.post("/prompts/{key}/reset")
def reset_prompt(key: str, db: Session = Depends(get_db)):
    if key not in P.DEFAULT_PROMPTS:
        raise not_found("prompt")
    p = P.reset_to_default(db, key)
    db.commit()
    return {"key": key, "version": p.version}


# -------------------------------------------------------------- ollama

@router.get("/ollama/models")
def ollama_models(db: Session = Depends(get_db)):
    st = load_settings(db)
    try:
        models = OllamaClient(st.ollama_url).list_models()
    except Exception as exc:  # noqa: BLE001
        return {"online": False, "error": getattr(exc, "user_message", str(exc)), "models": []}
    return {"online": True, "models": [{"name": m.get("name"), "size": m.get("size"),
                                        "parameter_size": (m.get("details") or {}).get("parameter_size"),
                                        "quantization": (m.get("details") or {}).get("quantization_level")}
                                       for m in models]}


@router.post("/ollama/test")
def ollama_test(body: OllamaTest, db: Session = Depends(get_db)):
    st = load_settings(db)
    url = (body.url or st.ollama_url).rstrip("/")
    model = body.model or st.ollama_model
    client = OllamaClient(url, timeout=120)
    version = client.version()
    if version is None:
        return {"ok": False, "stage": "connect", "message": f"Cannot reach Ollama at {url}. Is it running?"}
    try:
        names = [m.get("name") for m in client.list_models()]
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "stage": "models", "message": str(exc)}
    if model not in names and f"{model}:latest" not in names:
        return {"ok": False, "stage": "model", "version": version, "models": names,
                "message": f"Model '{model}' is not installed. Run: ollama pull {model}"}
    try:
        from app.services.ai.ollama import parse_json_loose

        raw = client.chat(model, [{"role": "user", "content": 'Reply with JSON {"ok": true}'}],
                          schema={"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]},
                          num_predict=20, num_ctx=2048)
        parsed = parse_json_loose(raw)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "stage": "generate", "version": version, "message": getattr(exc, "user_message", str(exc))}
    return {"ok": True, "version": version, "model": model, "response": parsed}
