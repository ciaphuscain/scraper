"""Static, process-level configuration (paths, ports).

Runtime-tunable options (concurrency, models, prompts...) live in the database
and are managed by :mod:`app.core.settings_store`. Only values that must be known
before the database is opened are configured here, via environment variables.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class Environment(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="YTCS_", env_file=str(REPO_ROOT / ".env"), extra="ignore")

    # Root of the archive. The SQLite database lives inside it by default.
    archive_dir: Path = Field(default=REPO_ROOT / "data" / "YouTube_Content_Archive")
    database_path: Path | None = None
    work_dir: Path | None = None  # temporary audio downloads
    log_dir: Path = Field(default=REPO_ROOT / "logs")
    host: str = "127.0.0.1"
    port: int = 8765
    log_level: str = "INFO"

    @property
    def db_path(self) -> Path:
        return self.database_path or (self.archive_dir / "database.sqlite")

    @property
    def tmp_dir(self) -> Path:
        return self.work_dir or (self.archive_dir / "_work")

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"

    def ensure_dirs(self) -> None:
        for p in (self.archive_dir, self.tmp_dir, self.log_dir, self.db_path.parent):
            p.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_env() -> Environment:
    env = Environment()
    env.ensure_dirs()
    return env


def reset_env_cache() -> None:
    get_env.cache_clear()


def is_windows() -> bool:
    return os.name == "nt"
