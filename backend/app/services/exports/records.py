"""Serialisation of database records into portable dictionaries / documents."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Channel, Idea, Transcript, Video, VideoAnalysis
from app.services.transcripts.store import current_transcript
from app.services.youtube.urls import watch_url
from app.utils.time import fmt_ts, utcnow


def video_metadata(video: Video, channel: Channel | None) -> dict[str, Any]:
    return {
        "video_id": video.id,
        "title": video.title,
        "url": video.url,
        "source_url": watch_url(video.id),
        "channel_id": video.channel_id,
        "channel_name": channel.name if channel else None,
        "channel_url": channel.url if channel else None,
        "upload_date": video.upload_date,
        "upload_date_approximate": video.upload_date_approximate,
        "duration_seconds": video.duration,
        "video_type": video.video_type,
        "type_source": video.type_source,
        "language": video.language,
        "description": video.description,
        "thumbnail_url": video.thumbnail_url,
        "tags": video.tags,
        "view_count": video.view_count,
        "has_manual_subtitles": video.has_manual_subs,
        "has_auto_captions": video.has_auto_subs,
        "availability": video.availability,
        "transcript_status": video.transcript_status,
        "analysis_status": video.analysis_status,
        "discovered_at": video.discovered_at,
        "attribution": f"Content by {channel.name if channel else 'unknown channel'} — {watch_url(video.id)}",
    }


def transcript_payload(video: Video, t: Transcript) -> dict[str, Any]:
    return {
        "video_id": video.id,
        "source_url": watch_url(video.id),
        "transcript_id": t.id,
        "method": t.method,
        "language": t.language,
        "kind": t.kind,
        "completeness": t.completeness,
        "coverage_ratio": t.coverage_ratio,
        "segments": [
            {"id": s.seg_key, "start": s.start, "end": s.end, "text": s.text, "confidence": s.confidence,
             "url": watch_url(video.id, s.start)}
            for s in t.segments
        ],
    }


def transcript_metadata(video: Video, t: Transcript) -> dict[str, Any]:
    return {
        "video_id": video.id,
        "source_url": watch_url(video.id),
        "title": video.title,
        "transcript_id": t.id,
        "method": t.method,
        "language": t.language,
        "completeness": t.completeness,
        "coverage_ratio": t.coverage_ratio,
        "confidence": t.confidence,
        "word_count": t.word_count,
        "segment_count": t.segment_count,
        "created_at": t.created_at,
        "details": t.details,
        "note": ("This transcript contains only the spoken content that was successfully captured "
                 "(captions or speech recognition). It does not describe visual content and may omit "
                 "inaudible or untranscribed speech."),
        "generated_at": utcnow(),
    }


def idea_dict(idea: Idea, video: Video | None = None, channel_name: str | None = None) -> dict[str, Any]:
    return {
        "id": idea.id,
        "title": idea.title,
        "explanation": idea.explanation,
        "idea_type": idea.idea_type,
        "topic": idea.topic,
        "keywords": idea.keywords,
        "statement_kind": idea.statement_kind,
        "confidence": idea.confidence,
        "video_id": idea.video_id,
        "video_title": video.title if video else None,
        "channel_id": idea.channel_id,
        "channel_name": channel_name,
        "segment_ids": idea.segment_keys,
        "start_time": idea.start_time,
        "end_time": idea.end_time,
        "timestamp_url": watch_url(idea.video_id, idea.start_time) if idea.start_time is not None else watch_url(idea.video_id),
        "excerpts": idea.excerpts,
        "model": idea.model,
        "analysis_version": idea.analysis_version,
        "created_at": idea.created_at,
    }


def current_analysis(session: Session, video_id: str) -> VideoAnalysis | None:
    return session.execute(
        select(VideoAnalysis).where(VideoAnalysis.video_id == video_id, VideoAnalysis.is_current.is_(True))
        .order_by(VideoAnalysis.id.desc())
    ).scalars().first()


def video_ideas(session: Session, video_id: str) -> list[Idea]:
    return list(session.execute(select(Idea).where(Idea.video_id == video_id).order_by(Idea.ordinal)).scalars())


def summary_markdown(video: Video, channel: Channel | None, analysis: VideoAnalysis | None, ideas: list[Idea]) -> str:
    lines = [f"# {video.title}", "", f"- Channel: {channel.name if channel else 'unknown'}",
             f"- Source: {watch_url(video.id)}", f"- Upload date: {video.upload_date or 'unknown'}",
             f"- Type: {video.video_type}", ""]
    if analysis:
        lines += [f"_Analysis by `{analysis.model}` (version {analysis.analysis_version}, "
                  f"prompts {analysis.prompt_versions})_", ""]
        if analysis.main_theme:
            lines += ["## Main theme", "", analysis.main_theme, ""]
        if analysis.central_thesis:
            lines += ["## Central thesis", "", analysis.central_thesis, ""]
        if analysis.summary:
            lines += ["## Summary", "", analysis.summary, ""]
        if analysis.takeaways:
            lines += ["## Practical takeaways", ""] + [f"- {t}" for t in analysis.takeaways] + [""]
        if analysis.topics:
            lines += ["## Topics", "", ", ".join(analysis.topics), ""]
    else:
        lines += ["_No AI analysis available yet._", ""]
    if ideas:
        lines += [f"## Ideas ({len(ideas)})", ""]
        for i in ideas:
            ts = fmt_ts(i.start_time) if i.start_time is not None else "?"
            link = watch_url(i.video_id, i.start_time)
            lines += [f"### {i.ordinal}. {i.title}", "",
                      f"*{i.idea_type.replace('_', ' ')} · {i.topic} · {i.statement_kind.replace('_', ' ')} · "
                      f"[{ts}]({link})*", "", i.explanation, ""]
            for ex in i.excerpts[:3]:
                lines.append(f"> {ex.get('text', '')}")
            lines.append("")
    return "\n".join(lines)


def transcript_txt(t: Transcript) -> str:
    return t.full_text + ("\n" if t.full_text and not t.full_text.endswith("\n") else "")
