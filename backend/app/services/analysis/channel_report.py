"""Channel-level analysis. Aggregates are computed deterministically from stored,
source-linked ideas; an optional LLM narrative must cite idea ids, and
uncited statements are discarded."""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Channel, ChannelReport, Idea, Transcript, Video
from app.services.ai import prompts as P
from app.services.ai.llm import StructuredLLM
from app.services.ai.schemas import ChannelNarrative
from app.services.analysis.common import candidate_pairs, idea_ref, norm_topic
from app.utils.text import STOPWORDS
from app.utils.time import fmt_ts, utcnow

log = logging.getLogger(__name__)


def build_channel_data(session: Session, channel: Channel) -> dict[str, Any]:
    videos = {v.id: v for v in session.execute(select(Video).where(Video.channel_id == channel.id)).scalars()}
    ideas = list(session.execute(select(Idea).where(Idea.channel_id == channel.id).order_by(Idea.video_id, Idea.ordinal)).scalars())
    n_transcripts = session.execute(
        select(Transcript.video_id).join(Video, Video.id == Transcript.video_id)
        .where(Video.channel_id == channel.id, Transcript.is_current.is_(True), Transcript.kind == "source")
    ).all()
    vt = lambda i: videos[i.video_id].title if i.video_id in videos else None  # noqa: E731

    topic_ideas: dict[str, list[Idea]] = defaultdict(list)
    topic_label: dict[str, str] = {}
    for i in ideas:
        k = norm_topic(i.topic)
        topic_ideas[k].append(i)
        topic_label.setdefault(k, i.topic or "General")
    topic_distribution = sorted(
        ({"topic": topic_label[k], "ideas": len(v), "videos": len({x.video_id for x in v})} for k, v in topic_ideas.items()),
        key=lambda d: (-d["videos"], -d["ideas"]))
    recurring = [
        {"topic": topic_label[k], "video_count": len({x.video_id for x in v}),
         "sources": [idea_ref(x, vt(x)) for x in sorted(v, key=lambda x: -(x.confidence or 0))[:8]]}
        for k, v in topic_ideas.items() if len({x.video_id for x in v}) >= 2
    ]
    recurring.sort(key=lambda d: -d["video_count"])

    kw_videos: dict[str, set[str]] = defaultdict(set)
    kw_ideas: dict[str, list[Idea]] = defaultdict(list)
    for i in ideas:
        for kw in {k.lower() for k in (i.keywords or [])} - STOPWORDS:
            kw_videos[kw].add(i.video_id)
            kw_ideas[kw].append(i)
    frequent = [{"concept": kw, "video_count": len(vs), "sources": [idea_ref(x, vt(x)) for x in kw_ideas[kw][:5]]}
                for kw, vs in kw_videos.items() if len(vs) >= 2]
    frequent.sort(key=lambda d: -d["video_count"])

    examples = [idea_ref(i, vt(i)) | {"type": i.idea_type, "explanation": i.explanation[:300]}
                for i in ideas if i.idea_type in ("example", "analogy")][:60]

    unique = []
    for i in ideas:
        kws = {k.lower() for k in (i.keywords or [])} - STOPWORDS
        if kws and all(len(kw_videos[k]) == 1 for k in kws):
            unique.append(i)
    unique.sort(key=lambda i: -(i.confidence or 0))
    unique_refs = [idea_ref(i, vt(i)) | {"explanation": i.explanation[:300]} for i in unique[:50]]

    by_type: dict[str, dict[str, Any]] = {}
    for kind in ("video", "short", "live"):
        vids = [v for v in videos.values() if v.video_type == kind]
        if not vids:
            continue
        kind_ideas = [i for i in ideas if videos.get(i.video_id) and videos[i.video_id].video_type == kind]
        analysed = [v for v in vids if v.analysis_status == "completed"]
        tc = Counter(i.topic or "General" for i in kind_ideas)
        by_type[kind] = {"videos": len(vids), "analysed": len(analysed), "ideas": len(kind_ideas),
                         "avg_ideas_per_analysed": round(len(kind_ideas) / len(analysed), 2) if analysed else None,
                         "top_topics": tc.most_common(10)}

    over_time: dict[str, Counter] = defaultdict(Counter)
    for i in ideas:
        v = videos.get(i.video_id)
        if v and v.upload_date:
            over_time[v.upload_date[:4]][i.topic or "General"] += 1
    emphasis = [{"period": p, "top_topics": c.most_common(8), "ideas": sum(c.values())} for p, c in sorted(over_time.items())]

    related = [{"similarity": round(s, 3), "basis": "lexical (keywords/title overlap; not semantically validated)",
                "a": idea_ref(a, vt(a)), "b": idea_ref(b, vt(b))}
               for s, a, b in candidate_pairs(ideas, different="video_id", max_pairs=60)]

    index: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for i in ideas:
        index[i.topic or "General"].append({"idea_id": i.id, "title": i.title, "type": i.idea_type,
                                            "video_id": i.video_id, "start": i.start_time})
    return {
        "channel_id": channel.id,
        "channel_name": channel.name,
        "generated_at": str(utcnow()),
        "totals": {"videos": sum(1 for v in videos.values() if v.video_type != "short"),
                   "shorts": sum(1 for v in videos.values() if v.video_type == "short"),
                   "transcripts": len(n_transcripts),
                   "analysed": sum(1 for v in videos.values() if v.analysis_status == "completed"),
                   "ideas": len(ideas)},
        "topic_distribution": topic_distribution,
        "recurring_themes": recurring[:40],
        "frequent_concepts": frequent[:60],
        "important_examples": examples,
        "unique_ideas": unique_refs,
        "video_vs_shorts": by_type,
        "emphasis_over_time": emphasis,
        "related_across_uploads": related,
        "idea_index": dict(sorted(index.items())),
    }


def _narrative_input(data: dict[str, Any], ideas: list[Idea], max_chars: int) -> str:
    lines = [f"Totals: {json.dumps(data['totals'])}", "Topic distribution:"]
    lines += [f"- {t['topic']}: {t['ideas']} ideas in {t['videos']} videos" for t in data["topic_distribution"][:25]]
    lines.append("Ideas (id | year | topic | title):")
    yr = {}
    for i in ideas:
        yr[i.id] = (i.upload_date or "")[:4]
    for i in sorted(ideas, key=lambda i: -(i.confidence or 0)):
        lines.append(f"[{i.id}] {yr[i.id]} | {i.topic} | {i.title}")
        if sum(len(x) for x in lines) > max_chars:
            lines.append("[... more ideas omitted for length ...]")
            break
    return "\n".join(lines)


def generate_narrative(session: Session, channel: Channel, data: dict[str, Any], llm: StructuredLLM,
                       context_tokens: int) -> tuple[dict[str, Any], int]:
    ideas = list(session.execute(select(Idea).where(Idea.channel_id == channel.id)).scalars())
    tmpl = P.get_active(session, "channel_analysis")
    prompt = P.render(tmpl.body, channel_name=channel.name,
                      report_data=_narrative_input(data, ideas, max_chars=int(context_tokens * 4 * 0.5)))
    nar = llm.generate(prompt, ChannelNarrative)
    valid = {i.id for i in ideas}
    out: dict[str, Any] = {"overview": nar.overview, "dropped_uncited": 0}
    for field in ("recurring_themes", "notable_insights", "evolution"):
        kept = []
        for st in getattr(nar, field):
            ids = [x for x in st.idea_ids if x in valid]
            if ids:
                kept.append({"statement": st.statement, "idea_ids": ids})
            else:
                out["dropped_uncited"] += 1
        out[field] = kept
    return out, tmpl.version


def report_markdown(data: dict[str, Any], narrative: dict[str, Any] | None) -> str:
    L = [f"# Channel report: {data['channel_name']}", "", f"_Generated {data['generated_at']}_", ""]
    t = data["totals"]
    L += [f"- Videos: {t['videos']} · Shorts: {t['shorts']} · Transcripts: {t['transcripts']} · "
          f"Analysed: {t['analysed']} · Ideas: {t['ideas']}", ""]
    if narrative:
        L += ["## Overview", "", narrative.get("overview", ""), ""]
        for field, title in (("recurring_themes", "Recurring themes"), ("notable_insights", "Notable insights"),
                             ("evolution", "Changes over time")):
            if narrative.get(field):
                L += [f"## {title}", ""] + [f"- {s['statement']} (ideas {', '.join(map(str, s['idea_ids']))})"
                                            for s in narrative[field]] + [""]
    L += ["## Topic distribution", "", "| Topic | Ideas | Videos |", "|---|---|---|"]
    L += [f"| {d['topic']} | {d['ideas']} | {d['videos']} |" for d in data["topic_distribution"][:40]] + [""]
    if data["recurring_themes"]:
        L += ["## Recurring themes (topics in 2+ uploads)", ""]
        for r in data["recurring_themes"][:20]:
            L.append(f"- **{r['topic']}** — {r['video_count']} uploads")
            L += [f"  - [{s['title']}]({s['url']})" for s in r["sources"][:3]]
        L.append("")
    if data["frequent_concepts"]:
        L += ["## Frequently discussed concepts", "",
              ", ".join(f"{c['concept']} ({c['video_count']})" for c in data["frequent_concepts"][:40]), ""]
    if data["emphasis_over_time"]:
        L += ["## Topic emphasis over time", ""]
        L += [f"- {e['period']}: " + ", ".join(f"{t} ({n})" for t, n in e["top_topics"][:5]) for e in data["emphasis_over_time"]]
        L.append("")
    if data["unique_ideas"]:
        L += ["## Unique ideas", ""] + [f"- [{u['title']}]({u['url']})" for u in data["unique_ideas"][:25]] + [""]
    L += ["## Idea index", ""]
    for topic, items in data["idea_index"].items():
        L.append(f"### {topic}")
        L += [f"- {x['title']} — `{x['video_id']}` @ {fmt_ts(x['start']) if x['start'] is not None else '?'}" for x in items]
        L.append("")
    return "\n".join(L)


def generate_channel_report(session: Session, channel: Channel, llm: StructuredLLM | None,
                            context_tokens: int = 8192) -> ChannelReport:
    data = build_channel_data(session, channel)
    narrative, pv = None, None
    if llm is not None and data["totals"]["ideas"] > 0:
        try:
            narrative, pv = generate_narrative(session, channel, data, llm, context_tokens)
        except Exception as exc:  # deterministic report is still useful
            log.warning("channel narrative failed: %s", exc)
            data["narrative_error"] = str(exc)[:500]
    rep = ChannelReport(channel_id=channel.id, data=data, narrative=narrative,
                        markdown=report_markdown(data, narrative),
                        model=getattr(llm, "model_name", None) if narrative else None, prompt_version=pv)
    session.add(rep)
    session.flush()
    return rep
