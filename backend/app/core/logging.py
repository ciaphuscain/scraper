"""Standard-library logging setup with rotating files."""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

_CONFIGURED: set[str] = set()


def setup_logging(log_dir: Path, name: str = "app", level: str = "INFO", retention_days: int = 14) -> None:
    if name in _CONFIGURED:
        return
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(level.upper())
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s [%(process)d:%(threadName)s] %(name)s: %(message)s")
    fh = logging.handlers.TimedRotatingFileHandler(
        log_dir / f"{name}.log", when="midnight", backupCount=max(1, retention_days), encoding="utf-8"
    )
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    root.addHandler(fh)
    root.addHandler(sh)
    for noisy in ("httpx", "httpcore", "faster_whisper"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED.add(name)
