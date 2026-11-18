"""Cross-channel comparison. Lexical candidates are only labelled as
equivalent/contradictory after LLM semantic validation; otherwise they are
reported as unvalidated candidates."""
from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Channel, CrossChannelReport, Idea, Video
from app.services.ai import prompts as P
from app.services.ai.llm import StructuredLLM
from app.services.ai.schemas import PairJudgement
from app.services.analysis.common import candidate_pairs, idea_ref, norm_topic
from app.utils.time import utcnow

log = logging.getLogger(__name__)


def compare_channels(session: Session, channel_ids: list[str], llm: StructuredLLM | None,
                     max_pairs: int = 40) -> CrossChannelReport:
    channels = {c.id: c for c in session.execute(select(Channel).where(Channel.id.in_(channel_ids))).scalars()}
    if len(channels) < 2:
        raise ValueError("select at least two existing channels")
    ideas = list(session.execute(select(Idea).where(Idea.channel_id.in_(list(channels)))).scalars())
    titles = dict(session.execute(select(Video.id, Video.title).where(Video.channel_id.in_(list(channels)))).all())
    ref = lambda i: idea_ref(i, titles.get(i.video_id)) | {"channel_name": channels[i.channel_id].name}  # noqa: E731

    topic_freq: dict[str, Counter] = {cid: Counter() for cid in channels}
    labels: dict[str, str] = {}
    for i in ideas:
        k = norm_topic(i.topic)
        labels.setdefault(k, i.topic or "General")
        topic_freq[i.channel_id][k] += 1
    all_topics = set().union(*[set(c) for c in topic_freq.values()])
    shared = []
    for k in all_topics:
        present = [cid for cid in channels if topic_freq[cid][k] > 0]
        if len(present) >= 2:
            shared.append({"topic": labels[k], "channels": {cid: topic_freq[cid][k] for cid in present}})
    shared.sort(key=lambda d: -sum(d["channels"].values()))
    unique_topics = {cid: [labels[k] for k, _ in topic_freq[cid].most_common() if
                           all(topic_freq[o][k] == 0 for o in channels if o != cid)][:30] for cid in channels}

    kw_ch: dict[str, Counter] = defaultdict(Counter)
    for i in ideas:
        for kw in {k.lower() for k in (i.keywords or [])}:
            kw_ch[kw][i.channel_id] += 1
    unique_concepts = {cid: sorted([kw for kw, c in kw_ch.items() if len(c) == 1 and c[cid] >= 2],
                                   key=lambda kw: -kw_ch[kw][cid])[:30] for cid in channels}

    pairs = candidate_pairs(ideas, different="channel_id", max_pairs=max_pairs, threshold=0.3)
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    validated = llm is not None
    for score, a, b in pairs:
        entry: dict[str, Any] = {"lexical_similarity": round(score, 3), "a": ref(a), "b": ref(b)}
        if llm is not None:
            try:
                tmpl = P.get_active(session, "cross_channel")
                j = llm.generate(P.render(tmpl.body, channel_a=channels[a.channel_id].name,
                                          channel_b=channels[b.channel_id].name,
                                          idea_a=f"{a.title}: {a.explanation}", idea_b=f"{b.title}: {b.explanation}"),
                                 PairJudgement)
                entry["relation"] = j.relation
                entry["explanation"] = j.explanation
            except Exception as exc:
                entry["relation"] = "unvalidated"
                entry["explanation"] = f"validation failed: {exc}"[:200]
        else:
            entry["relation"] = "unvalidated"
        rel = entry["relation"]
        if rel == "unrelated":
            continue
        if rel in ("same", "similar"):
            groups["similar_ideas"].append(entry)
            if a.statement_kind == "creator_claim" and b.statement_kind == "creator_claim":
                groups["repeated_claims"].append(entry)
            if a.idea_type in ("example", "analogy") and b.idea_type in ("example", "analogy"):
                groups["overlapping_examples"].append(entry)
        elif rel == "different_perspective":
            groups["different_perspectives"].append(entry)
        elif rel == "contradictory":
            groups["contradictory_claims"].append(entry)
        else:
            groups["unvalidated_candidates"].append(entry)

    data = {
        "generated_at": str(utcnow()),
        "channels": [{"id": c.id, "name": c.name, "ideas": sum(topic_freq[c.id].values())} for c in channels.values()],
        "semantic_validation": validated,
        "shared_topics": shared[:60],
        "topic_frequency": {cid: [(labels[k], n) for k, n in topic_freq[cid].most_common(30)] for cid in channels},
        "unique_topics": unique_topics,
        "unique_concepts": unique_concepts,
        **{k: groups.get(k, []) for k in ("similar_ideas", "different_perspectives", "contradictory_claims",
                                          "repeated_claims", "overlapping_examples", "unvalidated_candidates")},
    }
    rep = CrossChannelReport(channel_ids=sorted(channels), data=data, markdown=_markdown(data),
                             model=getattr(llm, "model_name", None), semantic_validation=validated)
    session.add(rep)
    session.flush()
    return rep


def _markdown(d: dict[str, Any]) -> str:
    names = {c["id"]: c["name"] for c in d["channels"]}
    L = ["# Cross-channel comparison", "", "Channels: " + ", ".join(names.values()), ""]
    if not d["semantic_validation"]:
        L += ["> Ollama was not used: idea pairs below are lexical candidates only and have NOT been "
              "semantically validated.", ""]
    L += ["## Shared topics", ""] + [f"- **{s['topic']}**: " + ", ".join(f"{names[c]} ({n})" for c, n in s["channels"].items())
                                     for s in d["shared_topics"][:30]] + [""]
    for key, title in (("similar_ideas", "Similar ideas"), ("different_perspectives", "Different perspectives"),
                       ("contradictory_claims", "Contradictory claims"), ("repeated_claims", "Repeated claims"),
                       ("overlapping_examples", "Overlapping examples"), ("unvalidated_candidates", "Unvalidated candidates")):
        if d.get(key):
            L += [f"## {title}", ""]
            for e in d[key]:
                L.append(f"- [{e['a']['title']}]({e['a']['url']}) ({e['a']['channel_name']}) ↔ "
                         f"[{e['b']['title']}]({e['b']['url']}) ({e['b']['channel_name']})"
                         + (f" — {e.get('explanation')}" if e.get("explanation") else ""))
            L.append("")
    L += ["## Unique topics", ""]
    for cid, ts in d["unique_topics"].items():
        L.append(f"- **{names[cid]}**: {', '.join(ts[:15]) or '—'}")
    return "\n".join(L)
