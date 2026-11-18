"""Job handlers. Each handler is idempotent and resumable via checkpoints."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import select

from app.core.config import get_env
from app.core.errors import DeferredError, PermanentError, StudioError, VideoUnavailableError
from app.database.session import session_scope
from app.jobs.context import JobContext
from app.jobs.pipeline import queue_analysis, queue_transcript
from app.jobs.queue import enqueue
from app.models import Channel, ExportRecord, Job, Video
from app.services.ai import prompts as P
from app.services.ai.extraction import ExtractionInput, IdeaExtractor, load_segments, persist_analysis
from app.services.ai.llm import OllamaStructuredLLM
from app.services.ai.ollama import client_from_settings
from app.services.exports.archive import write_channel_files, write_video_files
from app.services.transcripts.captions import parse_captions
from app.services.transcripts.selection import choose_track
from app.services.transcripts.store import current_transcript, save_source_transcript
from app.services.youtube import discovery
from app.services.youtube.client import get_client
from app.utils.time import utcnow

log = logging.getLogger(__name__)


def _write_files(ctx: JobContext, video_id: str) -> None:
    if not ctx.settings.write_files_on_completion:
        return
    try:
        with session_scope() as s:
            v = s.get(Video, video_id)
            if v:
                write_video_files(s, ctx.settings.archive_root, v)
    except OSError as exc:  # file output must never discard DB work
        log.error("could not write archive files for %s: %s", video_id, exc)
        ctx.log(f"warning: archive files not written: {exc}", "warning")


# ------------------------------------------------------------------ discovery

def discover_channel(ctx: JobContext) -> dict[str, Any]:
    client = get_client(ctx.settings.request_delay_seconds)
    ctx.stage("discovering", 0.02)
    with session_scope() as s:
        if ctx.channel_id:
            channel = s.get(Channel, ctx.channel_id)
            if channel is None:
                raise PermanentError("channel was removed")
        else:
            url = ctx.payload.get("input_url")
            if not url:
                raise PermanentError("no channel URL")
            channel = discovery.resolve_channel(s, client, url)
            cs = ctx.payload.get("channel_settings") or {}
            if cs.get("scan_since"):
                channel.scan_since = cs["scan_since"]
            if cs.get("priority") is not None:
                channel.priority = int(cs["priority"])
            if cs.get("auto_process") is not None:
                channel.auto_process = bool(cs["auto_process"])
            job = s.get(Job, ctx.job_id)
            if job:
                job.channel_id = channel.id
            ctx.channel_id = channel.id
        channel_id = channel.id
    ctx.stage("fetching_metadata", 0.1)
    since = ctx.payload.get("since")
    with session_scope() as s:
        channel = s.get(Channel, channel_id)
        assert channel is not None
        since = since or channel.scan_since
        incremental = not ctx.payload.get("full")
        channel.last_scan_at = utcnow()
        s.commit()
        try:
            stats = discovery.scan_channel(
                s, client, channel, since=since, incremental=incremental,
                progress=lambda tab, n: ctx.update(stage="discovering", progress=0.1 + (0.4 if tab == "videos" else 0.8) * min(1, n / 2000)),
            )
        except StudioError as exc:
            channel.last_scan_error = exc.user_message
            s.commit()
            raise
        channel.last_sync_at = utcnow()
        channel.last_scan_error = None
        queued = 0
        if ctx.settings.auto_process_new_videos and channel.auto_process and not channel.paused:
            for vid in stats["new_video_ids"]:
                v = s.get(Video, vid)
                if v is not None and v.selected:
                    queue_transcript(s, v)
                    queued += 1
        stats["queued_transcripts"] = queued
        stats["new"] = len(stats.pop("new_video_ids"))
    return stats


# ------------------------------------------------------------------ transcripts

def fetch_transcript(ctx: JobContext) -> dict[str, Any]:
    client = get_client(ctx.settings.request_delay_seconds)
    vid = ctx.video_id
    assert vid
    with session_scope() as s:
        v = s.get(Video, vid)
        if v is None:
            raise PermanentError("video record no longer exists")
        if not ctx.payload.get("force") and current_transcript(s, vid) is not None:
            v.transcript_status = "completed"
            return {"skipped": "transcript already collected"}
        v.transcript_status = "in_progress"
    ctx.stage("fetching_metadata", 0.1)
    try:
        info = client.video_info(vid)
    except VideoUnavailableError as exc:
        with session_scope() as s:
            v = s.get(Video, vid)
            if v:
                v.availability = exc.kind
                v.transcript_status = "unavailable"
                v.last_error = exc.user_message
        raise
    with session_scope() as s:
        v = s.get(Video, vid)
        assert v is not None
        discovery.apply_video_info(v, info)
        if info.get("channel_id") and v.channel_id is None:
            ch = s.get(Channel, info["channel_id"])
            if ch:
                v.channel_id = ch.id
    ctx.stage("downloading_captions", 0.3)
    choice = choose_track(info, ctx.settings.preferred_languages, ctx.settings.allow_auto_captions)
    if choice is not None:
        raw = client.fetch_text(choice.url)
        ctx.stage("normalizing", 0.6)
        try:
            parsed = parse_captions(raw, choice.ext)
        except Exception as exc:  # invalid caption file: fall through to whisper
            parsed = None
            ctx.log(f"caption file could not be parsed ({exc}); falling back", "warning")
        if parsed and parsed.segments:
            with session_scope() as s:
                v = s.get(Video, vid)
                assert v is not None
                t = save_source_transcript(
                    s, v, parsed.segments, method=choice.method, language=choice.language, raw_caption=raw,
                    raw_format=parsed.format,
                    details={"track_name": choice.name, "ext": choice.ext, "rolling_captions_collapsed": parsed.rolling_detected,
                             "skipped_cues": parsed.skipped_cues, "warnings": parsed.warnings},
                )
                tid, n = t.id, t.segment_count
                if ctx.settings.auto_analyze:
                    queue_analysis(s, v)
            _write_files(ctx, vid)
            return {"method": choice.method, "language": choice.language, "segments": n, "transcript_id": tid}
        ctx.log("caption track was empty or unusable", "warning")
    # fallback
    with session_scope() as s:
        v = s.get(Video, vid)
        assert v is not None
        if not ctx.settings.whisper_fallback_enabled:
            v.transcript_status = "unavailable"
            v.last_error = "No usable captions and local transcription is disabled."
            return {"method": None, "note": v.last_error}
        enqueue(s, "download_audio", channel_id=v.channel_id, video_id=vid, priority=None,
                max_attempts=ctx.settings.max_retries)
        v.transcript_status = "queued"
    return {"method": "whisper_queued"}


def download_audio(ctx: JobContext) -> dict[str, Any]:
    client = get_client(ctx.settings.request_delay_seconds)
    vid = ctx.video_id
    assert vid
    existing = ctx.checkpoint.get("audio_path")
    if existing and Path(existing).exists():
        path = Path(existing)
    else:
        ctx.stage("downloading_audio", 0.1)
        try:
            path = client.download_audio(vid, get_env().tmp_dir / vid)
        except VideoUnavailableError as exc:
            with session_scope() as s:
                v = s.get(Video, vid)
                if v:
                    v.transcript_status = "unavailable"
                    v.last_error = exc.user_message
            raise
        ctx.save_checkpoint(audio_path=str(path))
    with session_scope() as s:
        v = s.get(Video, vid)
        enqueue(s, "transcribe_audio", channel_id=v.channel_id if v else None, video_id=vid,
                payload={"audio_path": str(path)}, max_attempts=ctx.settings.max_retries)
    return {"audio_path": str(path), "bytes": path.stat().st_size}


def transcribe_audio(ctx: JobContext) -> dict[str, Any]:
    from app.services.transcription.whisper import get_engine

    vid = ctx.video_id
    assert vid
    path = Path(ctx.payload.get("audio_path") or "")
    if not path.exists():
        with session_scope() as s:
            v = s.get(Video, vid)
            enqueue(s, "download_audio", channel_id=v.channel_id if v else None, video_id=vid)
        return {"requeued_download": True}
    ctx.stage("transcribing", 0.02)
    last = [0.0]

    def prog(p: float) -> None:
        if p - last[0] >= 0.03:
            last[0] = p
            ctx.update(stage="transcribing", progress=0.02 + 0.9 * p)

    try:
        result = get_engine().transcribe(path, ctx.settings, progress=prog)
    except StudioError as exc:
        if not exc.transient and ctx.settings.cleanup_failed_audio:
            path.unlink(missing_ok=True)
        raise
    ctx.stage("normalizing", 0.95)
    with session_scope() as s:
        v = s.get(Video, vid)
        assert v is not None
        if not v.duration and result.duration:
            v.duration = result.duration
        t = save_source_transcript(s, v, result.segments, method="whisper", language=result.language,
                                   details=result.details, whisper_finished=result.finished)
        tid, n = t.id, t.segment_count
        if ctx.settings.auto_analyze and n:
            queue_analysis(s, v)
    if not ctx.settings.retain_audio:
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass
    _write_files(ctx, vid)
    return {"method": "whisper", "language": result.language, "segments": n, "transcript_id": tid}


# ------------------------------------------------------------------ AI

def _llm(ctx: JobContext, *, required: bool = True) -> OllamaStructuredLLM | None:
    client = client_from_settings(ctx.settings)
    if not client.is_available():
        if required:
            raise DeferredError("ollama offline", delay_seconds=300,
                                user_message=f"Ollama is not reachable at {ctx.settings.ollama_url}. "
                                             "Analysis will resume automatically when it is available.")
        return None
    return OllamaStructuredLLM(client, ctx.settings)


def analyze_video(ctx: JobContext) -> dict[str, Any]:
    vid = ctx.video_id
    assert vid
    llm = _llm(ctx)
    with session_scope() as s:
        v = s.get(Video, vid)
        if v is None:
            raise PermanentError("video record no longer exists")
        t = current_transcript(s, vid)
        if t is None:
            raise PermanentError("no transcript", user_message="No transcript is available to analyse yet.")
        segments = load_segments(s, t)
        ch = s.get(Channel, v.channel_id) if v.channel_id else None
        inp = ExtractionInput(video_id=vid, channel_id=v.channel_id, video_title=v.title,
                              channel_name=ch.name if ch else "unknown channel", transcript_id=t.id, segments=segments)
        bodies, versions = {}, {}
        for key in P.DEFAULT_PROMPTS:
            p = P.get_active(s, key)
            bodies[key], versions[key] = p.body, p.version
        v.analysis_status = "in_progress"
    if not segments:
        with session_scope() as s:
            v = s.get(Video, vid)
            if v:
                v.analysis_status = "skipped"
        return {"ideas": 0, "note": "empty transcript"}
    st = ctx.settings
    extractor = IdeaExtractor(llm, bodies, versions, chunk_tokens=st.chunk_tokens, overlap=st.chunk_overlap_segments,
                              semantic_dedupe=st.llm_semantic_dedupe, context_tokens=st.llm_context_size,
                              max_output_tokens=st.llm_max_tokens)
    ctx.stage("extracting_ideas", 0.03)
    out = extractor.run(
        inp,
        checkpoint=ctx.checkpoint,
        on_chunk=lambda i, n, cp: ctx.update(save_checkpoint=True),
        on_stage=lambda name, p: ctx.update(stage=name, progress=p),
    )
    with session_scope() as s:
        v = s.get(Video, vid)
        t = current_transcript(s, vid)
        assert v is not None and t is not None
        a = persist_analysis(s, v, t, out)
        aid = a.id
    _write_files(ctx, vid)
    ctx.checkpoint.clear()
    ctx.update(save_checkpoint=True)
    return {"ideas": len(out.ideas), "chunks": out.chunk_count, "analysis_id": aid, "validation": out.stats.as_dict(),
            "llm_calls": getattr(getattr(llm, "stats", None), "calls", None),
            "invalid_llm_responses": getattr(getattr(llm, "stats", None), "invalid_responses", None)}


def channel_report(ctx: JobContext) -> dict[str, Any]:
    from app.services.analysis.channel_report import generate_channel_report

    use_llm = ctx.payload.get("use_llm", True)
    llm = _llm(ctx, required=False) if use_llm else None
    ctx.stage("analyzing", 0.2)
    with session_scope() as s:
        ch = s.get(Channel, ctx.channel_id)
        if ch is None:
            raise PermanentError("channel not found")
        rep = generate_channel_report(s, ch, llm, ctx.settings.llm_context_size)
        rid = rep.id
        try:
            from app.utils.files import atomic_write_text
            from app.services.exports.archive import channel_dir

            atomic_write_text(channel_dir(ctx.settings.archive_root, ch.id) / "channel_summary.md", rep.markdown)
        except OSError as exc:
            log.warning("could not write channel summary: %s", exc)
    return {"report_id": rid, "llm_used": llm is not None}


def cross_channel_report(ctx: JobContext) -> dict[str, Any]:
    from app.services.analysis.cross_channel import compare_channels

    ids = ctx.payload.get("channel_ids") or []
    llm = _llm(ctx, required=False) if ctx.payload.get("validate", True) else None
    ctx.stage("analyzing", 0.2)
    with session_scope() as s:
        try:
            rep = compare_channels(s, ids, llm, max_pairs=int(ctx.payload.get("max_pairs", 40)))
        except ValueError as exc:
            raise PermanentError(str(exc)) from exc
        return {"report_id": rep.id, "semantic_validation": llm is not None}


def export_job(ctx: JobContext) -> dict[str, Any]:
    from app.services.exports.exporter import export

    rec_id = ctx.payload["export_id"]
    ctx.stage("exporting", 0.1)
    with session_scope() as s:
        rec = s.get(ExportRecord, rec_id)
        if rec is None:
            raise PermanentError("export record missing")
        rec.status = "running"
    try:
        with session_scope() as s:
            rec = s.get(ExportRecord, rec_id)
            assert rec is not None
            res = export(s, scope=rec.scope, ids=rec.target_ids, content=rec.content, fmt=rec.format,
                         out_dir=ctx.settings.archive_root / "exports")
            rec.status, rec.file_path, rec.size_bytes = "completed", res["path"], res["size"]
            rec.item_count, rec.finished_at = res["items"], utcnow()
    except Exception as exc:
        with session_scope() as s:
            rec = s.get(ExportRecord, rec_id)
            if rec:
                rec.status, rec.error = "failed", str(exc)[:1000]
        if isinstance(exc, OSError):
            from app.core.errors import classify_os_error

            raise classify_os_error(exc) from exc
        raise
    return res


HANDLERS: dict[str, Callable[[JobContext], dict[str, Any]]] = {
    "discover_channel": discover_channel,
    "fetch_transcript": fetch_transcript,
    "download_audio": download_audio,
    "transcribe_audio": transcribe_audio,
    "analyze_video": analyze_video,
    "channel_report": channel_report,
    "cross_channel_report": cross_channel_report,
    "export": export_job,
}


def on_final_failure(job: Job, session) -> None:
    """Reflect terminal job failure on the video record (completed work is kept)."""
    if not job.video_id:
        return
    v = session.get(Video, job.video_id)
    if v is None:
        return
    if job.job_type in ("fetch_transcript", "download_audio", "transcribe_audio"):
        if v.transcript_status not in ("completed", "unavailable"):
            v.transcript_status = "failed"
        v.last_error = job.error_message
    elif job.job_type == "analyze_video":
        # Previous ideas are kept; only flag failure when there is no usable analysis.
        v.analysis_status = "failed" if v.idea_count == 0 else "completed"
        v.last_error = job.error_message
