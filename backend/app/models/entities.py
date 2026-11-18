"""ORM models.

Design notes
------------
* YouTube IDs (channel/video) are the primary keys so they are stable across
  re-imports and safe to use as directory names.
* Source transcripts are immutable once stored; AI derived versions are new
  ``Transcript`` rows with ``kind='derived'`` and ``parent_id`` set.
* User annotations live in ``idea_annotations`` so re-analysis never
  overwrites them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.utils.time import utcnow

ACTIVE_JOB_STATUSES = ("queued", "running", "retry_scheduled", "paused")


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # UC...
    name: Mapped[str] = mapped_column(String(512), default="")
    handle: Mapped[str | None] = mapped_column(String(256))
    url: Mapped[str] = mapped_column(String(1024))
    input_url: Mapped[str | None] = mapped_column(String(1024))
    description: Mapped[str | None] = mapped_column(Text)
    thumbnail_url: Mapped[str | None] = mapped_column(String(2048))
    subscriber_count: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    paused: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    priority: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    scan_since: Mapped[str | None] = mapped_column(String(8))  # YYYYMMDD lower bound for discovery
    auto_process: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime)  # last *successful* full sync
    last_scan_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    videos: Mapped[list[Video]] = relationship(back_populates="channel", passive_deletes=True)


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    channel_id: Mapped[str | None] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(1024), default="")
    description: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(1024))
    upload_date: Mapped[str | None] = mapped_column(String(8), index=True)  # YYYYMMDD
    upload_date_approximate: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("0"))
    duration: Mapped[float | None] = mapped_column(Float)
    thumbnail_url: Mapped[str | None] = mapped_column(String(2048))
    video_type: Mapped[str] = mapped_column(String(16), default="video", index=True)  # video | short | live
    type_source: Mapped[str] = mapped_column(String(32), default="listing")  # listing | metadata | url | default
    listing_sources: Mapped[list[str]] = mapped_column(JSON, default=list)
    language: Mapped[str | None] = mapped_column(String(16))
    has_manual_subs: Mapped[bool | None] = mapped_column(Boolean)
    has_auto_subs: Mapped[bool | None] = mapped_column(Boolean)
    subtitle_languages: Mapped[list[str] | None] = mapped_column(JSON)
    view_count: Mapped[int | None] = mapped_column(Integer)
    tags: Mapped[list[str] | None] = mapped_column(JSON)
    availability: Mapped[str] = mapped_column(String(32), default="unknown")  # public|unavailable|private|...
    metadata_fetched_at: Mapped[datetime | None] = mapped_column(DateTime)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    selected: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))

    # pipeline state
    transcript_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    # pending | queued | in_progress | completed | unavailable | failed | skipped
    analysis_status: Mapped[str] = mapped_column(String(32), default="pending", index=True)
    # pending | queued | in_progress | completed | failed | skipped
    last_error: Mapped[str | None] = mapped_column(Text)
    idea_count: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    channel: Mapped[Channel | None] = relationship(back_populates="videos")
    transcripts: Mapped[list[Transcript]] = relationship(back_populates="video", passive_deletes=True)

    __table_args__ = (Index("ix_videos_channel_type_date", "channel_id", "video_type", "upload_date"),)


class Transcript(Base):
    __tablename__ = "transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default="source")  # source | derived
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("transcripts.id", ondelete="CASCADE"))
    method: Mapped[str] = mapped_column(String(32))  # manual_captions | auto_captions | whisper | ai_correction
    language: Mapped[str | None] = mapped_column(String(16))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    completeness: Mapped[str] = mapped_column(String(32), default="unknown")  # complete | partial | unknown
    coverage_ratio: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    segment_count: Mapped[int] = mapped_column(Integer, default=0)
    full_text: Mapped[str] = mapped_column(Text, default="")
    raw_caption: Mapped[str | None] = mapped_column(Text)  # original caption file contents
    raw_format: Mapped[str | None] = mapped_column(String(16))
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # model, notes, warnings
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    video: Mapped[Video] = relationship(back_populates="transcripts")
    segments: Mapped[list[TranscriptSegment]] = relationship(
        back_populates="transcript", order_by="TranscriptSegment.idx", passive_deletes=True
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transcript_id: Mapped[int] = mapped_column(ForeignKey("transcripts.id", ondelete="CASCADE"))
    video_id: Mapped[str] = mapped_column(String(32), index=True)
    idx: Mapped[int] = mapped_column(Integer)
    seg_key: Mapped[str] = mapped_column(String(16))  # stable identifier within a transcript: S00012
    start: Mapped[float] = mapped_column(Float)
    end: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)

    transcript: Mapped[Transcript] = relationship(back_populates="segments")

    __table_args__ = (UniqueConstraint("transcript_id", "idx", name="uq_segment_idx"),)


class VideoAnalysis(Base):
    __tablename__ = "video_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    transcript_id: Mapped[int | None] = mapped_column(ForeignKey("transcripts.id", ondelete="SET NULL"))
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("1"))
    status: Mapped[str] = mapped_column(String(32), default="completed")
    model: Mapped[str] = mapped_column(String(128))
    analysis_version: Mapped[str] = mapped_column(String(32))
    prompt_versions: Mapped[dict[str, int]] = mapped_column(JSON, default=dict)
    main_theme: Mapped[str | None] = mapped_column(Text)
    central_thesis: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    topics: Mapped[list[str]] = mapped_column(JSON, default=list)
    takeaways: Mapped[list[str]] = mapped_column(JSON, default=list)
    relationships: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    validation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    raw_idea_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Idea(Base):
    __tablename__ = "ideas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    channel_id: Mapped[str | None] = mapped_column(String(64), index=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("video_analyses.id", ondelete="CASCADE"), index=True)
    transcript_id: Mapped[int | None] = mapped_column(Integer)
    ordinal: Mapped[int] = mapped_column(Integer, default=0)
    title: Mapped[str] = mapped_column(String(512))
    explanation: Mapped[str] = mapped_column(Text)
    idea_type: Mapped[str] = mapped_column(String(48), index=True)
    topic: Mapped[str | None] = mapped_column(String(256), index=True)
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    keywords_text: Mapped[str] = mapped_column(Text, default="")  # flattened for FTS
    segment_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    start_time: Mapped[float | None] = mapped_column(Float)
    end_time: Mapped[float | None] = mapped_column(Float)
    excerpts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    statement_kind: Mapped[str] = mapped_column(String(32), default="stated")
    # stated | interpretation | creator_claim | verified_fact
    confidence: Mapped[float | None] = mapped_column(Float)
    uncertainty: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(128))
    analysis_version: Mapped[str] = mapped_column(String(32))
    video_type: Mapped[str | None] = mapped_column(String(16))
    upload_date: Mapped[str | None] = mapped_column(String(8))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (Index("ix_ideas_channel_topic", "channel_id", "topic"),)


class IdeaAnnotation(Base):
    """User-owned data. Kept separate from AI output; re-linked on re-analysis."""

    __tablename__ = "idea_annotations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    idea_id: Mapped[int | None] = mapped_column(ForeignKey("ideas.id", ondelete="SET NULL"), unique=True)
    video_id: Mapped[str] = mapped_column(ForeignKey("videos.id", ondelete="CASCADE"), index=True)
    idea_title_snapshot: Mapped[str] = mapped_column(String(512))
    segment_keys_snapshot: Mapped[list[str]] = mapped_column(JSON, default=list)
    note: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    bookmarked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(48), index=True)
    lane: Mapped[str] = mapped_column(String(16), index=True)  # network | cpu | llm | general
    channel_id: Mapped[str | None] = mapped_column(String(64), index=True)
    video_id: Mapped[str | None] = mapped_column(String(32), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(256))
    priority: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    stage: Mapped[str] = mapped_column(String(48), default="queued")
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=4)
    run_after: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    error_kind: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(Text)
    worker_id: Mapped[str | None] = mapped_column(String(64))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime)
    requested_action: Mapped[str | None] = mapped_column(String(16))  # pause | cancel (for running jobs)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        # No duplicate active work for the same video + stage.
        Index(
            "uq_jobs_active_dedupe",
            "dedupe_key",
            unique=True,
            sqlite_where=text("status IN ('queued','running','retry_scheduled','paused')"),
        ),
        Index("ix_jobs_claim", "lane", "status", "priority", "run_after"),
    )


class JobEvent(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    video_id: Mapped[str | None] = mapped_column(String(32), index=True)
    level: Mapped[str] = mapped_column(String(16), default="info")
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    body: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (UniqueConstraint("key", "version", name="uq_prompt_key_version"),)


class ChannelReport(Base):
    __tablename__ = "channel_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_id: Mapped[str] = mapped_column(ForeignKey("channels.id", ondelete="CASCADE"), index=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    narrative: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    markdown: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str | None] = mapped_column(String(128))
    prompt_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CrossChannelReport(Base):
    __tablename__ = "cross_channel_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    channel_ids: Mapped[list[str]] = mapped_column(JSON)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    markdown: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str | None] = mapped_column(String(128))
    semantic_validation: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ExportRecord(Base):
    __tablename__ = "exports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int | None] = mapped_column(Integer)
    scope: Mapped[str] = mapped_column(String(32))
    target_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    content: Mapped[list[str]] = mapped_column(JSON, default=list)
    format: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="pending")
    file_path: Mapped[str | None] = mapped_column(String(2048))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    item_count: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
