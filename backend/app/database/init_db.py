"""Database initialisation: run Alembic migrations to head."""
from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.core.config import get_env
from app.database.session import init_engine

log = logging.getLogger(__name__)
BACKEND_DIR = Path(__file__).resolve().parents[2]


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def init_db(url: str | None = None) -> None:
    url = url or get_env().database_url
    command.upgrade(alembic_config(url), "head")
    init_engine(url)
    from app.core.settings_store import ensure_defaults
    from app.services.ai.prompts import ensure_default_prompts
    from app.database.session import session_scope

    with session_scope() as s:
        ensure_defaults(s)
        ensure_default_prompts(s)
    log.info("database ready at %s", url)


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.INFO)
    init_db()
    print(f"Database initialised: {get_env().db_path}")
