# Implementation status

Legend: **[T]** implemented and tested · **[I]** implemented, not tested · **[P]** partial · **[N]** not implemented · **[B]** blocked

"Tested" means automated tests in this repo (fixture/mocked; see TESTING.md). Live YouTube and real Ollama
models could not be exercised in the development sandbox (YouTube is blocked there; Ollama not installed).

## Channels & discovery
- [T] Channel URL parsing/normalisation for @handle, /channel/ID, /c/, /user/, tab suffixes
- [T] Channel resolution to stable channel ID (fake yt-dlp client) · [B] live verification
- [T] /videos + /shorts discovery, dedupe by video ID, Shorts from listing context
- [T] Incremental rescans (stop after known uploads), "only since date" scans
- [T] Add (single + bulk), remove (soft/purge), restore, pause/resume, retry failed, priority, process pending
- [T] Private/unavailable videos handled as permanent, not retried
- [I] Age/region/members-only/bot-check error mapping (pattern-based on yt-dlp messages)

## Transcripts
- [T] Track priority: manual → original auto captions → Whisper; never auto-translations
- [T] VTT / SRT / json3 parsing; entities, tags, invalid timestamps, rolling captions, repeated speech kept
- [T] Immutable source transcripts, original caption file stored, completeness labels
- [T] Whisper fallback pipeline (download → transcribe → store → cleanup) with mocked engine
- [I] Real faster-whisper transcription (code path present; not executed against real audio)
- [T] transcript.txt / transcript_timestamped.json / transcript.vtt / transcript_metadata.json
- [N] AI-corrected derived transcript generation (schema + reader version selector exist; no job creates them)

## AI
- [T] Ollama client: structured `format` schema, offline → deferred, model-missing error (mock transport)
- [T] Token-aware chunking with segment IDs; JSON repair; schema validation with self-correcting retries
- [T] Source validation (invalid refs dropped, excerpts verified/replaced, timestamps from segments)
- [T] Cross-chunk dedupe with optional LLM confirmation; topic normalisation; summary/relationships
- [T] Per-chunk checkpoints and resume
- [T] Editable versioned prompts with reset
- [B] Quality of extraction with a real local model (needs Ollama; prompts untuned)

## Jobs / reliability
- [T] Persistent queue, atomic claim, active-dedupe index, priorities, lanes
- [T] Backoff for transient errors, permanent failure, deferral, crash recovery, pause/cancel running jobs
- [T] Single worker instance lock (Linux); [I] Windows `msvcrt` lock path
- [T] Worker process smoke test (real process, real yt-dlp → network blocked → retry scheduled)
- [I] Heartbeat-based stale-job recovery, DB-locked retry wrapper, disk-full/permission error mapping

## Search, ideas, reports
- [T] FTS5 over videos, segments, ideas, channels with triggers; filters; safe query syntax
- [T] Idea explorer API: filters, relevance sort, bookmarks, tags, notes; annotations survive re-analysis
- [T] Channel report (deterministic aggregates + citation-checked narrative)
- [T] Cross-channel comparison (shared/unique topics, validated pair relations)
- [I] Export of hand-picked ideas (JSON/CSV/MD endpoint)

## Exports
- [T] JSON, CSV, ZIP (with validation), SQLite backup through the API
- [I] TXT, Markdown, JSONL formats (same code path, not individually asserted)
- [T] Per-video archive files written on completion; channel aggregates in ZIP exports

## Frontend
- [T] Component tests: channels list/add, video filters, transcript reader, idea search, job rows,
  settings validation, export selection, error handling (13 tests)
- [I] All pages render real backend data (verified by screenshots against a fixture-populated DB:
  dashboard, channels, channel, videos, video, transcript, ideas, search, queue, reports, exports, settings)
- [T] TypeScript strict typecheck and production build

## Windows
- [I] setup.ps1, start.ps1 — written and reviewed but **not executed** (no PowerShell/Windows in sandbox)
