"""Exports in TXT, Markdown, JSON, JSONL, CSV, SQLite backup and ZIP."""
from __future__ import annotations

import csv
import io
import json
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_env
from app.core.errors import PermanentError
from app.models import Channel, Video
from app.services.exports import records as R
from app.services.exports.archive import ideas_csv, write_channel_files, write_video_files
from app.services.transcripts.store import current_transcript
from app.utils.files import atomic_write_text
from app.utils.time import fmt_ts, utcnow

SCOPES = {"video", "videos", "channel", "channels", "all"}
CONTENTS = {"metadata", "transcripts", "ideas", "summaries"}
FORMATS = {"txt", "md", "json", "jsonl", "csv", "zip", "sqlite"}


def resolve_videos(session: Session, scope: str, ids: list[str]) -> list[Video]:
    if scope not in SCOPES:
        raise PermanentError(f"invalid scope {scope}")
    q = select(Video)
    if scope in ("video", "videos"):
        if not ids:
            raise PermanentError("no videos selected")
        q = q.where(Video.id.in_(ids))
    elif scope in ("channel", "channels"):
        if not ids:
            raise PermanentError("no channels selected")
        q = q.where(Video.channel_id.in_(ids))
    return list(session.execute(q.order_by(Video.channel_id, Video.upload_date.desc().nulls_last(), Video.id)).scalars())


def build_record(session: Session, video: Video, content: set[str], channels: dict[str, Channel]) -> dict[str, Any]:
    channel = channels.get(video.channel_id or "")
    rec: dict[str, Any] = {"video_id": video.id, "title": video.title, "source_url": R.watch_url(video.id),
                           "channel_id": video.channel_id, "channel_name": channel.name if channel else None}
    if "metadata" in content:
        rec["metadata"] = R.video_metadata(video, channel)
    if "transcripts" in content:
        t = current_transcript(session, video.id)
        rec["transcript"] = None if t is None else {**R.transcript_metadata(video, t),
                                                    "text": t.full_text,
                                                    "segments": R.transcript_payload(video, t)["segments"]}
    if "ideas" in content:
        rec["ideas"] = [R.idea_dict(i, video, channel.name if channel else None) for i in R.video_ideas(session, video.id)]
    if "summaries" in content:
        a = R.current_analysis(session, video.id)
        rec["summary"] = None if a is None else {
            "main_theme": a.main_theme, "central_thesis": a.central_thesis, "summary": a.summary,
            "topics": a.topics, "takeaways": a.takeaways, "relationships": a.relationships, "model": a.model,
            "analysis_version": a.analysis_version, "prompt_versions": a.prompt_versions}
    return rec


def _records(session: Session, videos: list[Video], content: set[str]) -> Iterable[dict[str, Any]]:
    channels = {c.id: c for c in session.execute(select(Channel)).scalars()}
    for v in videos:
        yield build_record(session, v, content, channels)


def _txt(rec: dict[str, Any]) -> str:
    out = [f"=== {rec['title']} ===", f"Channel: {rec.get('channel_name')}", f"Source: {rec['source_url']}"]
    md = rec.get("metadata")
    if md:
        out += [f"Upload date: {md.get('upload_date')}", f"Type: {md.get('video_type')}",
                f"Duration: {md.get('duration_seconds')}s"]
    s = rec.get("summary")
    if s:
        out += ["", "SUMMARY", s.get("main_theme") or "", s.get("summary") or ""]
    if rec.get("ideas"):
        out += ["", "IDEAS"]
        for i in rec["ideas"]:
            ts = fmt_ts(i["start_time"]) if i.get("start_time") is not None else "?"
            out += [f"- [{ts}] {i['title']} ({i['idea_type']}): {i['explanation']}  <{i['timestamp_url']}>"]
    t = rec.get("transcript")
    if t:
        out += ["", f"TRANSCRIPT ({t['method']}, {t['completeness']})", t["text"]]
    elif "transcript" in rec:
        out += ["", "TRANSCRIPT: not available"]
    return "\n".join(out) + "\n\n"


def _md(rec: dict[str, Any]) -> str:
    out = [f"# {rec['title']}", "", f"- Channel: {rec.get('channel_name')}", f"- Source: <{rec['source_url']}>"]
    md = rec.get("metadata")
    if md:
        out += [f"- Upload date: {md.get('upload_date')}", f"- Type: {md.get('video_type')}"]
    s = rec.get("summary")
    if s:
        out += ["", "## Summary", "", s.get("main_theme") or "", "", s.get("summary") or ""]
        if s.get("takeaways"):
            out += ["", "### Takeaways"] + [f"- {x}" for x in s["takeaways"]]
    if rec.get("ideas"):
        out += ["", f"## Ideas ({len(rec['ideas'])})", ""]
        for i in rec["ideas"]:
            ts = fmt_ts(i["start_time"]) if i.get("start_time") is not None else "?"
            out += [f"### {i['title']}", f"*{i['idea_type']} · {i['topic']} · [{ts}]({i['timestamp_url']})*", "",
                    i["explanation"], ""]
            out += [f"> {e.get('text', '')}" for e in (i.get("excerpts") or [])[:2]] + [""]
    t = rec.get("transcript")
    if t:
        out += ["", f"## Transcript ({t['method']}, {t['completeness']})", ""]
        out += [f"[{fmt_ts(s['start'])}]({s['url']}) {s['text']}  " for s in t["segments"]]
    return "\n".join(out) + "\n\n---\n\n"


def _sqlite_backup(dest: Path) -> None:
    src_path = get_env().db_path
    src = sqlite3.connect(str(src_path))
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
        ok = dst.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise PermanentError(f"backup integrity check failed: {ok}")
    finally:
        dst.close()
        src.close()


def export(
    session: Session,
    *,
    scope: str,
    ids: list[str],
    content: list[str],
    fmt: str,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    if fmt not in FORMATS:
        raise PermanentError(f"unsupported format {fmt}")
    content_set = set(content or CONTENTS) & CONTENTS
    if not content_set:
        raise PermanentError("no export content selected")
    out_dir = out_dir or (get_env().archive_dir / "exports")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    label = scope if scope == "all" else f"{scope}-{(ids[0] if len(ids) == 1 else f'{len(ids)}items')}"
    name = f"export_{label}_{stamp}"

    if fmt == "sqlite":
        path = out_dir / f"{name}.sqlite"
        _sqlite_backup(path)
        return {"path": str(path), "items": None, "size": path.stat().st_size}

    videos = resolve_videos(session, scope, ids)
    if fmt == "zip":
        path = out_dir / f"{name}.zip"
        with tempfile.TemporaryDirectory(dir=str(out_dir)) as tmp:
            root = Path(tmp) / "YouTube_Content_Archive"
            channel_ids = sorted({v.channel_id for v in videos if v.channel_id})
            if scope in ("channel", "channels", "all"):
                for cid in channel_ids:
                    ch = session.get(Channel, cid)
                    if ch:
                        write_channel_files(session, root, ch)
                for v in videos:
                    if not v.channel_id:
                        write_video_files(session, root, v)
            else:
                for v in videos:
                    write_video_files(session, root, v)
            keep = _zip_filter(content_set)
            tmp_zip = Path(tmp) / "out.zip"
            n_files = 0
            with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in sorted(root.rglob("*")):
                    if f.is_file() and keep(f.name):
                        zf.write(f, f.relative_to(root.parent))
                        n_files += 1
                zf.writestr("YouTube_Content_Archive/export_manifest.json", json.dumps({
                    "exported_at": str(utcnow()), "scope": scope, "ids": ids, "content": sorted(content_set),
                    "videos": len(videos), "files": n_files}, indent=2))
            with zipfile.ZipFile(tmp_zip) as zf:
                bad = zf.testzip()
                if bad:
                    raise PermanentError(f"zip validation failed at {bad}")
            shutil.move(str(tmp_zip), path)
        return {"path": str(path), "items": len(videos), "size": path.stat().st_size}

    recs = list(_records(session, videos, content_set))
    if fmt == "json":
        path = out_dir / f"{name}.json"
        text = json.dumps({"exported_at": str(utcnow()), "scope": scope, "ids": ids, "content": sorted(content_set),
                           "count": len(recs), "records": recs}, ensure_ascii=False, indent=2, default=str)
        json.loads(text)  # validation
    elif fmt == "jsonl":
        path = out_dir / f"{name}.jsonl"
        lines = [json.dumps(r, ensure_ascii=False, default=str) for r in recs]
        text = "\n".join(lines) + ("\n" if lines else "")
    elif fmt == "csv":
        path = out_dir / f"{name}.csv"
        if "ideas" in content_set:
            text = ideas_csv([i for r in recs for i in r.get("ideas", [])])
        else:
            buf = io.StringIO()
            fields = ["video_id", "title", "channel_id", "channel_name", "upload_date", "video_type",
                      "duration_seconds", "source_url", "transcript_status", "transcript_method",
                      "transcript_completeness", "transcript_text"]
            w = csv.DictWriter(buf, fieldnames=fields)
            w.writeheader()
            for r in recs:
                md = r.get("metadata") or {}
                t = r.get("transcript") or {}
                w.writerow({"video_id": r["video_id"], "title": r["title"], "channel_id": r["channel_id"],
                            "channel_name": r["channel_name"], "upload_date": md.get("upload_date"),
                            "video_type": md.get("video_type"), "duration_seconds": md.get("duration_seconds"),
                            "source_url": r["source_url"], "transcript_status": md.get("transcript_status"),
                            "transcript_method": t.get("method"), "transcript_completeness": t.get("completeness"),
                            "transcript_text": t.get("text")})
            text = buf.getvalue()
        list(csv.reader(io.StringIO(text)))  # validation
    elif fmt == "md":
        path = out_dir / f"{name}.md"
        text = f"# Export ({scope})\n\nExported {utcnow()} — {len(recs)} record(s).\n\n" + "".join(_md(r) for r in recs)
    else:  # txt
        path = out_dir / f"{name}.txt"
        text = "".join(_txt(r) for r in recs)
    atomic_write_text(path, text)
    return {"path": str(path), "items": len(recs), "size": path.stat().st_size}


def _zip_filter(content: set[str]):
    allowed: set[str] = {"channel_info.json", "export_manifest.json"}
    if "metadata" in content:
        allowed |= {"metadata.json"}
    if "transcripts" in content:
        allowed |= {"transcript.txt", "transcript_timestamped.json", "transcript.vtt", "transcript_metadata.json",
                    "all_video_transcripts.txt", "all_shorts_transcripts.txt", "original_captions.srt",
                    "original_captions.json3"}
    if "ideas" in content:
        allowed |= {"ideas.json", "all_ideas.json", "ideas_catalog.csv"}
    if "summaries" in content:
        allowed |= {"summary.md", "channel_summary.md"}
    return lambda name: name in allowed
