from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from app.models import Idea
from app.services.youtube.urls import watch_url
from app.utils.text import jaccard, tokens


def idea_ref(i: Idea, video_title: str | None = None) -> dict[str, Any]:
    return {"idea_id": i.id, "title": i.title, "video_id": i.video_id, "video_title": video_title,
            "channel_id": i.channel_id, "start": i.start_time, "url": watch_url(i.video_id, i.start_time)}


def idea_tokens(i: Idea) -> set[str]:
    return set(tokens(i.title)) | set(tokens(" ".join(i.keywords or [])))


def candidate_pairs(ideas: list[Idea], *, different: str = "video_id", min_shared: int = 2,
                    threshold: float = 0.35, max_pairs: int = 100, max_bucket: int = 200) -> list[tuple[float, Idea, Idea]]:
    """Lexically similar idea pairs, found via an inverted index (avoids O(n^2) on large channels).

    These are *candidates* only; similar words do not imply equivalent meaning.
    """
    toks = {i.id: idea_tokens(i) for i in ideas}
    index: dict[str, list[Idea]] = defaultdict(list)
    for i in ideas:
        for t in toks[i.id]:
            index[t].append(i)
    shared: dict[tuple[int, int], int] = defaultdict(int)
    by_id = {i.id: i for i in ideas}
    for t, bucket in index.items():
        if len(bucket) > max_bucket:  # too common to be informative
            continue
        for a_i in range(len(bucket)):
            for b_i in range(a_i + 1, len(bucket)):
                a, b = bucket[a_i], bucket[b_i]
                if getattr(a, different) == getattr(b, different):
                    continue
                key = (min(a.id, b.id), max(a.id, b.id))
                shared[key] += 1
    out = []
    for (a_id, b_id), n in shared.items():
        if n < min_shared:
            continue
        s = jaccard(toks[a_id], toks[b_id])
        if s >= threshold:
            out.append((s, by_id[a_id], by_id[b_id]))
    out.sort(key=lambda x: -x[0])
    return out[:max_pairs]


def norm_topic(t: str | None) -> str:
    return (t or "General").strip().lower()


def counter_top(items: Iterable[tuple[str, Any]], n: int) -> list[tuple[str, Any]]:
    return sorted(items, key=lambda kv: -kv[1])[:n]
