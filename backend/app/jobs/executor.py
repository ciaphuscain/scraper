"""Run a single claimed job and record the outcome."""
from __future__ import annotations

import logging
import traceback

from app.core.errors import JobCancelled
from app.database.session import session_scope, with_db_retry
from app.jobs.context import JobContext
from app.jobs.handlers import HANDLERS, on_final_failure
from app.jobs.queue import log_event, mark_completed, mark_failed
from app.models import Job
from app.utils.time import utcnow

log = logging.getLogger(__name__)


def execute(job_id: int, worker_id: str = "inline") -> str:
    """Execute a job that is already in ``running`` state. Returns final status."""
    ctx = JobContext(job_id, worker_id)
    handler = HANDLERS.get(ctx.job_type)
    try:
        if handler is None:
            raise RuntimeError(f"no handler for {ctx.job_type}")
        result = handler(ctx)
    except JobCancelled as jc:
        action = str(jc)

        def _cancel() -> str:
            with session_scope() as s:
                job = s.get(Job, job_id)
                if job is None:
                    return "missing"
                job.requested_action = None
                job.attempts = max(0, job.attempts - 1)
                if action == "cancel":
                    job.status, job.stage, job.finished_at = "cancelled", "cancelled", utcnow()
                else:
                    job.status, job.stage = "paused", "paused"
                log_event(s, job, f"{job.status} by user")
                return job.status

        return with_db_retry(_cancel)
    except Exception as exc:  # noqa: BLE001
        log.warning("job %s (%s) failed: %s", job_id, ctx.job_type, exc)
        log.debug("%s", traceback.format_exc())

        def _fail() -> str:
            with session_scope() as s:
                job = s.get(Job, job_id)
                if job is None:
                    return "missing"
                status = mark_failed(s, job, exc)
                if status == "failed":
                    on_final_failure(job, s)
                return status

        return with_db_retry(_fail)

    def _done() -> str:
        with session_scope() as s:
            job = s.get(Job, job_id)
            if job is None:
                return "missing"
            mark_completed(s, job, result)
            return "completed"

    return with_db_retry(_done)
