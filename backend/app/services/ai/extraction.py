"""Hierarchical idea extraction pipeline.

Stage 1  segmentation      -> chunking.chunk_segments
Stage 2  chunk extraction  -> one structured LLM call per chunk (checkpointed)
Stage 3  aggregation       -> dedupe.dedupe_ideas (+ optional LLM confirmation)
Stage 4  video analysis    -> topic normalisation + summary/relationships
Stage 5  validation        -> validation.final_check, then atomic persistence
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.models import Idea, IdeaAnnotation, Transcript, Video, VideoAnalysis
from app.services.ai import prompts as P
from app.services.ai.chunking import Chunk, chunk_segments
from app.services.ai.dedupe import dedupe_ideas
from app.services.ai.llm import StructuredLLM
from app.services.ai.schemas import IDEA_TYPES, ChunkExtraction, DedupeDecision, TopicMap, VideoSummary
from app.services.ai.validation import SourcedIdea, ValidationStats, final_check, validate_idea
from app.utils.text import jaccard, normalize_for_match
from app.utils.time import fmt_ts

log = logging.getLogger(__name__)
ANALYSIS_VERSION = "1.0"


@dataclass
class ExtractionInput:
    video_id: str
    channel_id: str | None
    video_title: str
    channel_name: str
    transcript_id: int
    segments: list[dict[str, Any]]


@dataclass
class ExtractionOutput:
    ideas: list[SourcedIdea]
    summary: VideoSummary
    stats: ValidationStats
    chunk_count: int
    prompt_versions: dict[str, int]
    model: str


def chunk_signature(chunk: Chunk, transcript_id: int, prompt_version: int, model: str) -> str:
    h = hashlib.sha1(f"{transcript_id}|{prompt_version}|{model}|{','.join(chunk.keys)}".encode()).hexdigest()
    return h[:16]


class IdeaExtractor:
    def __init__(
        self,
        llm: StructuredLLM,
        prompt_bodies: dict[str, str],
        prompt_versions: dict[str, int],
        *,
        chunk_tokens: int = 1200,
        overlap: int = 1,
        semantic_dedupe: bool = True,
        context_tokens: int = 8192,
        max_output_tokens: int = 3072,
    ):
        self.llm = llm
        self.prompts = prompt_bodies
        self.versions = prompt_versions
        self.chunk_tokens = chunk_tokens
        self.overlap = overlap
        self.semantic_dedupe = semantic_dedupe
        self.context_tokens = context_tokens
        self.max_output_tokens = max_output_tokens

    def run(
        self,
        inp: ExtractionInput,
        *,
        checkpoint: dict[str, Any] | None = None,
        on_chunk: Callable[[int, int, dict[str, Any]], None] | None = None,
        on_stage: Callable[[str, float], None] | None = None,
    ) -> ExtractionOutput:
        stats = ValidationStats()
        checkpoint = checkpoint if checkpoint is not None else {}
        done: dict[str, Any] = checkpoint.setdefault("chunks", {})
        chunks = chunk_segments(inp.segments, self.chunk_tokens, self.overlap)
        all_ideas: list[SourcedIdea] = []
        pv = self.versions.get("chunk_extraction", 1)
        for chunk in chunks:
            sig = chunk_signature(chunk, inp.transcript_id, pv, self.llm.model_name)
            if sig in done:
                saved = done[sig]
                ideas = [SourcedIdea.from_dict(d) for d in saved["ideas"]]
                for k, v in saved.get("stats", {}).items():
                    if isinstance(v, int) and hasattr(stats, k):
                        setattr(stats, k, getattr(stats, k) + v)
            else:
                chunk_stats = ValidationStats()
                prompt = P.render(
                    self.prompts["chunk_extraction"],
                    chunk_index=chunk.index + 1,
                    chunk_count=len(chunks),
                    video_title=inp.video_title,
                    channel_name=inp.channel_name,
                    idea_types=", ".join(IDEA_TYPES),
                    chunk_text=chunk.text,
                )
                result = self.llm.generate(prompt, ChunkExtraction)
                chunk_stats.raw_ideas = len(result.ideas)
                ideas = []
                for raw in result.ideas:
                    v = validate_idea(raw, chunk.segments, chunk.index, chunk_stats)
                    if v:
                        ideas.append(v)
                done[sig] = {"ideas": [i.to_dict() for i in ideas], "stats": chunk_stats.as_dict()}
                for k, v in chunk_stats.as_dict().items():
                    if isinstance(v, int):
                        setattr(stats, k, getattr(stats, k) + v)
                if on_chunk:
                    on_chunk(chunk.index, len(chunks), checkpoint)
            all_ideas.extend(ideas)
            if on_stage:
                on_stage("extracting_ideas", 0.05 + 0.75 * (chunk.index + 1) / max(1, len(chunks)))

        if on_stage:
            on_stage("combining_ideas", 0.82)
        confirm = self._confirm_same if self.semantic_dedupe else None
        merged = dedupe_ideas(all_ideas, stats, confirm)
        merged = self._normalize_topics(merged, stats)
        if on_stage:
            on_stage("analyzing", 0.9)
        summary = self._summarize(inp, merged, stats)
        seg_map = {s["seg_key"]: s for s in inp.segments}
        problems = final_check(merged, seg_map)
        if problems:
            stats.notes.extend(problems[:50])
            merged = [i for i in merged if i.segment_keys and all(k in seg_map for k in i.segment_keys)]
        stats.final_ideas = len(merged)
        return ExtractionOutput(merged, summary, stats, len(chunks), dict(self.versions), self.llm.model_name)

    # -- helpers
    def _confirm_same(self, a: SourcedIdea, b: SourcedIdea) -> bool:
        prompt = P.render(self.prompts["dedupe"], idea_a=f"{a.title}: {a.explanation}",
                          idea_b=f"{b.title}: {b.explanation}")
        return self.llm.generate(prompt, DedupeDecision).same

    def _normalize_topics(self, ideas: list[SourcedIdea], stats: ValidationStats) -> list[SourcedIdea]:
        topics = sorted({i.topic for i in ideas if i.topic})
        if len(topics) <= 3:
            return ideas
        try:
            prompt = P.render(self.prompts["topic_classification"], topics="\n".join(f"- {t}" for t in topics))
            mapping = self.llm.generate(prompt, TopicMap).mapping
        except Exception as exc:
            stats.notes.append(f"topic normalisation skipped: {exc}"[:200])
            return ideas
        lowered = {k.strip().lower(): v.strip() for k, v in mapping.items() if v and v.strip()}
        for i in ideas:
            canon = lowered.get(i.topic.lower())
            if canon:
                i.topic = canon[:200]
        return ideas

    def _ideas_text(self, ideas: list[SourcedIdea]) -> str:
        budget_chars = max(4000, (self.context_tokens - self.max_output_tokens - 800) * 4 * 0.85)
        for max_expl in (300, 140, 60, 0):
            lines = []
            for n, i in enumerate(ideas, 1):
                expl = (" — " + i.explanation[:max_expl]) if max_expl else ""
                ts = fmt_ts(i.start_time) if i.start_time is not None else "?"
                lines.append(f"{n}. [{i.idea_type} @ {ts}] {i.title}{expl}")
            text = "\n".join(lines)
            if len(text) <= budget_chars:
                return text
        return text[: int(budget_chars)] + "\n[... list truncated to fit the context window ...]"

    def _summarize(self, inp: ExtractionInput, ideas: list[SourcedIdea], stats: ValidationStats) -> VideoSummary:
        if not ideas:
            return VideoSummary(main_theme="", detailed_summary="No substantive ideas were extracted from the "
                                                                 "captured transcript.")
        prompt = P.render(self.prompts["video_summary"], video_title=inp.video_title,
                          channel_name=inp.channel_name, ideas_text=self._ideas_text(ideas))
        try:
            summary = self.llm.generate(prompt, VideoSummary)
        except Exception as exc:
            stats.notes.append(f"summary generation failed: {exc}"[:300])
            return VideoSummary(main_theme="", detailed_summary="")
        n = len(ideas)
        summary.relationships = [r for r in summary.relationships
                                 if 1 <= r.source <= n and 1 <= r.target <= n and r.source != r.target]
        return summary


def load_segments(session: Session, transcript: Transcript) -> list[dict[str, Any]]:
    return [
        {"seg_key": s.seg_key, "start": s.start, "end": s.end, "text": s.text}
        for s in transcript.segments
    ]


def persist_analysis(session: Session, video: Video, transcript: Transcript, out: ExtractionOutput) -> VideoAnalysis:
    """Atomically replace the video's current analysis. User annotations are re-linked, never deleted."""
    old_ideas = session.execute(select(Idea).where(Idea.video_id == video.id)).scalars().all()
    old_by_id = {i.id: i for i in old_ideas}
    annotations = session.execute(select(IdeaAnnotation).where(IdeaAnnotation.video_id == video.id)).scalars().all()
    for a in annotations:
        if a.idea_id in old_by_id:
            a.idea_title_snapshot = old_by_id[a.idea_id].title
            a.segment_keys_snapshot = list(old_by_id[a.idea_id].segment_keys or [])
        a.idea_id = None
    session.flush()
    session.execute(update(VideoAnalysis).where(VideoAnalysis.video_id == video.id).values(is_current=False))
    session.execute(delete(Idea).where(Idea.video_id == video.id))
    s = out.summary
    analysis = VideoAnalysis(
        video_id=video.id,
        transcript_id=transcript.id,
        is_current=True,
        status="completed",
        model=out.model,
        analysis_version=ANALYSIS_VERSION,
        prompt_versions=out.prompt_versions,
        main_theme=s.main_theme,
        central_thesis=s.central_thesis,
        summary=s.detailed_summary,
        topics=s.topics,
        takeaways=s.practical_takeaways,
        relationships=[r.model_dump() for r in s.relationships],
        validation=out.stats.as_dict(),
        chunk_count=out.chunk_count,
        raw_idea_count=out.stats.raw_ideas,
    )
    session.add(analysis)
    session.flush()
    new_ideas: list[Idea] = []
    for n, i in enumerate(out.ideas, 1):
        idea = Idea(
            video_id=video.id,
            channel_id=video.channel_id,
            analysis_id=analysis.id,
            transcript_id=transcript.id,
            ordinal=n,
            title=i.title[:500],
            explanation=i.explanation,
            idea_type=i.idea_type,
            topic=i.topic,
            keywords=i.keywords,
            keywords_text=" ".join(i.keywords),
            segment_keys=i.segment_keys,
            start_time=i.start_time,
            end_time=i.end_time,
            excerpts=i.excerpts,
            statement_kind=i.statement_kind,
            confidence=i.confidence,
            model=out.model,
            analysis_version=ANALYSIS_VERSION,
            video_type=video.video_type,
            upload_date=video.upload_date,
        )
        session.add(idea)
        new_ideas.append(idea)
    session.flush()
    # re-link annotations: exact title match first, then source overlap
    for a in annotations:
        title = normalize_for_match(a.idea_title_snapshot)
        best, best_score = None, 0.0
        for idea in new_ideas:
            if normalize_for_match(idea.title) == title:
                best, best_score = idea, 1.0
                break
            score = jaccard(set(a.segment_keys_snapshot or []), set(idea.segment_keys or []))
            if score > best_score:
                best, best_score = idea, score
        taken = {x.idea_id for x in annotations if x.idea_id}
        if best is not None and best_score >= 0.5 and best.id not in taken:
            a.idea_id = best.id
    video.idea_count = len(new_ideas)
    video.analysis_status = "completed"
    session.flush()
    return analysis
