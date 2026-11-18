"""Source validation for extracted ideas.

Every stored idea must be backed by real transcript segments. Timestamps are
always derived from segments, never taken from the model. Excerpts that do not
appear verbatim (after whitespace/punctuation normalisation) in the cited
segments are discarded and replaced with actual source text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.services.ai.schemas import ChunkIdea
from app.utils.text import normalize_for_match

KEY_RE = re.compile(r"s?\s*0*(\d+)", re.I)


def normalize_key(raw: str) -> str | None:
    m = KEY_RE.fullmatch(raw.strip().strip("[]"))
    if not m:
        m = KEY_RE.search(raw)
        if not m:
            return None
    return f"S{int(m.group(1)):05d}"


@dataclass
class ValidationStats:
    raw_ideas: int = 0
    dropped_unsourced: int = 0
    invalid_segment_refs: int = 0
    excerpts_verified: int = 0
    excerpts_replaced: int = 0
    sources_recovered_from_excerpt: int = 0
    merged: int = 0
    llm_merge_checks: int = 0
    final_ideas: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class SourcedIdea:
    title: str
    explanation: str
    idea_type: str
    topic: str
    keywords: list[str]
    segment_keys: list[str]
    excerpts: list[dict[str, Any]]
    statement_kind: str
    confidence: float | None
    chunk_index: int
    start_time: float | None = None
    end_time: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SourcedIdea:
        return cls(**d)


def _find_excerpt(excerpt: str, segs: list[dict[str, Any]]) -> list[str]:
    """Return keys of the segment(s) whose (concatenated) text contains excerpt."""
    target = normalize_for_match(excerpt)
    if len(target) < 3:
        return []
    for s in segs:
        if target in normalize_for_match(s["text"]):
            return [s["seg_key"]]
    # spans multiple consecutive segments
    for i in range(len(segs)):
        acc = ""
        keys = []
        for s in segs[i:i + 6]:
            acc = (acc + " " + normalize_for_match(s["text"])).strip()
            keys.append(s["seg_key"])
            if target in acc:
                return keys
            if len(acc) > len(target) * 3 + 200:
                break
    return []


def validate_idea(raw: ChunkIdea, chunk_segments: list[dict[str, Any]], chunk_index: int,
                  stats: ValidationStats) -> SourcedIdea | None:
    by_key = {s["seg_key"]: s for s in chunk_segments}
    keys: list[str] = []
    for r in raw.segment_ids:
        k = normalize_key(r)
        if k and k in by_key:
            if k not in keys:
                keys.append(k)
        else:
            stats.invalid_segment_refs += 1
    excerpts: list[dict[str, Any]] = []
    for ex in raw.excerpts:
        # search cited segments first, then the whole chunk
        cited = [by_key[k] for k in keys]
        found = _find_excerpt(ex, cited) if cited else []
        if not found:
            found = _find_excerpt(ex, chunk_segments)
            if found and not keys:
                stats.sources_recovered_from_excerpt += 1
        if found:
            stats.excerpts_verified += 1
            for k in found:
                if k not in keys:
                    keys.append(k)
            excerpts.append({"text": ex.strip(), "segment_key": found[0], "start": by_key[found[0]]["start"],
                             "verified": True})
    if not keys:
        stats.dropped_unsourced += 1
        return None
    keys.sort()
    if not excerpts:
        stats.excerpts_replaced += 1
        seg = by_key[keys[0]]
        excerpts.append({"text": seg["text"][:400], "segment_key": seg["seg_key"], "start": seg["start"],
                         "verified": True, "source": "segment_text"})
    starts = [by_key[k]["start"] for k in keys]
    ends = [by_key[k]["end"] for k in keys]
    seen_kw: set[str] = set()
    kws = []
    for kw in raw.keywords:
        low = kw.lower()
        if low not in seen_kw and len(kw) <= 80:
            seen_kw.add(low)
            kws.append(kw)
    return SourcedIdea(
        title=raw.title.strip(),
        explanation=raw.explanation.strip(),
        idea_type=raw.idea_type,
        topic=(raw.topic or "").strip()[:200] or "General",
        keywords=kws[:12],
        segment_keys=keys,
        excerpts=excerpts[:6],
        statement_kind=raw.statement_kind,
        confidence=raw.confidence,
        chunk_index=chunk_index,
        start_time=min(starts),
        end_time=max(ends),
    )


def final_check(ideas: list[SourcedIdea], all_segments: dict[str, dict[str, Any]]) -> list[str]:
    """Return a list of integrity problems (should be empty)."""
    problems = []
    for i, idea in enumerate(ideas):
        if not idea.segment_keys:
            problems.append(f"idea {i} has no sources")
        for k in idea.segment_keys:
            if k not in all_segments:
                problems.append(f"idea {i} references unknown segment {k}")
        if idea.start_time is not None and idea.segment_keys:
            real = min(all_segments[k]["start"] for k in idea.segment_keys if k in all_segments)
            if abs(real - idea.start_time) > 0.01:
                problems.append(f"idea {i} start time mismatch")
        for ex in idea.excerpts:
            seg = all_segments.get(ex.get("segment_key", ""))
            if seg is None:
                problems.append(f"idea {i} excerpt has unknown segment")
    return problems
