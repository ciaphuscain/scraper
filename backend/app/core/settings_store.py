"""Persistent, validated runtime settings stored in the ``app_settings`` table."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_env
from app.models import AppSetting

WhisperModel = Literal[
    "tiny", "tiny.en", "base", "base.en", "small", "small.en", "medium", "medium.en",
    "large-v2", "large-v3", "large-v3-turbo", "distil-large-v3",
]


class AppSettings(BaseModel):
    # --- queue / resources
    download_concurrency: int = Field(2, ge=1, le=8, description="Parallel network jobs (metadata, captions, audio).")
    processing_concurrency: int = Field(1, ge=1, le=4, description="Parallel CPU transcription jobs.")
    llm_concurrency: int = Field(1, ge=1, le=4, description="Parallel LLM analysis jobs.")
    allow_parallel_heavy: bool = Field(False, description="Allow Whisper and Ollama to run at the same time.")
    request_delay_seconds: float = Field(2.0, ge=0, le=120, description="Delay between YouTube requests.")
    max_retries: int = Field(4, ge=1, le=10)
    queue_paused: bool = False
    auto_process_new_videos: bool = Field(True, description="Queue transcript collection after discovery.")
    auto_analyze: bool = Field(True, description="Queue AI analysis when a transcript is collected.")

    # --- transcripts
    preferred_languages: list[str] = Field(default_factory=lambda: ["en"])
    allow_auto_captions: bool = True
    whisper_fallback_enabled: bool = True
    whisper_model: WhisperModel = "small"
    whisper_device: Literal["cpu", "cuda", "auto"] = "cpu"
    whisper_compute_type: Literal["int8", "int8_float32", "int8_float16", "float16", "float32", "default"] = "int8"
    whisper_language: str | None = Field(None, description="Force a language code; empty = auto-detect.")
    whisper_vad: bool = True
    whisper_beam_size: int = Field(5, ge=1, le=10)
    whisper_cpu_threads: int = Field(0, ge=0, le=64, description="0 = library default.")

    # --- AI
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen2.5:7b"
    llm_temperature: float = Field(0.1, ge=0, le=2)
    llm_context_size: int = Field(8192, ge=2048, le=131072)
    llm_max_tokens: int = Field(3072, ge=256, le=32768)
    llm_timeout_seconds: int = Field(900, ge=30, le=7200)
    llm_retries: int = Field(3, ge=1, le=8)
    chunk_tokens: int = Field(1200, ge=200, le=16000)
    chunk_overlap_segments: int = Field(1, ge=0, le=10)
    llm_semantic_dedupe: bool = Field(True, description="Ask the LLM to confirm borderline duplicate merges.")

    # --- files
    output_dir: str = ""
    retain_audio: bool = False
    cleanup_failed_audio: bool = True
    write_files_on_completion: bool = Field(True, description="Write per-video archive files as work completes.")
    export_default_format: Literal["zip", "json", "jsonl", "csv", "md", "txt"] = "zip"
    log_retention_days: int = Field(14, ge=1, le=365)

    @field_validator("preferred_languages")
    @classmethod
    def _langs(cls, v: list[str]) -> list[str]:
        out = [x.strip() for x in v if x and x.strip()]
        if not out:
            raise ValueError("at least one preferred language is required")
        for lang in out:
            if len(lang) > 16 or not all(c.isalnum() or c in "-_" for c in lang):
                raise ValueError(f"invalid language code: {lang!r}")
        return out

    @field_validator("ollama_url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError("Ollama URL must start with http:// or https://")
        return v

    @field_validator("whisper_language")
    @classmethod
    def _wlang(cls, v: str | None) -> str | None:
        return (v or "").strip() or None

    @field_validator("ollama_model")
    @classmethod
    def _model(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("an Ollama model name is required")
        return v

    @field_validator("output_dir")
    @classmethod
    def _out(cls, v: str) -> str:
        v = (v or "").strip()
        if v:
            p = Path(v).expanduser()
            if p.exists() and not p.is_dir():
                raise ValueError("output directory points to a file")
        return v

    @model_validator(mode="after")
    def _ctx(self) -> AppSettings:
        if self.chunk_tokens * 2 + 1000 > self.llm_context_size:
            raise ValueError(
                "chunk_tokens is too large for llm_context_size (need context >= 2*chunk_tokens + 1000)"
            )
        return self

    @property
    def archive_root(self) -> Path:
        return Path(self.output_dir).expanduser() if self.output_dir else get_env().archive_dir


DEFAULTS = AppSettings()


def load_settings(session: Session) -> AppSettings:
    rows = session.execute(select(AppSetting)).scalars().all()
    data: dict[str, Any] = DEFAULTS.model_dump()
    for row in rows:
        if row.key in data:
            data[row.key] = row.value
    try:
        return AppSettings(**data)
    except Exception:
        # A stored value became invalid (e.g. schema change): fall back field by field.
        clean = DEFAULTS.model_dump()
        for k, v in data.items():
            trial = dict(clean, **{k: v})
            try:
                AppSettings(**trial)
                clean[k] = v
            except Exception:
                pass
        return AppSettings(**clean)


def save_settings(session: Session, updates: dict[str, Any]) -> AppSettings:
    current = load_settings(session).model_dump()
    unknown = set(updates) - set(current)
    if unknown:
        raise ValueError(f"unknown settings: {', '.join(sorted(unknown))}")
    current.update(updates)
    validated = AppSettings(**current)  # raises ValidationError
    if validated.output_dir:
        Path(validated.output_dir).expanduser().mkdir(parents=True, exist_ok=True)
    for key, value in validated.model_dump().items():
        row = session.get(AppSetting, key)
        if row is None:
            session.add(AppSetting(key=key, value=value))
        elif row.value != value:
            row.value = value
    session.flush()
    return validated


def ensure_defaults(session: Session) -> None:
    existing = {r.key for r in session.execute(select(AppSetting)).scalars()}
    for key, value in DEFAULTS.model_dump().items():
        if key not in existing:
            session.add(AppSetting(key=key, value=value))
