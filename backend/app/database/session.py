"""Engine/session management. SQLite in WAL mode with foreign keys enforced."""
from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Iterator
from typing import Callable, TypeVar

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_env

log = logging.getLogger(__name__)
T = TypeVar("T")

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _configure_sqlite(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.close()


def make_engine(url: str) -> Engine:
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30}, pool_pre_ping=True)
    _configure_sqlite(engine)
    return engine


def init_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    if _engine is not None and (url is None or str(_engine.url) == url):
        return _engine
    if _engine is not None:
        _engine.dispose()
    _engine = make_engine(url or get_env().database_url)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_engine() -> Engine:
    return init_engine()


def SessionLocal() -> Session:  # noqa: N802 - factory
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


@contextlib.contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, rollback on error."""
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except BaseException:
        s.rollback()
        raise
    finally:
        s.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()


def with_db_retry(fn: Callable[[], T], attempts: int = 5) -> T:
    """Retry a unit of work when SQLite reports the database is locked."""
    delay = 0.2
    for i in range(attempts):
        try:
            return fn()
        except OperationalError as exc:
            if "locked" not in str(exc).lower() or i == attempts - 1:
                raise
            log.warning("database locked, retrying in %.1fs", delay)
            time.sleep(delay)
            delay *= 2
    raise RuntimeError("unreachable")
