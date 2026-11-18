"""Context handed to job handlers for progress, checkpoints and cancellation."""
from __future__ import annotations

from typing import Any

from app.core.errors import JobCancelled
from app.core.settings_store import AppSettings, load_settings
from app.database.session import session_scope, with_db_retry
from app.jobs.queue import log_event
from app.models import Job
from app.utils.time import utcnow


class JobContext:
    def __init__(self, job_id: int, worker_id: str = "inline"):
        self.job_id = job_id
        self.worker_id = worker_id
        with session_scope() as s:
            job = s.get(Job, job_id)
            assert job is not None
            self.job_type = job.job_type
            self.channel_id = job.channel_id
            self.video_id = job.video_id
            self.payload: dict[str, Any] = dict(job.payload or {})
            self.checkpoint: dict[str, Any] = dict(job.checkpoint or {})
            self.attempts = job.attempts
            self.settings: AppSettings = load_settings(s)

    def update(self, *, stage: str | None = None, progress: float | None = None, save_checkpoint: bool = False,
               message: str | None = None) -> None:
        def _do() -> None:
            with session_scope() as s:
                job = s.get(Job, self.job_id)
                if job is None:
                    return
                if stage:
                    job.stage = stage
                if progress is not None:
                    job.progress = max(0.0, min(1.0, progress))
                if save_checkpoint:
                    job.checkpoint = dict(self.checkpoint)
                job.heartbeat_at = utcnow()
                if message:
                    log_event(s, job, message)
                action = job.requested_action
            if action in ("pause", "cancel"):
                raise JobCancelled(action)

        with_db_retry(_do)

    def stage(self, name: str, progress: float | None = None) -> None:
        self.update(stage=name, progress=progress)

    def save_checkpoint(self, **values: Any) -> None:
        self.checkpoint.update(values)
        self.update(save_checkpoint=True)

    def log(self, message: str, level: str = "info") -> None:
        with session_scope() as s:
            job = s.get(Job, self.job_id)
            if job:
                log_event(s, job, message, level)

    def heartbeat(self) -> None:
        self.update()
