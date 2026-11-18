"""Environment/configuration check: ``python -m app.core.doctor``.

Exit code 0 when all *required* checks pass. Optional components (Ollama)
produce warnings only.
"""
from __future__ import annotations

import shutil
import sys
import tempfile


def main() -> int:
    ok = True
    print("YouTube Content Intelligence Studio - configuration check\n")

    def line(status: str, name: str, detail: str = "") -> None:
        print(f"  [{status:^5}] {name}{(' - ' + detail) if detail else ''}")

    v = sys.version_info
    if (v.major, v.minor) >= (3, 12):
        line("OK", "Python", sys.version.split()[0])
    else:
        ok = False
        line("FAIL", "Python", f"{sys.version.split()[0]} (3.12 or 3.13 required)")
    for mod in ("fastapi", "sqlalchemy", "alembic", "yt_dlp", "httpx", "pydantic_settings"):
        try:
            __import__(mod)
            line("OK", mod)
        except ImportError:
            ok = False
            line("FAIL", mod, "not installed (run setup.ps1)")
    try:
        import faster_whisper  # noqa: F401

        line("OK", "faster-whisper")
    except ImportError:
        line("WARN", "faster-whisper", "missing: local transcription fallback disabled")
    if shutil.which("ffmpeg"):
        line("OK", "FFmpeg", shutil.which("ffmpeg") or "")
    else:
        line("WARN", "FFmpeg", "not on PATH. Captions still work; install FFmpeg for robust audio handling "
                               "(e.g. 'winget install Gyan.FFmpeg', then reopen the terminal)")

    from app.core.config import get_env

    env = get_env()
    try:
        with tempfile.NamedTemporaryFile(dir=env.archive_dir, delete=True):
            pass
        line("OK", "Archive folder writable", str(env.archive_dir))
    except OSError as exc:
        ok = False
        line("FAIL", "Archive folder", f"{env.archive_dir}: {exc}")
    free = shutil.disk_usage(env.archive_dir).free / 1e9
    line("OK" if free > 5 else "WARN", "Free disk space", f"{free:.1f} GB")

    try:
        from app.database.init_db import init_db
        from app.database.session import session_scope
        from app.core.settings_store import load_settings

        init_db()
        with session_scope() as s:
            settings = load_settings(s)
        line("OK", "Database", str(env.db_path))
    except Exception as exc:  # noqa: BLE001
        ok = False
        line("FAIL", "Database", str(exc))
        settings = None
    if settings is not None:
        from app.services.ai.ollama import OllamaClient

        client = OllamaClient(settings.ollama_url)
        ver = client.version()
        if ver:
            names = [m.get("name") for m in client.list_models()]
            has = settings.ollama_model in names or f"{settings.ollama_model}:latest" in names
            line("OK" if has else "WARN", "Ollama", f"v{ver} at {settings.ollama_url}; model '{settings.ollama_model}' "
                 + ("installed" if has else f"NOT installed (run: ollama pull {settings.ollama_model})"))
        else:
            line("WARN", "Ollama", f"not reachable at {settings.ollama_url} (optional: transcripts still collected; "
                                   "idea extraction waits until Ollama runs)")
    print("\nResult:", "ready" if ok else "problems found (see FAIL lines)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
