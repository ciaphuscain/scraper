# Testing

## Running

```bash
# backend (from backend/)
../.venv/bin/python -m pytest -q          # Windows: ..\.venv\Scripts\python.exe -m pytest -q
# frontend (from frontend/)
npx tsc -b && npx vitest run
# both
scripts/run_tests.sh      # or scripts\run_tests.ps1
```

## Results at last run (Linux, Python 3.13, Node 22)

- Backend: **58 passed** (`pytest -q`), 2 live tests deselected by default.
- Frontend: **13 passed** (`vitest run`); `tsc -b` clean; `vite build` succeeds.

## What the suites cover

Backend (`backend/tests`, deterministic, no network):
- `test_urls.py` URL parsing/normalisation, timestamp links
- `test_captions.py` VTT/SRT/json3, invalid timestamps, entities, rolling captions, repeated speech,
  track selection priority, no auto-translations, completeness
- `test_discovery.py` resolution, cross-tab dedupe, Shorts classification, since-date and incremental scans
- `test_queue.py` idempotent enqueue, priority claim, paused channels, backoff vs permanent, deferral,
  recovery with checkpoints, cancel/pause running jobs, retry-failed policy
- `test_ai.py` chunking, JSON repair, schema normalisation, source validation, dedupe, full extractor with
  checkpoint resume, invalid-LLM retries, Ollama client offline/structured output (mock transport)
- `test_e2e.py` the brief's end-to-end workflow through the HTTP API with fake YouTube/Whisper/LLM:
  add channel → discover → captions and Whisper fallback → timestamped transcript → idea extraction →
  search → open supporting segment → annotations survive re-analysis → archive files → JSON/ZIP/CSV/SQLite
  exports → channel report → **restart** and verify data intact. Also: incremental rescan processes only
  new uploads; Ollama offline keeps transcripts and defers analysis; pause/resume and crash recovery;
  settings validation; prompt versioning; cross-channel comparison; single video + batch actions.

Frontend (`frontend/src/test`): see TASKS.md.

## Manual verification performed
- Real worker + API processes started together; second worker refused (lock); adding a real channel
  ran yt-dlp, which was blocked by the sandbox network and correctly became `retry_scheduled` (transient).
- UI screenshots of every page against a database populated through the real pipeline with fakes.
- `python -m app.core.doctor` configuration check.

## Not verified (environment limits)
- **Live YouTube** (blocked in the dev sandbox). Run the opt-in tests on your machine:
  `YTCS_LIVE_CHANNEL=https://www.youtube.com/@SomeChannel pytest -m live`
- **Real Ollama models** (not installed in sandbox): `YTCS_LIVE_OLLAMA=1 pytest -m live`
- **Real faster-whisper transcription** of audio (model download + CPU run not performed).
- **Windows**: `setup.ps1` / `start.ps1` and the Windows file-lock path were not executed.
