"""Maintain the on-disk archive (stable-ID directory layout)."""
from __future__ import annotations

import csv
import io
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Channel, Idea, Video
from app.services.exports import records as R
from app.services.transcripts.captions import segments_to_vtt
from app.services.transcripts.store import current_transcript
from app.utils.files import atomic_write_json, atomic_write_text
from app.utils.time import utcnow

log = logging.getLogger(__name__)


def channel_dir(root: Path, channel_id: str | None) -> Path:
    return root / "channels" / (channel_id or "_unassigned")


def video_dir(root: Path, video: Video) -> Path:
    sub = "shorts" if video.video_type == "short" else "videos"
    return channel_dir(root, video.channel_id) / sub / video.id


def write_video_files(session: Session, root: Path, video: Video) -> Path:
    """(Re)write all files for one video. Safe to call repeatedly."""
    channel = session.get(Channel, video.channel_id) if video.channel_id else None
    d = video_dir(root, video)
    d.mkdir(parents=True, exist_ok=True)
    # remove a stale copy in the other type folder (e.g. reclassified as Short)
    other = d.parent.parent / ("videos" if d.parent.name == "shorts" else "shorts") / video.id
    if other.exists() and other != d:
        import shutil

        shutil.rmtree(other, ignore_errors=True)
    atomic_write_json(d / "metadata.json", R.video_metadata(video, channel))
    t = current_transcript(session, video.id)
    if t is not None:
        atomic_write_text(d / "transcript.txt", R.transcript_txt(t))
        payload = R.transcript_payload(video, t)
        atomic_write_json(d / "transcript_timestamped.json", payload)
        if t.raw_caption and t.raw_format == "vtt":
            atomic_write_text(d / "transcript.vtt", t.raw_caption)
        else:
            atomic_write_text(d / "transcript.vtt", segments_to_vtt(payload["segments"]))
        if t.raw_caption and t.raw_format in ("srt", "json3"):
            atomic_write_text(d / f"original_captions.{t.raw_format}", t.raw_caption)
        atomic_write_json(d / "transcript_metadata.json", R.transcript_metadata(video, t))
    analysis = R.current_analysis(session, video.id)
    ideas = R.video_ideas(session, video.id)
    if analysis is not None:
        atomic_write_json(d / "ideas.json", {
            "video_id": video.id, "source_url": video.url, "model": analysis.model,
            "analysis_version": analysis.analysis_version, "prompt_versions": analysis.prompt_versions,
            "validation": analysis.validation,
            "ideas": [R.idea_dict(i, video, channel.name if channel else None) for i in ideas],
        })
    atomic_write_text(d / "summary.md", R.summary_markdown(video, channel, analysis, ideas))
    return d


IDEA_CSV_FIELDS = ["id", "title", "idea_type", "topic", "statement_kind", "confidence", "keywords", "explanation",
                   "video_id", "video_title", "channel_id", "channel_name", "start_time", "timestamp_url",
                   "segment_ids", "model"]


def ideas_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=IDEA_CSV_FIELDS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        r = dict(r)
        r["keywords"] = "; ".join(r.get("keywords") or [])
        r["segment_ids"] = " ".join(r.get("segment_ids") or [])
        w.writerow(r)
    return buf.getvalue()


def write_channel_files(session: Session, root: Path, channel: Channel, *, include_videos: bool = True) -> Path:
    d = channel_dir(root, channel.id)
    d.mkdir(parents=True, exist_ok=True)
    videos = session.execute(
        select(Video).where(Video.channel_id == channel.id).order_by(Video.upload_date.desc().nulls_last(), Video.id)
    ).scalars().all()
    atomic_write_json(d / "channel_info.json", {
        "channel_id": channel.id, "name": channel.name, "handle": channel.handle, "url": channel.url,
        "description": channel.description, "thumbnail_url": channel.thumbnail_url,
        "video_count": sum(1 for v in videos if v.video_type != "short"),
        "shorts_count": sum(1 for v in videos if v.video_type == "short"),
        "last_scan_at": channel.last_scan_at, "last_sync_at": channel.last_sync_at, "generated_at": utcnow(),
    })
    all_v, all_s = [], []
    idea_rows: list[dict] = []
    for v in videos:
        if include_videos:
            write_video_files(session, root, v)
        t = current_transcript(session, v.id)
        if t is not None:
            block = f"===== {v.title} | {v.upload_date or ''} | {R.watch_url(v.id)} | {t.method} ({t.completeness}) =====\n{R.transcript_txt(t)}\n"
            (all_s if v.video_type == "short" else all_v).append(block)
        for i in session.execute(select(Idea).where(Idea.video_id == v.id).order_by(Idea.ordinal)).scalars():
            idea_rows.append(R.idea_dict(i, v, channel.name))
    atomic_write_text(d / "all_video_transcripts.txt", "\n".join(all_v))
    atomic_write_text(d / "all_shorts_transcripts.txt", "\n".join(all_s))
    atomic_write_json(d / "all_ideas.json", {"channel_id": channel.id, "channel_name": channel.name,
                                             "count": len(idea_rows), "ideas": idea_rows})
    atomic_write_text(d / "ideas_catalog.csv", ideas_csv(idea_rows))
    from app.models import ChannelReport

    report = session.execute(select(ChannelReport).where(ChannelReport.channel_id == channel.id)
                             .order_by(ChannelReport.id.desc())).scalars().first()
    if report is not None:
        atomic_write_text(d / "channel_summary.md", report.markdown)
    else:
        atomic_write_text(d / "channel_summary.md", f"# {channel.name}\n\nNo channel report generated yet.\n")
    return d
