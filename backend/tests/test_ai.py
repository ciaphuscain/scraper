import pytest
from fakes import FakeLLM

from app.core.errors import InvalidAIOutputError
from app.core.settings_store import AppSettings
from app.services.ai import prompts as P
from app.services.ai.chunking import chunk_segments
from app.services.ai.dedupe import dedupe_ideas
from app.services.ai.extraction import ExtractionInput, IdeaExtractor
from app.services.ai.llm import OllamaStructuredLLM
from app.services.ai.ollama import parse_json_loose
from app.services.ai.schemas import ChunkExtraction, ChunkIdea
from app.services.ai.validation import SourcedIdea, ValidationStats, normalize_key, validate_idea


def segs(n=40):
    return [{"seg_key": f"S{i:05d}", "start": i * 5.0, "end": i * 5.0 + 5, "text": f"Sentence number {i} talks about topic {i % 4}."}
            for i in range(n)]


def test_chunking_preserves_segments_and_budget():
    s = segs(60)
    chunks = chunk_segments(s, max_tokens=200, overlap=1)
    assert len(chunks) > 3
    covered = [k for c in chunks for k in c.keys if k not in c.overlap_keys]
    assert covered == [x["seg_key"] for x in s]  # every segment exactly once outside overlap
    assert all(c.overlap_keys == c.keys[:1] for c in chunks[1:])
    assert "[S00000 | 0:00]" in chunks[0].text


def test_parse_json_loose():
    assert parse_json_loose('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_loose('Sure! {"a": [1,2]} hope that helps') == {"a": [1, 2]}
    with pytest.raises(InvalidAIOutputError):
        parse_json_loose("not json")


def test_schema_normalisation():
    i = ChunkIdea(title="T", explanation="E", idea_type="Technical Concept", statement_kind="explicit",
                  keywords="a, b", confidence=85)
    assert i.idea_type == "technical_concept" and i.statement_kind == "stated"
    assert i.keywords == ["a", "b"] and i.confidence == 0.85


def test_normalize_key():
    assert normalize_key("S12") == "S00012"
    assert normalize_key("[S00012]") == "S00012"
    assert normalize_key("12") == "S00012"
    assert normalize_key("xyz") is None


def test_validation_drops_unsourced_and_repairs_excerpts():
    s = segs(5)
    st = ValidationStats()
    good = validate_idea(ChunkIdea(title="t", explanation="e", segment_ids=["S1"], excerpts=["number 1 talks"]), s, 0, st)
    assert good.segment_keys == ["S00001"] and good.excerpts[0]["verified"] and good.start_time == 5.0
    fabricated = validate_idea(ChunkIdea(title="t", explanation="e", segment_ids=["S77"], excerpts=["made up"]), s, 0, st)
    assert fabricated is None and st.dropped_unsourced == 1
    bad_excerpt = validate_idea(ChunkIdea(title="t", explanation="e", segment_ids=["S2"], excerpts=["invented quote"]), s, 0, st)
    assert bad_excerpt.excerpts[0]["text"] == s[2]["text"] and st.excerpts_replaced == 1
    recovered = validate_idea(ChunkIdea(title="t", explanation="e", segment_ids=[], excerpts=["number 3 talks about"]), s, 0, st)
    assert recovered.segment_keys == ["S00003"]


def _idea(title, keys, chunk, expl="x"):
    return SourcedIdea(title=title, explanation=expl, idea_type="main_idea", topic="T", keywords=[], segment_keys=keys,
                       excerpts=[{"text": title, "segment_key": keys[0], "start": 0, "verified": True}],
                       statement_kind="stated", confidence=0.5, chunk_index=chunk, start_time=0, end_time=1)


def test_dedupe_merges_and_preserves_sources():
    ideas = [_idea("Compound interest grows savings", ["S00001"], 0, "short"),
             _idea("Compound interest grows savings", ["S00009"], 1, "a much longer explanation"),
             _idea("Inflation erodes value", ["S00004"], 1)]
    st = ValidationStats()
    out = dedupe_ideas(ideas, st)
    assert len(out) == 2 and st.merged == 1
    merged = [i for i in out if i.title.startswith("Compound")][0]
    assert merged.segment_keys == ["S00001", "S00009"]
    assert merged.explanation == "a much longer explanation"


def test_dedupe_borderline_requires_confirmation():
    a = _idea("Saving money early matters a lot", ["S00001"], 0)
    b = _idea("Saving money early is important", ["S00002"], 1)
    assert len(dedupe_ideas([a, b], ValidationStats(), None)) == 2
    a2 = _idea("Saving money early matters a lot", ["S00001"], 0)
    b2 = _idea("Saving money early is important", ["S00002"], 1)
    assert len(dedupe_ideas([a2, b2], ValidationStats(), lambda x, y: True)) == 1


def test_extractor_end_to_end_with_fake_llm():
    llm = FakeLLM()
    ex = IdeaExtractor(llm, dict(P.DEFAULT_PROMPTS), {k: 1 for k in P.DEFAULT_PROMPTS}, chunk_tokens=200)
    inp = ExtractionInput("v", "c", "Video", "Chan", 1, segs(30))
    cp = {}
    out = ex.run(inp, checkpoint=cp)
    assert out.chunk_count > 1
    assert out.stats.dropped_unsourced == out.chunk_count  # one hallucination per chunk
    assert out.ideas and all(i.segment_keys for i in out.ideas)
    assert len(out.summary.relationships) == 1  # invalid index removed
    # resuming from checkpoint makes no new chunk calls
    calls_before = llm.calls.count("ChunkExtraction")
    ex.run(inp, checkpoint=cp)
    assert llm.calls.count("ChunkExtraction") == calls_before


class _BadThenGood:
    def __init__(self):
        self.n = 0

    def chat(self, *a, **k):
        self.n += 1
        return "oops not json" if self.n == 1 else '{"ideas": []}'


class _AlwaysBad:
    def chat(self, *a, **k):
        return '{"ideas": [{"title": 5}]}'


def test_llm_retry_on_invalid_json():
    st = AppSettings(llm_retries=3)
    llm = OllamaStructuredLLM(_BadThenGood(), st)
    assert llm.generate("p", ChunkExtraction).ideas == []
    assert llm.stats.invalid_responses == 1
    with pytest.raises(InvalidAIOutputError):
        OllamaStructuredLLM(_AlwaysBad(), st).generate("p", ChunkExtraction)


def test_ollama_client_offline_is_deferred():
    import httpx

    from app.core.errors import DeferredError
    from app.services.ai.ollama import OllamaClient

    def handler(request):
        raise httpx.ConnectError("refused")

    c = OllamaClient("http://127.0.0.1:9", transport=httpx.MockTransport(handler))
    assert c.is_available() is False
    with pytest.raises(DeferredError):
        c.chat("m", [{"role": "user", "content": "x"}])


def test_ollama_client_structured_output():
    import json

    import httpx

    from app.services.ai.ollama import OllamaClient

    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": '{"ideas": []}'}})

    c = OllamaClient("http://x", transport=httpx.MockTransport(handler))
    assert c.chat("m", [], schema={"type": "object"}, num_ctx=4096) == '{"ideas": []}'
    assert seen["body"]["format"] == {"type": "object"} and seen["body"]["options"]["num_ctx"] == 4096
