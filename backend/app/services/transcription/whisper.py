"""Local speech-to-text with faster-whisper.

One model instance is cached per process and reused; it is swapped only when
the configuration changes, to avoid loading several large models in 16 GB.
"""
from __future__ import annotations

import gc
import logging
import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from app.core.errors import DependencyMissingError, PermanentError, TransientError
from app.core.settings_store import AppSettings
from app.services.transcripts.captions import Segment

log = logging.getLogger(__name__)


@dataclass
class WhisperResult:
    segments: list[Segment]
    language: str | None
    language_probability: float | None
    duration: float | None
    finished: bool
    model: str
    details: dict[str, Any]


class WhisperEngine:
    def __init__(self) -> None:
        self._model = None
        self._key: tuple | None = None
        self._lock = threading.Lock()

    def _load(self, settings: AppSettings):
        key = (settings.whisper_model, settings.whisper_device, settings.whisper_compute_type,
               settings.whisper_cpu_threads)
        if self._model is not None and self._key == key:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover - environment specific
            raise DependencyMissingError(str(exc), user_message="faster-whisper is not installed.") from exc
        self.unload()
        log.info("loading whisper model %s (%s/%s)", *key[:3])
        try:
            self._model = WhisperModel(
                settings.whisper_model,
                device=settings.whisper_device,
                compute_type=settings.whisper_compute_type,
                cpu_threads=settings.whisper_cpu_threads,
            )
        except (OSError, ValueError, RuntimeError) as exc:
            msg = str(exc)
            if "connect" in msg.lower() or "resolve" in msg.lower() or "huggingface" in msg.lower():
                raise TransientError(msg, user_message=(
                    f"Could not download Whisper model '{settings.whisper_model}'. "
                    "The first use needs internet access to huggingface.co.")) from exc
            raise PermanentError(msg, user_message=f"Failed to load Whisper model: {msg}") from exc
        self._key = key
        return self._model

    def unload(self) -> None:
        if self._model is not None:
            self._model = None
            self._key = None
            gc.collect()

    def transcribe(
        self,
        audio_path: Path,
        settings: AppSettings,
        progress: Callable[[float], None] | None = None,
    ) -> WhisperResult:
        if not audio_path.exists():
            raise TransientError(f"audio file missing: {audio_path}")
        with self._lock:
            model = self._load(settings)
            try:
                seg_iter, info = model.transcribe(
                    str(audio_path),
                    language=settings.whisper_language or None,
                    beam_size=settings.whisper_beam_size,
                    vad_filter=settings.whisper_vad,
                    condition_on_previous_text=False,  # reduces hallucinated repetition loops
                )
                segments: list[Segment] = []
                duration = getattr(info, "duration", None)
                for s in seg_iter:
                    text = (s.text or "").strip()
                    if not text:
                        continue
                    conf = None
                    if getattr(s, "avg_logprob", None) is not None:
                        import math

                        conf = round(math.exp(min(0.0, s.avg_logprob)), 4)
                    segments.append(Segment(float(s.start), float(s.end), text, conf))
                    if progress and duration:
                        progress(min(1.0, float(s.end) / duration))
            except FileNotFoundError as exc:
                raise DependencyMissingError(str(exc), user_message="Audio decoding failed (FFmpeg/PyAV missing?).") from exc
            except MemoryError as exc:
                self.unload()
                raise PermanentError("out of memory", user_message=(
                    "Whisper ran out of memory. Choose a smaller model in Settings.")) from exc
            except RuntimeError as exc:
                raise TransientError(str(exc), user_message=f"Whisper failed: {exc}") from exc
        return WhisperResult(
            segments=segments,
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
            duration=duration,
            finished=True,
            model=settings.whisper_model,
            details={
                "model": settings.whisper_model,
                "device": settings.whisper_device,
                "compute_type": settings.whisper_compute_type,
                "beam_size": settings.whisper_beam_size,
                "vad": settings.whisper_vad,
                "language_probability": getattr(info, "language_probability", None),
            },
        )


_engine: WhisperEngine | None = None


def get_engine() -> WhisperEngine:
    global _engine
    if _engine is None:
        _engine = WhisperEngine()
    return _engine


def set_engine(engine: Any) -> None:
    global _engine
    _engine = engine


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None
