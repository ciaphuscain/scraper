"""Timestamp-preserving, token-aware transcript chunking."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.utils.text import estimate_tokens
from app.utils.time import fmt_ts

SENTENCE_END = (".", "!", "?", "…", '."', '?"', '!"')


@dataclass
class Chunk:
    index: int
    segments: list[dict[str, Any]]  # dicts with seg_key, start, end, text
    overlap_keys: list[str] = field(default_factory=list)

    @property
    def keys(self) -> list[str]:
        return [s["seg_key"] for s in self.segments]

    @property
    def text(self) -> str:
        return "\n".join(format_line(s) for s in self.segments)

    @property
    def start(self) -> float:
        return self.segments[0]["start"]

    @property
    def end(self) -> float:
        return self.segments[-1]["end"]


def format_line(seg: dict[str, Any]) -> str:
    return f"[{seg['seg_key']} | {fmt_ts(seg['start'])}] {seg['text']}"


def chunk_segments(segments: list[dict[str, Any]], max_tokens: int = 1200, overlap: int = 1) -> list[Chunk]:
    """Split segments into chunks of roughly ``max_tokens``.

    Prefers to end a chunk on a sentence boundary when one occurs in the last
    quarter of the budget. ``overlap`` trailing segments are repeated at the
    start of the next chunk for context; cross-chunk dedupe merges resulting
    duplicates.
    """
    chunks: list[Chunk] = []
    if not segments:
        return chunks
    i = 0
    n = len(segments)
    while i < n:
        budget = 0
        j = i
        last_sentence_end = None
        while j < n:
            cost = estimate_tokens(format_line(segments[j])) + 1
            if budget + cost > max_tokens and j > i:
                break
            budget += cost
            if segments[j]["text"].rstrip().endswith(SENTENCE_END) and budget >= max_tokens * 0.75:
                last_sentence_end = j
            j += 1
        end = j
        if end < n and last_sentence_end is not None and last_sentence_end + 1 > i:
            end = last_sentence_end + 1
        body = segments[i:end]
        prefix: list[dict[str, Any]] = []
        if chunks and overlap > 0:
            prefix = segments[max(0, i - overlap):i]
        chunks.append(Chunk(len(chunks), prefix + body, [s["seg_key"] for s in prefix]))
        i = end
    return chunks
