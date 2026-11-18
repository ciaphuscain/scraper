"""Model -> JSON dict conversion for API responses."""
from __future__ import annotations

from typing import Any

from app.models import Channel, Idea, IdeaAnnotation, Job, Transcript, Video
from app.services.youtube.urls import watch_url


def channel_out(c: Channel, stats: dict[str, Any] | None = None) -> dict[str, Any]:
    d = {
        "id": c.id, "name": c.name, "handle": c.handle, "url": c.url, "description": c.description,
        "thumbnail_url": c.thumbnail_url, "subscriber_count": c.subscriber_count, "active": c.active,
        "paused": c.paused, "priority": c.priority, "scan_since": c.scan_since, "auto_process": c.auto_process,
        "last_scan_at": c.last_scan_at, "last_sync_at": c.last_sync_at, "last_scan_error": c.last_scan_error,
        "created_at": c.created_at,
    }
    d.update(stats or {})
    return d


def video_out(v: Video, channel_name: str | None = None) -> dict[str, Any]:
    return {
        "id": v.id, "channel_id": v.channel_id, "channel_name": channel_name, "title": v.title, "url": v.url,
        "upload_date": v.upload_date, "upload_date_approximate": v.upload_date_approximate, "duration": v.duration,
        "thumbnail_url": v.thumbnail_url, "video_type": v.video_type, "type_source": v.type_source,
        "language": v.language, "has_manual_subs": v.has_manual_subs, "has_auto_subs": v.has_auto_subs,
        "availability": v.availability, "selected": v.selected, "transcript_status": v.transcript_status,
        "analysis_status": v.analysis_status, "idea_count": v.idea_count, "last_error": v.last_error,
        "discovered_at": v.discovered_at, "view_count": v.view_count,
    }


def transcript_out(t: Transcript, include_segments: bool = False) -> dict[str, Any]:
    d = {
        "id": t.id, "video_id": t.video_id, "kind": t.kind, "parent_id": t.parent_id, "method": t.method,
        "language": t.language, "is_current": t.is_current, "completeness": t.completeness,
        "coverage_ratio": t.coverage_ratio, "confidence": t.confidence, "word_count": t.word_count,
        "segment_count": t.segment_count, "details": t.details, "created_at": t.created_at,
        "has_raw_caption": bool(t.raw_caption),
    }
    if include_segments:
        d["segments"] = [{"id": s.seg_key, "start": s.start, "end": s.end, "text": s.text,
                          "confidence": s.confidence, "url": watch_url(t.video_id, s.start)} for s in t.segments]
    return d


def annotation_out(a: IdeaAnnotation | None) -> dict[str, Any] | None:
    if a is None:
        return None
    return {"id": a.id, "note": a.note, "tags": a.tags or [], "bookmarked": a.bookmarked, "updated_at": a.updated_at}


def idea_out(i: Idea, *, video_title: str | None = None, channel_name: str | None = None,
             annotation: IdeaAnnotation | None = None) -> dict[str, Any]:
    return {
        "id": i.id, "video_id": i.video_id, "video_title": video_title, "channel_id": i.channel_id,
        "channel_name": channel_name, "ordinal": i.ordinal, "title": i.title, "explanation": i.explanation,
        "idea_type": i.idea_type, "topic": i.topic, "keywords": i.keywords, "segment_ids": i.segment_keys,
        "start_time": i.start_time, "end_time": i.end_time, "excerpts": i.excerpts,
        "statement_kind": i.statement_kind, "confidence": i.confidence, "uncertainty": i.uncertainty,
        "model": i.model, "analysis_version": i.analysis_version, "video_type": i.video_type,
        "upload_date": i.upload_date, "created_at": i.created_at,
        "url": watch_url(i.video_id, i.start_time), "annotation": annotation_out(annotation),
    }


def job_out(j: Job, *, video_title: str | None = None, channel_name: str | None = None) -> dict[str, Any]:
    return {
        "id": j.id, "job_type": j.job_type, "lane": j.lane, "channel_id": j.channel_id, "video_id": j.video_id,
        "video_title": video_title, "channel_name": channel_name, "priority": j.priority, "status": j.status,
        "stage": j.stage, "progress": j.progress, "attempts": j.attempts, "max_attempts": j.max_attempts,
        "run_after": j.run_after, "error_kind": j.error_kind, "error_message": j.error_message,
        "created_at": j.created_at, "started_at": j.started_at, "finished_at": j.finished_at,
        "heartbeat_at": j.heartbeat_at, "requested_action": j.requested_action, "result": j.result,
        "payload": j.payload,
    }
