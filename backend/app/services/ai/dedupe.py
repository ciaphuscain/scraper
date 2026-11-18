"""Cross-chunk idea de-duplication.

Lexical similarity proposes candidates; only near-identical pairs are merged
automatically. Borderline pairs are merged only if the LLM confirms semantic
equivalence (when enabled). Merging preserves every source reference.
"""
from __future__ import annotations

from typing import Callable

from app.services.ai.validation import SourcedIdea, ValidationStats
from app.utils.text import jaccard, normalize_for_match, tokens

AUTO_MERGE = 0.72
CANDIDATE = 0.42
MAX_LLM_CHECKS = 60


def _sig(idea: SourcedIdea) -> tuple[set[str], set[str]]:
    title = set(tokens(idea.title))
    body = title | set(tokens(" ".join(idea.keywords))) | set(tokens(idea.explanation)[:40])
    return title, body


def similarity(a: SourcedIdea, b: SourcedIdea) -> float:
    if normalize_for_match(a.title) == normalize_for_match(b.title):
        return 1.0
    ta, ba = _sig(a)
    tb, bb = _sig(b)
    seg_overlap = jaccard(set(a.segment_keys), set(b.segment_keys))
    return max(jaccard(ta, tb), 0.6 * jaccard(ba, bb) + 0.4 * seg_overlap)


def merge_into(base: SourcedIdea, other: SourcedIdea) -> None:
    base.segment_keys = sorted(set(base.segment_keys) | set(other.segment_keys))
    seen = {k.lower() for k in base.keywords}
    for k in other.keywords:
        if k.lower() not in seen:
            base.keywords.append(k)
            seen.add(k.lower())
    texts = {e["text"] for e in base.excerpts}
    for e in other.excerpts:
        if e["text"] not in texts:
            base.excerpts.append(e)
            texts.add(e["text"])
    if len(other.explanation) > len(base.explanation):
        base.explanation = other.explanation
    if other.confidence is not None:
        base.confidence = max(base.confidence or 0, other.confidence)
    times = [t for t in (base.start_time, other.start_time) if t is not None]
    base.start_time = min(times) if times else None
    ends = [t for t in (base.end_time, other.end_time) if t is not None]
    base.end_time = max(ends) if ends else None


def dedupe_ideas(
    ideas: list[SourcedIdea],
    stats: ValidationStats,
    confirm: Callable[[SourcedIdea, SourcedIdea], bool] | None = None,
) -> list[SourcedIdea]:
    n = len(ideas)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    candidates: list[tuple[float, int, int]] = []
    for i in range(n):
        for j in range(i + 1, n):
            if ideas[i].chunk_index == ideas[j].chunk_index:
                # Same chunk: the extractor already separated these, unless titles are identical.
                if normalize_for_match(ideas[i].title) != normalize_for_match(ideas[j].title):
                    continue
            s = similarity(ideas[i], ideas[j])
            if s >= CANDIDATE:
                candidates.append((s, i, j))
    candidates.sort(reverse=True)
    checks = 0
    for s, i, j in candidates:
        ri, rj = find(i), find(j)
        if ri == rj:
            continue
        if s >= AUTO_MERGE:
            parent[rj] = ri
            continue
        if confirm is not None and checks < MAX_LLM_CHECKS:
            checks += 1
            stats.llm_merge_checks += 1
            try:
                if confirm(ideas[i], ideas[j]):
                    parent[rj] = ri
            except Exception as exc:  # LLM failure: be conservative, keep both
                stats.notes.append(f"dedupe check failed: {exc}"[:200])
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    out: list[SourcedIdea] = []
    for members in groups.values():
        members.sort(key=lambda k: (-len(ideas[k].explanation), k))
        base = ideas[members[0]]
        for m in members[1:]:
            merge_into(base, ideas[m])
            stats.merged += 1
        out.append(base)
    out.sort(key=lambda x: (x.start_time if x.start_time is not None else 1e12, x.title))
    return out
