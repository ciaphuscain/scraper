"""Pydantic schemas for structured LLM output. Validation is strict on shape,
lenient on harmless variations (e.g. enum casing, a string instead of a list)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

IDEA_TYPES = [
    "central_thesis", "main_idea", "supporting_idea", "subtopic", "explanation", "argument", "factual_claim",
    "example", "analogy", "question", "observation", "conclusion", "recommendation", "technique",
    "practical_takeaway", "named_entity", "technical_concept", "unusual_fact", "comparison",
    "contradiction", "qualification",
]
STATEMENT_KINDS = ["stated", "interpretation", "creator_claim"]


def _norm_enum(v: Any, allowed: list[str], default: str) -> str:
    s = str(v or "").strip().lower().replace(" ", "_").replace("-", "_")
    if s in allowed:
        return s
    aliases = {"thesis": "central_thesis", "claim": "factual_claim", "fact": "factual_claim",
               "takeaway": "practical_takeaway", "concept": "technical_concept", "entity": "named_entity",
               "tip": "recommendation", "method": "technique", "idea": "main_idea",
               "direct": "stated", "explicit": "stated", "inferred": "interpretation", "claim_by_creator": "creator_claim"}
    return aliases.get(s, default)


class ChunkIdea(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    explanation: str = Field(min_length=1)
    idea_type: str = "main_idea"
    topic: str = ""
    keywords: list[str] = Field(default_factory=list)
    segment_ids: list[str] = Field(default_factory=list)
    excerpts: list[str] = Field(default_factory=list)
    statement_kind: str = "stated"
    confidence: float | None = None

    @field_validator("idea_type", mode="before")
    @classmethod
    def _t(cls, v: Any) -> str:
        return _norm_enum(v, IDEA_TYPES, "main_idea")

    @field_validator("statement_kind", mode="before")
    @classmethod
    def _k(cls, v: Any) -> str:
        return _norm_enum(v, STATEMENT_KINDS, "stated")

    @field_validator("keywords", "segment_ids", "excerpts", mode="before")
    @classmethod
    def _list(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            return [x.strip() for x in v.split(",") if x.strip()] if v else []
        return [str(x).strip() for x in v if str(x).strip()]

    @field_validator("confidence", mode="before")
    @classmethod
    def _c(cls, v: Any) -> float | None:
        if v is None or v == "":
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        if f > 1:
            f = f / 100 if f <= 100 else 1.0
        return max(0.0, min(1.0, f))


class ChunkExtraction(BaseModel):
    ideas: list[ChunkIdea] = Field(default_factory=list)


class DedupeDecision(BaseModel):
    same: bool
    reason: str = ""


class Relationship(BaseModel):
    source: int
    target: int
    relation: str


class VideoSummary(BaseModel):
    main_theme: str = ""
    central_thesis: str = ""
    detailed_summary: str = ""
    topics: list[str] = Field(default_factory=list)
    practical_takeaways: list[str] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)


class TopicMap(BaseModel):
    mapping: dict[str, str] = Field(default_factory=dict)


class CitedStatement(BaseModel):
    statement: str
    idea_ids: list[int] = Field(default_factory=list)


class ChannelNarrative(BaseModel):
    overview: str = ""
    recurring_themes: list[CitedStatement] = Field(default_factory=list)
    notable_insights: list[CitedStatement] = Field(default_factory=list)
    evolution: list[CitedStatement] = Field(default_factory=list)


class PairJudgement(BaseModel):
    relation: Literal["same", "similar", "different_perspective", "contradictory", "unrelated"]
    explanation: str = ""


def json_schema(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema()
