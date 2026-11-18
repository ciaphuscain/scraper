"""Editable, versioned prompt templates.

Templates use ``{{name}}`` placeholders. Every analysis records the prompt
versions it used so results can be traced back.
"""
from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import PromptTemplate

DEFAULT_PROMPTS: dict[str, str] = {
    "chunk_extraction": """You are a meticulous research assistant extracting ideas from a video transcript.
The transcript excerpt below is part {{chunk_index}} of {{chunk_count}} from the video "{{video_title}}" by {{channel_name}}.
Each line starts with a segment id and timestamp, e.g. [S00012 | 1:23].

Extract EVERY meaningful, distinct idea supported by this excerpt. Do not summarise the excerpt into a few points
and do not stop at an arbitrary number: a dense excerpt may contain many ideas, a sparse one may contain one or none.
Do not turn every sentence into an idea: group statements that form one coherent concept.

Consider: central thesis, main and supporting ideas, subtopics, explanations, arguments, factual claims, examples,
analogies, questions, observations, conclusions, recommendations, techniques, practical takeaways, named entities,
technical concepts, unusual facts, comparisons, contradictions and qualifications.

Rules:
- Use ONLY information in the excerpt. Never invent content, never add outside knowledge.
- segment_ids must be ids that appear in the excerpt and directly support the idea.
- excerpts must be short VERBATIM quotes copied from those segments.
- statement_kind: "stated" if the speaker says it directly, "creator_claim" if it is a factual claim made by the
  speaker (not verified), "interpretation" if it is your reasonable reading of what was said.
- idea_type must be one of: {{idea_types}}.
- topic: a short general category (2-4 words). keywords: 2-8 specific terms.
- confidence: 0..1, how clearly the excerpt supports the idea.
- Ignore filler, sponsor reads and channel housekeeping unless they contain substantive ideas.

Return JSON: {"ideas": [{"title", "explanation", "idea_type", "topic", "keywords", "segment_ids", "excerpts",
"statement_kind", "confidence"}]}. Return {"ideas": []} if the excerpt contains no substantive idea.

TRANSCRIPT EXCERPT:
{{chunk_text}}
""",
    "video_summary": """You are analysing the video "{{video_title}}" by {{channel_name}}.
Below are ALL ideas extracted from its transcript, numbered. Using only these ideas (no outside knowledge):

1. main_theme: one sentence.
2. central_thesis: the core argument or message, or "" if there is none.
3. detailed_summary: a thorough multi-paragraph summary that preserves important details, examples and nuances.
4. topics: the topic categories covered.
5. practical_takeaways: actionable takeaways explicitly supported by the ideas (may be empty).
6. relationships: links between ideas using their numbers, e.g. {"source": 3, "target": 7,
   "relation": "example_of" | "supports" | "contradicts" | "qualifies" | "leads_to" | "part_of" | "compares_with"}.

Return JSON with keys main_theme, central_thesis, detailed_summary, topics, practical_takeaways, relationships.

IDEAS:
{{ideas_text}}
""",
    "dedupe": """Two ideas were extracted from different parts of the same video transcript.
Decide whether they express the SAME idea (semantically equivalent, so they should be merged into one) or are
distinct ideas (even if related). Only answer same=true if merging would lose no meaning.

IDEA A: {{idea_a}}
IDEA B: {{idea_b}}

Return JSON: {"same": true|false, "reason": "..."}
""",
    "topic_classification": """Normalise these topic labels from one video into a small set of consistent,
general categories (2-4 words each). Merge labels that mean the same thing. Keep distinct subjects separate.

LABELS:
{{topics}}

Return JSON: {"mapping": {"original label": "canonical category", ...}} covering every label.
""",
    "channel_analysis": """You are writing a research overview of the YouTube channel "{{channel_name}}"
based solely on aggregated, source-linked data extracted from its transcripts. Do not speculate about the
creator's private intentions or beliefs. Every statement must cite the idea ids (numbers in brackets) that
support it; statements without support must be omitted.

DATA:
{{report_data}}

Return JSON: {"overview": "...", "recurring_themes": [{"statement": "...", "idea_ids": [..]}],
"notable_insights": [...], "evolution": [...]}
""",
    "cross_channel": """Compare two ideas from different YouTube creators. Judge their relationship by MEANING,
not by shared words.

IDEA 1 ({{channel_a}}): {{idea_a}}
IDEA 2 ({{channel_b}}): {{idea_b}}

relation must be one of: "same" (equivalent claim), "similar" (overlapping idea), "different_perspective"
(same subject, different angle), "contradictory" (incompatible claims), "unrelated".
Return JSON: {"relation": "...", "explanation": "..."}
""",
}

PROMPT_DESCRIPTIONS = {
    "chunk_extraction": "Extract all distinct ideas from one transcript chunk.",
    "video_summary": "Video-level theme, summary, takeaways and idea relationships.",
    "dedupe": "Confirm whether two cross-chunk ideas should be merged.",
    "topic_classification": "Normalise topic labels within a video.",
    "channel_analysis": "Narrative channel report with idea citations.",
    "cross_channel": "Semantic comparison of two ideas from different channels.",
}


def render(template: str, **values: object) -> str:
    out = template
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", str(v))
    return out


def ensure_default_prompts(session: Session) -> None:
    for key, body in DEFAULT_PROMPTS.items():
        exists = session.execute(select(PromptTemplate.id).where(PromptTemplate.key == key)).first()
        if not exists:
            session.add(PromptTemplate(key=key, version=1, body=body, is_active=True, is_default=True))
    session.flush()


def get_active(session: Session, key: str) -> PromptTemplate:
    p = session.execute(
        select(PromptTemplate).where(PromptTemplate.key == key, PromptTemplate.is_active.is_(True))
        .order_by(PromptTemplate.version.desc())
    ).scalars().first()
    if p is None:
        ensure_default_prompts(session)
        p = session.execute(
            select(PromptTemplate).where(PromptTemplate.key == key).order_by(PromptTemplate.version.desc())
        ).scalars().first()
    assert p is not None, key
    return p


def save_new_version(session: Session, key: str, body: str, *, is_default: bool = False) -> PromptTemplate:
    if key not in DEFAULT_PROMPTS:
        raise ValueError(f"unknown prompt key {key}")
    if not body.strip():
        raise ValueError("prompt body cannot be empty")
    required = {"chunk_extraction": ["{{chunk_text}}"], "video_summary": ["{{ideas_text}}"],
                "dedupe": ["{{idea_a}}", "{{idea_b}}"], "topic_classification": ["{{topics}}"],
                "channel_analysis": ["{{report_data}}"], "cross_channel": ["{{idea_a}}", "{{idea_b}}"]}[key]
    missing = [r for r in required if r not in body]
    if missing:
        raise ValueError(f"prompt must contain placeholder(s): {', '.join(missing)}")
    latest = session.execute(select(func.max(PromptTemplate.version)).where(PromptTemplate.key == key)).scalar() or 0
    session.execute(update(PromptTemplate).where(PromptTemplate.key == key).values(is_active=False))
    p = PromptTemplate(key=key, version=latest + 1, body=body, is_active=True, is_default=is_default)
    session.add(p)
    session.flush()
    return p


def reset_to_default(session: Session, key: str) -> PromptTemplate:
    return save_new_version(session, key, DEFAULT_PROMPTS[key], is_default=True)
