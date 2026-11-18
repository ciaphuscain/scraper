# YouTube Content Intelligence Studio

A local-first Windows application for collecting the **spoken and written content** of YouTube channels
(metadata, captions, local speech-to-text) and turning it into a searchable, source-linked library of ideas
using a **local** LLM via Ollama. No cloud services, paid APIs, Docker or hosted databases.

> **What this captures.** Transcripts contain only the speech that was successfully captured from captions or
> local speech recognition. Visual-only information, inaudible speech and inaccessible media are not recovered,
> and nothing is invented to fill gaps. Each transcript is labelled `complete`, `partial` or `unknown`.
> Ideas are tied to real transcript segments; creator statements are labelled as claims, not facts.

## Features

- Add any number of channels (`@handle`, `/channel/UC…`, `/c/name`, `/user/name`, with or without `/videos`
  or `/shorts`). Bulk add, pause/resume, priority, retry, remove, "only uploads since" date.
- Discovery of `/videos` and `/shorts` with yt-dlp; deduplicated by video ID; Shorts classified by listing
  context (not duration). Incremental rescans only process new uploads.
- Transcript priority: creator captions → original-language auto captions (never auto-translations) →
  local Whisper (faster-whisper) on temporarily downloaded audio. Robust VTT/SRT/json3 parsing with rolling
  auto-caption cleanup that preserves genuinely repeated speech.
- Source transcripts are immutable; original caption files are kept.
- Hierarchical idea extraction (token-aware chunking → per-chunk structured extraction → validation →
  cross-chunk dedupe → topic normalisation → video summary & relationships). No fixed idea limit.
  Hallucinated sources are dropped, excerpts are verified against the transcript, timestamps come from
  segments only. Checkpointed per chunk so interrupted analyses resume.
- Idea explorer with full-text search, filters, bookmarks, tags and personal notes (stored separately,
  re-linked after re-analysis), export of selected ideas.
- SQLite FTS5 search across titles, descriptions, transcript segments, ideas and channels.
- Channel reports (topics, recurring themes, concepts, examples, unique ideas, videos vs Shorts, emphasis
  over time, idea index) and cross-channel comparisons, all linking to video timestamps. LLM-written
  statements without valid citations are discarded; lexical matches are labelled "unvalidated" unless
  Ollama confirms the meaning.
- Persistent SQLite job queue with separate lanes (network / CPU / LLM / general), bounded exponential
  backoff, deferral while Ollama is offline, pause/resume/cancel/priority, crash recovery.
- Exports: TXT, Markdown, JSON, JSONL, CSV, ZIP (archive folder layout) and SQLite backup, for one video,
  selected videos, channels or everything.

## Requirements

| Component | Required | Notes |
|---|---|---|
| Windows 10/11 | yes | Developed and tested on Linux; see TESTING.md for what was verified |
| Python 3.12 or 3.13 | yes | python.org installer, "Add to PATH" |
| Node.js 18+ | yes (for the UI) | LTS from nodejs.org |
| FFmpeg | recommended | `winget install Gyan.FFmpeg` |
| Ollama | optional | Needed only for idea extraction/reports. `ollama pull qwen2.5:7b` |

Recommended models for 16 GB RAM, CPU only: Whisper `small` (int8) or `base` for speed; Ollama
`qwen2.5:7b` or `llama3.1:8b` (Q4). Smaller: `qwen2.5:3b` / `llama3.2:3b` (faster, less thorough).
The first Whisper use downloads the model from huggingface.co.

## Quick start (Windows PowerShell)

```powershell
Set-ExecutionPolicy -Scope Process Bypass   # allow local scripts for this session
.\setup.ps1
.\start.ps1          # dev UI on http://localhost:5173, API on http://127.0.0.1:8765
.\start.ps1 -Prod    # build the UI once and serve everything from http://127.0.0.1:8765
```

`start.ps1` launches the API, one processing worker (a second worker for the same archive refuses to start)
and the UI, opens the browser, and stops everything on Ctrl+C.

## Manual start (any OS)

```bash
python -m venv .venv && .venv/bin/pip install -r backend/requirements-dev.txt
cd backend
../.venv/bin/python -m app.database.init_db
../.venv/bin/uvicorn app.main:app --port 8765 &
../.venv/bin/python -m app.workers.runner &
cd ../frontend && npm install && npm run dev
```

## Data locations

Default archive root: `data/YouTube_Content_Archive/` (override with env `YTCS_ARCHIVE_DIR`).

```
YouTube_Content_Archive/
  database.sqlite
  channels/<CHANNEL_ID>/
    channel_info.json  all_video_transcripts.txt  all_shorts_transcripts.txt
    all_ideas.json  ideas_catalog.csv  channel_summary.md
    videos/<VIDEO_ID>/  metadata.json transcript.txt transcript_timestamped.json
                        transcript.vtt transcript_metadata.json ideas.json summary.md
    shorts/<VIDEO_ID>/  (same files)
  exports/
  _work/               temporary audio (deleted after transcription unless retained)
```

Per-video files are written as work completes; channel-level aggregate files are (re)written by channel
exports (ZIP) and report generation. The **Output directory** setting changes where files and exports are
written; the database location is controlled by `YTCS_ARCHIVE_DIR` / `YTCS_DATABASE_PATH`.

## Architecture

```
backend/app
  api/          FastAPI routers (channels, videos, ideas, search, jobs, reports, exports, settings/system)
  core/         config (env), runtime settings (DB-backed, validated), errors, logging, doctor
  database/     engine/session (WAL, FKs, busy timeout), FTS5 definitions, migrations runner
  models/       SQLAlchemy models
  jobs/         queue (atomic claim, dedupe index, backoff, recovery), handlers, executor, pipeline helpers
  workers/      worker process: lane threads, heavy-job lock, heartbeat, single-instance lock
  services/
    youtube/        URL parsing, yt-dlp client (rate limited), discovery
    transcripts/    caption parsing, track selection, transcript storage
    transcription/  faster-whisper engine
    ai/             Ollama client, schemas, prompts, chunking, validation, dedupe, extraction pipeline
    analysis/       channel report, cross-channel comparison
    search/         FTS5 queries
    exports/        archive writer, exporter
frontend/src    React + TS + Vite + Tailwind; shadcn-style components; TanStack Query; Zustand; React Router
```

API docs are available at `http://127.0.0.1:8765/docs` while the backend runs.

See **PLAN.md**, **TASKS.md** (implementation status), **DECISIONS.md** and **TESTING.md**.
