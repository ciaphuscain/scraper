# Plan

Phases from the brief and their current state (details in TASKS.md).

| Phase | Scope | State |
|---|---|---|
| 1 Foundation | repo layout, FastAPI app, models, Alembic migration, config, scripts | Done |
| 2 Channel discovery | URL normalisation, channel resolution, /videos + /shorts discovery, dedupe, incremental scans | Done (fixture-tested; live YouTube not reachable from dev sandbox) |
| 3 Transcripts | track selection, VTT/SRT/json3 parsing, rolling-caption cleanup, Whisper fallback, audio cleanup | Done (Whisper path tested with a mock engine) |
| 4 AI analysis | Ollama client, structured output, chunking, validation, dedupe, summaries, prompt versioning | Done (tested with a deterministic fake LLM; no real model run) |
| 5 Jobs | persistent queue, lanes, worker, pause/resume/cancel, retries, recovery, logs | Done |
| 6 Frontend | dashboard, channels, videos, video details, transcript reader, idea explorer, queue, settings | Done |
| 7 Search & reports | FTS5, channel reports, cross-channel comparison, notes/bookmarks/tags | Done |
| 8 Export | TXT/MD/JSON/JSONL/CSV/ZIP/SQLite, all scopes | Done |
| 9 Integration | backend + frontend test suites, e2e fixture workflow, UI smoke screenshots | Done on Linux; Windows scripts not executed (see TESTING.md) |

## Next steps (suggested)

1. Run `setup.ps1` / `start.ps1` on a Windows machine and fix any environment issues.
2. Run the optional live tests (`pytest -m live`, see TESTING.md) against a small real channel.
3. Run a real Ollama model over a few transcripts and tune the default prompt/chunk size.
4. Optional features not built: AI-corrected derived transcripts (data model and reader support exist),
   embeddings-based semantic similarity, an independent fact-verification workflow.
