"""Caption parsing and normalisation.

Supports WebVTT, SRT and YouTube json3. Handles:

* hour-less / comma-decimal / malformed timestamps (malformed cues are skipped
  and counted, never invented)
* inline tags (``<c>``, ``<00:00:01.000>``, ``<v Speaker>``, ``<i>``) and HTML entities
* YouTube "rolling" auto-captions, where each cue repeats the previous line and
  appends new words. De-duplication is only applied when the rolling pattern
  is detected, and only against the immediately preceding cue, so genuinely
  repeated speech in normal captions is preserved.
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field

TS_RE = re.compile(r"^\s*(?:(\d+):)?(\d{1,2}):(\d{1,2})(?:[.,](\d{1,3}))?\s*$")
TIMING_RE = re.compile(r"^\s*(\S+)\s*-->\s*(\S+)(.*)$")
TAG_RE = re.compile(r"<[^>]*>")
SPACE_RE = re.compile(r"\s+")


@dataclass
class Cue:
    start: float
    end: float
    lines: list[str]

    @property
    def text(self) -> str:
        return " ".join(self.lines)


@dataclass
class Segment:
    start: float
    end: float
    text: str
    confidence: float | None = None


@dataclass
class ParseResult:
    segments: list[Segment]
    format: str
    warnings: list[str] = field(default_factory=list)
    rolling_detected: bool = False
    skipped_cues: int = 0


def parse_timestamp(value: str) -> float | None:
    m = TS_RE.match(value)
    if not m:
        return None
    h, mnt, s, frac = m.groups()
    mnt_i, s_i = int(mnt), int(s)
    if s_i >= 60 or (h is not None and mnt_i >= 60):
        return None
    ms = int((frac or "0").ljust(3, "0")[:3])
    return int(h or 0) * 3600 + mnt_i * 60 + s_i + ms / 1000.0


def clean_text(line: str) -> str:
    line = TAG_RE.sub("", line)
    line = html.unescape(html.unescape(line))  # some tracks are double-escaped
    line = line.replace("​", "").replace("\xa0", " ")
    return SPACE_RE.sub(" ", line).strip()


def _parse_blocks(text: str, fmt: str) -> tuple[list[Cue], int, list[str]]:
    text = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("﻿")
    blocks = re.split(r"\n\s*\n", text)
    cues: list[Cue] = []
    skipped = 0
    warnings: list[str] = []
    for block in blocks:
        lines = [ln for ln in block.split("\n")]
        while lines and not lines[0].strip():
            lines.pop(0)
        if not lines:
            continue
        head = lines[0].strip()
        if fmt == "vtt" and (head.startswith("WEBVTT") or head.startswith(("NOTE", "STYLE", "REGION"))):
            # header may be immediately followed by a cue without blank line in sloppy files
            idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
            if idx is None:
                continue
            lines = lines[idx:]
        timing_idx = next((i for i, ln in enumerate(lines[:3]) if "-->" in ln), None)
        if timing_idx is None:
            continue
        m = TIMING_RE.match(lines[timing_idx])
        if not m:
            skipped += 1
            continue
        start, end = parse_timestamp(m.group(1)), parse_timestamp(m.group(2))
        if start is None or end is None:
            skipped += 1
            if len(warnings) < 20:
                warnings.append(f"invalid timestamp: {lines[timing_idx].strip()[:80]}")
            continue
        if end < start:
            end = start
        body = [clean_text(ln) for ln in lines[timing_idx + 1:]]
        body = [b for b in body if b]
        if not body:
            continue
        cues.append(Cue(start, end, body))
    return cues, skipped, warnings


def detect_rolling(cues: list[Cue]) -> bool:
    """YouTube auto-captions: cue N's first line equals cue N-1's last line,
    and many ~10ms 'settle' cues exist."""
    if len(cues) < 6:
        return False
    repeats = 0
    tiny = 0
    for prev, cur in zip(cues, cues[1:]):
        if cur.lines and prev.lines and cur.lines[0] == prev.lines[-1]:
            repeats += 1
        if cur.end - cur.start <= 0.05:
            tiny += 1
    n = len(cues) - 1
    return repeats / n >= 0.3 or tiny / n >= 0.3


def collapse_rolling(cues: list[Cue]) -> list[Segment]:
    segments: list[Segment] = []
    prev_lines: list[str] = []
    for cue in cues:
        is_tiny = cue.end - cue.start <= 0.05
        for line in cue.lines:
            # skip lines carried over from the previous cue (rolling window)
            if line in prev_lines[-2:]:
                continue
            last = segments[-1] if segments else None
            if last and line.startswith(last.text) and cue.start <= last.end + 0.5:
                # growing line: "hello" -> "hello world"
                last.text = line
                last.end = max(last.end, cue.end)
                continue
            if is_tiny and last and last.text.endswith(line):
                continue
            segments.append(Segment(cue.start, cue.end, line))
        if not is_tiny:
            prev_lines = cue.lines
        else:
            prev_lines = prev_lines + [ln for ln in cue.lines if ln not in prev_lines]
    # fix end times: a rolling line remains on screen while the next is spoken
    for a, b in zip(segments, segments[1:]):
        if a.end <= a.start:
            a.end = b.start
    return [s for s in segments if s.text]


def cues_to_segments(cues: list[Cue]) -> list[Segment]:
    segs: list[Segment] = []
    for cue in cues:
        text = cue.text
        # Exact duplicate cue (same text and same timing) is a file artifact, not speech.
        if segs and segs[-1].text == text and abs(segs[-1].start - cue.start) < 0.01:
            continue
        segs.append(Segment(cue.start, cue.end, text))
    return segs


def parse_vtt(text: str) -> ParseResult:
    cues, skipped, warnings = _parse_blocks(text, "vtt")
    cues.sort(key=lambda c: (c.start, c.end))
    rolling = detect_rolling(cues)
    segs = collapse_rolling(cues) if rolling else cues_to_segments(cues)
    return ParseResult(segs, "vtt", warnings, rolling, skipped)


def parse_srt(text: str) -> ParseResult:
    cues, skipped, warnings = _parse_blocks(text, "srt")
    cues.sort(key=lambda c: (c.start, c.end))
    rolling = detect_rolling(cues)
    segs = collapse_rolling(cues) if rolling else cues_to_segments(cues)
    return ParseResult(segs, "srt", warnings, rolling, skipped)


def parse_json3(text: str) -> ParseResult:
    data = json.loads(text)
    segs: list[Segment] = []
    for ev in data.get("events", []):
        if "segs" not in ev or ev.get("aAppend"):
            continue
        start = (ev.get("tStartMs") or 0) / 1000
        dur = (ev.get("dDurationMs") or 0) / 1000
        line = clean_text("".join(s.get("utf8", "") for s in ev["segs"]).replace("\n", " "))
        if line:
            segs.append(Segment(start, start + dur, line))
    segs.sort(key=lambda s: s.start)
    return ParseResult(segs, "json3")


def parse_captions(text: str, fmt: str | None = None) -> ParseResult:
    fmt = (fmt or "").lower()
    stripped = text.lstrip("﻿").lstrip()
    if fmt == "json3" or (not fmt and stripped.startswith("{")):
        return parse_json3(text)
    if fmt == "srt" or (not fmt and not stripped.startswith("WEBVTT") and re.match(r"^\d+\s*\n", stripped)):
        return parse_srt(text)
    return parse_vtt(text)


def segments_to_vtt(segments: list[Segment] | list[dict]) -> str:
    from app.utils.time import fmt_ts

    out = ["WEBVTT", ""]
    for i, s in enumerate(segments):
        start = s["start"] if isinstance(s, dict) else s.start
        end = s["end"] if isinstance(s, dict) else s.end
        txt = s["text"] if isinstance(s, dict) else s.text
        out.append(f"S{i:05d}")
        out.append(f"{fmt_ts(start, vtt=True)} --> {fmt_ts(max(end, start), vtt=True)}")
        out.append(txt)
        out.append("")
    return "\n".join(out)
