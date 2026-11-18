"""Error taxonomy used by the job system to decide on retries."""
from __future__ import annotations


class StudioError(Exception):
    """Base class. ``user_message`` is shown in the UI."""

    transient: bool = False
    kind: str = "error"

    def __init__(self, message: str, *, user_message: str | None = None):
        super().__init__(message)
        self.user_message = user_message or message


class TransientError(StudioError):
    """Retry with exponential backoff (network blips, HTTP 429, DB locked)."""

    transient = True
    kind = "transient"


class RateLimitedError(TransientError):
    kind = "rate_limited"


class PermanentError(StudioError):
    """Never retried automatically (private/removed video, bad input)."""

    kind = "permanent"


class VideoUnavailableError(PermanentError):
    kind = "unavailable"


class DependencyMissingError(PermanentError):
    """A local dependency (FFmpeg, faster-whisper) is missing."""

    kind = "dependency_missing"


class DeferredError(StudioError):
    """Job cannot run right now (e.g. Ollama offline). Rescheduled without
    consuming a retry attempt."""

    kind = "deferred"

    def __init__(self, message: str, *, delay_seconds: int = 300, user_message: str | None = None):
        super().__init__(message, user_message=user_message)
        self.delay_seconds = delay_seconds


class InvalidAIOutputError(TransientError):
    kind = "invalid_ai_output"


class JobCancelled(Exception):
    """Raised inside a handler when the job was cancelled/paused by the user."""


def classify_os_error(exc: OSError) -> StudioError:
    import errno

    if exc.errno == errno.ENOSPC:
        return PermanentError(str(exc), user_message="Disk is full. Free space and retry the job.")
    if exc.errno in (errno.EACCES, errno.EPERM):
        return PermanentError(str(exc), user_message=f"Permission denied: {exc.filename}. Check folder permissions.")
    return TransientError(str(exc))
