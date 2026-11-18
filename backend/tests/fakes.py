"""Deterministic fakes for YouTube, Whisper and the LLM."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterator

from app.core.errors import VideoUnavailableError
from app.services.ai.schemas import (
    ChannelNarrative,
    ChunkExtraction,
    DedupeDecision,
    PairJudgement,
    TopicMap,
    VideoSummary,
)
from app.services.transcription.whisper import WhisperResult
from app.services.transcripts.captions import Segment
from app.services.youtube.urls import ChannelRef

FIX = Path(__file__).parent / "fixtures"
CH_ID = "UC" + "a" * 22
CH2_ID = "UC" + "b" * 22


def vid(n: int) -> str:
    return f"vid{n:08d}"


class FakeYouTube:
    def __init__(self):
        self.channels = {
            "@alpha": {"channel_id": CH_ID, "channel": "Alpha Finance", "uploader_id": "@alpha",
                       "channel_url": f"https://www.youtube.com/channel/{CH_ID}", "description": "Money talk",
                       "thumbnails": [{"url": "https://img/a.jpg", "width": 100, "height": 100}]},
            "@beta": {"channel_id": CH2_ID, "channel": "Beta Science", "uploader_id": "@beta",
                      "channel_url": f"https://www.youtube.com/channel/{CH2_ID}", "description": "Science"},
        }
        self.tabs: dict[tuple[str, str], list[dict[str, Any]]] = {
            (CH_ID, "videos"): [
                {"id": vid(1), "title": "Compound interest explained", "duration": 600, "upload_date": "20240301"},
                {"id": vid(2), "title": "Neural nets", "duration": 300, "upload_date": "20240201"},
                {"id": vid(3), "title": "No captions video", "duration": 120, "upload_date": "20240101"},
                {"id": vid(4), "title": "Private one", "duration": 100, "upload_date": "20231201"},
            ],
            (CH_ID, "shorts"): [
                {"id": vid(5), "title": "Short tip", "duration": 40, "url": f"https://www.youtube.com/shorts/{vid(5)}"},
                {"id": vid(2), "title": "Neural nets", "duration": 300},  # overlaps /videos listing
            ],
            (CH2_ID, "videos"): [
                {"id": vid(10), "title": "Saving money science", "duration": 600, "upload_date": "20240305"},
            ],
            (CH2_ID, "shorts"): [],
        }
        self.calls: list[str] = []
        manual = (FIX / "manual_en.vtt").read_text()
        rolling = (FIX / "rolling_auto.vtt").read_text()
        self.texts = {"https://subs/manual": manual, "https://subs/auto": rolling, "https://subs/manual10": manual}
        self.audio_downloads = 0

    def _ch(self, ref: ChannelRef) -> dict[str, Any]:
        if ref.kind == "handle":
            return self.channels[ref.value]
        for c in self.channels.values():
            if c["channel_id"] == ref.value:
                return c
        raise VideoUnavailableError("channel does not exist")

    def resolve_channel(self, ref: ChannelRef) -> dict[str, Any]:
        self.calls.append(f"resolve:{ref.value}")
        return dict(self._ch(ref))

    def iter_tab(self, ref: ChannelRef, tab: str) -> Iterator[dict[str, Any]]:
        self.calls.append(f"tab:{ref.value}:{tab}")
        cid = self._ch(ref)["channel_id"]
        yield from [dict(e) for e in self.tabs.get((cid, tab), [])]

    def video_info(self, video_id: str) -> dict[str, Any]:
        self.calls.append(f"info:{video_id}")
        base = {"id": video_id, "title": f"Title {video_id}", "description": "desc", "duration": 30,
                "upload_date": "20240301", "language": "en", "subtitles": {}, "automatic_captions": {}}
        if video_id == vid(1):
            base.update(title="Compound interest explained", duration=40,
                        subtitles={"en": [{"ext": "json3", "url": "https://subs/x"}, {"ext": "vtt", "url": "https://subs/manual"}]},
                        automatic_captions={"en-orig": [{"ext": "vtt", "url": "https://subs/auto"}]})
        elif video_id == vid(2):
            base.update(title="Neural nets", duration=9,
                        automatic_captions={"en-orig": [{"ext": "vtt", "url": "https://subs/auto"}],
                                            "fr": [{"ext": "vtt", "url": "https://subs/translated"}]})
        elif video_id == vid(4):
            raise VideoUnavailableError("Private video", user_message="The video is private.")
        elif video_id == vid(10):
            base.update(title="Saving money science", duration=40,
                        subtitles={"en": [{"ext": "vtt", "url": "https://subs/manual10"}]})
        return base

    def fetch_text(self, url: str) -> str:
        self.calls.append(f"fetch:{url}")
        return self.texts[url]

    def download_audio(self, video_id: str, dest_dir: Path) -> Path:
        self.audio_downloads += 1
        dest_dir.mkdir(parents=True, exist_ok=True)
        p = dest_dir / f"{video_id}.m4a"
        p.write_bytes(b"fake audio")
        return p


class FakeWhisper:
    def __init__(self):
        self.calls = 0

    def transcribe(self, path, settings, progress=None):
        self.calls += 1
        if progress:
            progress(0.5)
            progress(1.0)
        segs = [Segment(0.0, 3.0, "This video has no captions.", 0.9),
                Segment(3.0, 7.5, "Whisper transcribed the spoken audio locally.", 0.8)]
        return WhisperResult(segs, "en", 0.99, 7.5, True, settings.whisper_model, {"model": settings.whisper_model})


LINE = re.compile(r"^\[(S\d{5}) \| [^\]]+\] (.*)$", re.M)


class FakeLLM:
    """Produces one idea per segment that contains >= 5 words, quoting it verbatim."""

    model_name = "fake-llm"

    def __init__(self, bad_first: bool = False):
        self.calls: list[str] = []

    def generate(self, prompt: str, schema):
        self.calls.append(schema.__name__)
        if schema is ChunkExtraction:
            ideas = []
            for key, text in LINE.findall(prompt.split("TRANSCRIPT EXCERPT:")[-1]):
                words = text.split()
                if len(words) < 5:
                    continue
                ideas.append({"title": " ".join(words[:6]), "explanation": f"The speaker says: {text}",
                              "idea_type": "main_idea", "topic": "Personal Finance" if "interest" in text.lower() else "Learning",
                              "keywords": [w.strip(".,").lower() for w in words[:3]], "segment_ids": [key],
                              "excerpts": [" ".join(words[:5])], "statement_kind": "stated", "confidence": 0.8})
            # a hallucinated idea with no valid source must be dropped
            ideas.append({"title": "Invented idea", "explanation": "not in transcript", "segment_ids": ["S99999"],
                          "excerpts": ["this text does not exist anywhere"]})
            return ChunkExtraction.model_validate({"ideas": ideas})
        if schema is DedupeDecision:
            return DedupeDecision(same=False, reason="distinct")
        if schema is TopicMap:
            return TopicMap(mapping={})
        if schema is VideoSummary:
            return VideoSummary(main_theme="Fake theme", central_thesis="Fake thesis", detailed_summary="Fake summary.",
                                topics=["Personal Finance"], practical_takeaways=["Start early"],
                                relationships=[{"source": 1, "target": 2, "relation": "supports"},
                                               {"source": 1, "target": 999, "relation": "invalid"}])
        if schema is ChannelNarrative:
            return ChannelNarrative(overview="Overview", recurring_themes=[{"statement": "Uncited", "idea_ids": [123456]}])
        if schema is PairJudgement:
            return PairJudgement(relation="similar", explanation="both about saving")
        raise AssertionError(schema)
