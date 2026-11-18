from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture()
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv("YTCS_ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setenv("YTCS_LOG_DIR", str(tmp_path / "logs"))
    from app.core.config import reset_env_cache

    reset_env_cache()
    from app.database import session as S
    from app.database.init_db import init_db

    S._engine = None
    S._SessionLocal = None
    init_db()
    yield tmp_path / "archive"
    if S._engine is not None:
        S._engine.dispose()
    S._engine = None
    reset_env_cache()


@pytest.fixture()
def db(archive):
    from app.database.session import SessionLocal

    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture()
def fake_yt():
    from fakes import FakeYouTube

    from app.services.youtube import client

    f = FakeYouTube()
    client.set_client(f)
    yield f
    client.set_client(None)


@pytest.fixture()
def fake_whisper():
    from fakes import FakeWhisper

    from app.services.transcription import whisper

    f = FakeWhisper()
    whisper.set_engine(f)
    yield f
    whisper.set_engine(None)


@pytest.fixture()
def fake_llm(monkeypatch):
    from fakes import FakeLLM

    from app.jobs import handlers

    llm = FakeLLM()
    monkeypatch.setattr(handlers, "_llm", lambda ctx, required=True: llm)
    return llm


@pytest.fixture()
def no_delay(db):
    from app.core.settings_store import save_settings

    save_settings(db, {"request_delay_seconds": 0})
    db.commit()


def run_jobs(max_jobs: int = 200) -> list[tuple[int, str, str]]:
    """Drain all lanes inline (deterministic replacement for the worker)."""
    from app.database.session import session_scope
    from app.jobs.executor import execute
    from app.jobs.queue import claim

    done = []
    for _ in range(max_jobs):
        job_id = None
        for lane in ("network", "cpu", "llm", "general"):
            with session_scope() as s:
                j = claim(s, lane, "test")
                if j:
                    job_id, jtype = j.id, j.job_type
                    break
        if job_id is None:
            return done
        done.append((job_id, jtype, execute(job_id, "test")))
    raise AssertionError("job queue did not drain")


@pytest.fixture()
def drain():
    return run_jobs
