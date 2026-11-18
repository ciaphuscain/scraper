from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _date(v: str | None) -> str | None:
    if not v:
        return None
    d = v.replace("-", "")
    if len(d) != 8 or not d.isdigit():
        raise ValueError("date must be YYYY-MM-DD")
    return d


class ChannelCreate(BaseModel):
    url: str = Field(min_length=3, max_length=1024)
    scan_since: str | None = None
    priority: int = 0
    auto_process: bool = True

    @field_validator("scan_since")
    @classmethod
    def _d(cls, v: str | None) -> str | None:
        return _date(v)


class ChannelsBulkCreate(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=1000)
    scan_since: str | None = None
    auto_process: bool = True

    @field_validator("scan_since")
    @classmethod
    def _d(cls, v: str | None) -> str | None:
        return _date(v)


class ChannelUpdate(BaseModel):
    priority: int | None = None
    scan_since: str | None = None
    auto_process: bool | None = None
    clear_scan_since: bool = False

    @field_validator("scan_since")
    @classmethod
    def _d(cls, v: str | None) -> str | None:
        return _date(v)


class ScanRequest(BaseModel):
    full: bool = False
    since: str | None = None

    @field_validator("since")
    @classmethod
    def _d(cls, v: str | None) -> str | None:
        return _date(v)


class VideoCreate(BaseModel):
    url: str


class BatchAction(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=5000)
    action: Literal["process", "analyze", "reprocess", "select", "deselect", "retry", "priority"]
    priority: int | None = None


class AnnotationUpdate(BaseModel):
    note: str | None = Field(None, max_length=20000)
    tags: list[str] | None = None
    bookmarked: bool | None = None

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        out = []
        for t in v:
            t = t.strip()[:64]
            if t and t.lower() not in {x.lower() for x in out}:
                out.append(t)
        return out


class PriorityUpdate(BaseModel):
    priority: int = Field(ge=-100, le=100)


class PromptUpdate(BaseModel):
    body: str = Field(min_length=10, max_length=50000)


class CrossChannelRequest(BaseModel):
    channel_ids: list[str] = Field(min_length=2, max_length=50)
    validate_semantics: bool = True
    max_pairs: int = Field(40, ge=1, le=300)


class ExportRequest(BaseModel):
    scope: Literal["video", "videos", "channel", "channels", "all"]
    ids: list[str] = Field(default_factory=list)
    content: list[Literal["metadata", "transcripts", "ideas", "summaries"]] = Field(
        default_factory=lambda: ["metadata", "transcripts", "ideas", "summaries"])
    format: Literal["txt", "md", "json", "jsonl", "csv", "zip", "sqlite"] = "zip"


class OllamaTest(BaseModel):
    url: str | None = None
    model: str | None = None
