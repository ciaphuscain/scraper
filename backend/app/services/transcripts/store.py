"""Persist transcripts (immutable source versions) and compute completeness."""
from __future__ import annotations

from typing import Any

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import Transcript, TranscriptSegment, Video
from app.services.transcripts.captions import Segment


def seg_key(idx: int) -> str:
    return f"S{idx:05d}"


def assess_completeness(segments: list[Segment], duration: float | None, method: str,
                        whisper_finished: bool | None = None) -> tuple[str, float | None]:
    if not segments:
        return "partial", 0.0
    last_end = max(s.end for s in segments)
    if not duration or duration <= 0:
        return ("complete" if whisper_finished else "unknown"), None
    coverage = min(1.0, last_end / duration)
    if method == "whisper":
        # Whisper covered the whole decoded file; VAD may skip silence at the end.
        return ("complete" if whisper_finished else "partial"), coverage
    if coverage >= 0.85 or (duration - last_end) <= 30:
        return "complete", coverage
    return "partial", coverage


def save_source_transcript(
    session: Session,
    video: Video,
    segments: list[Segment],
    *,
    method: str,
    language: str | None,
    raw_caption: str | None = None,
    raw_format: str | None = None,
    details: dict[str, Any] | None = None,
    whisper_finished: bool | None = None,
) -> Transcript:
    """Store a new source transcript and mark it current. Older versions are kept."""
    segments = [s for s in segments if s.text.strip()]
    completeness, coverage = assess_completeness(segments, video.duration, method, whisper_finished)
    full_text = "\n".join(s.text for s in segments)
    confs = [s.confidence for s in segments if s.confidence is not None]
    session.execute(
        update(Transcript).where(Transcript.video_id == video.id, Transcript.kind == "source").values(is_current=False)
    )
    t = Transcript(
        video_id=video.id,
        kind="source",
        method=method,
        language=language,
        is_current=True,
        completeness=completeness,
        coverage_ratio=coverage,
        confidence=(sum(confs) / len(confs)) if confs else None,
        word_count=len(full_text.split()),
        segment_count=len(segments),
        full_text=full_text,
        raw_caption=raw_caption,
        raw_format=raw_format,
        details=details or {},
    )
    session.add(t)
    session.flush()
    session.add_all(
        TranscriptSegment(
            transcript_id=t.id, video_id=video.id, idx=i, seg_key=seg_key(i),
            start=round(s.start, 3), end=round(max(s.end, s.start), 3), text=s.text, confidence=s.confidence,
        )
        for i, s in enumerate(segments)
    )
    video.transcript_status = "completed"
    video.language = video.language or language
    video.last_error = None
    session.flush()
    return t


def current_transcript(session: Session, video_id: str, kind: str = "source") -> Transcript | None:
    from sqlalchemy import select

    return session.execute(
        select(Transcript)
        .where(Transcript.video_id == video_id, Transcript.kind == kind, Transcript.is_current.is_(True))
        .order_by(Transcript.id.desc())
    ).scalars().first()
