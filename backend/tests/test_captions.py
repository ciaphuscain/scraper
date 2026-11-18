from fakes import FIX

from app.services.transcripts.captions import parse_captions, parse_timestamp, segments_to_vtt
from app.services.transcripts.selection import choose_track
from app.services.transcripts.store import assess_completeness


def test_timestamps():
    assert parse_timestamp("00:01:02.500") == 62.5
    assert parse_timestamp("01:02.5") == 62.5
    assert parse_timestamp("00:00:01,250") == 1.25
    assert parse_timestamp("00:01:bad") is None
    assert parse_timestamp("00:00:75.000") is None


def test_manual_vtt_entities_tags_and_invalid():
    r = parse_captions((FIX / "manual_en.vtt").read_text(), "vtt")
    texts = [s.text for s in r.segments]
    assert texts[0] == "Welcome back. Today we talk about compound interest & savings."
    assert r.skipped_cues == 1 and r.warnings
    assert not r.rolling_detected
    # genuinely repeated speech in separate cues is preserved
    assert texts.count("No. No.") == 2
    assert texts[-1].startswith("Inflation")
    assert all(s.end >= s.start for s in r.segments)


def test_rolling_auto_captions_collapsed():
    r = parse_captions((FIX / "rolling_auto.vtt").read_text(), "vtt")
    assert r.rolling_detected
    texts = [s.text for s in r.segments]
    assert texts == ["so today we learn", "about neural networks", "they learn from data", "using gradient descent"]
    full = " ".join(texts)
    assert full.count("neural networks") == 1
    starts = [s.start for s in r.segments]
    assert starts == sorted(starts)


def test_srt():
    r = parse_captions((FIX / "sample.srt").read_text())
    assert r.format == "srt"
    assert [s.text for s in r.segments] == ["Hello <world>", "This is SRT text.", "End before start is clamped."]
    assert r.segments[2].end == r.segments[2].start


def test_json3():
    import json

    data = {"events": [{"tStartMs": 0, "dDurationMs": 1000, "segs": [{"utf8": "hi "}, {"utf8": "there"}]},
                       {"tStartMs": 1000, "dDurationMs": 10, "aAppend": 1, "segs": [{"utf8": "\n"}]},
                       {"tStartMs": 1500, "dDurationMs": 500}]}
    r = parse_captions(json.dumps(data))
    assert [s.text for s in r.segments] == ["hi there"]


def test_vtt_roundtrip():
    r = parse_captions((FIX / "manual_en.vtt").read_text())
    vtt = segments_to_vtt(r.segments)
    again = parse_captions(vtt)
    assert [s.text for s in again.segments] == [s.text for s in r.segments]


def test_track_selection_priority():
    info = {"language": "en",
            "subtitles": {"en-GB": [{"ext": "vtt", "url": "m"}], "live_chat": [{"ext": "json", "url": "x"}]},
            "automatic_captions": {"en-orig": [{"ext": "vtt", "url": "a"}]}}
    c = choose_track(info, ["en"])
    assert c.method == "manual_captions" and c.url == "m"
    info["subtitles"] = {}
    c = choose_track(info, ["en"])
    assert c.method == "auto_captions" and c.language == "en"
    assert choose_track(info, ["en"], allow_auto=False) is None


def test_track_selection_never_uses_translations():
    info = {"language": "de", "subtitles": {}, "automatic_captions": {"en": [{"ext": "vtt", "url": "translated"}],
                                                                      "de-orig": [{"ext": "vtt", "url": "orig"}]}}
    c = choose_track(info, ["en"])
    assert c.url == "orig" and c.language == "de"


def test_completeness():
    from app.services.transcripts.captions import Segment

    segs = [Segment(0, 10, "a"), Segment(10, 50, "b")]
    assert assess_completeness(segs, 55, "manual_captions") == ("complete", 50 / 55)
    assert assess_completeness(segs, 600, "auto_captions")[0] == "partial"
    assert assess_completeness(segs, None, "auto_captions")[0] == "unknown"
    assert assess_completeness([], 100, "whisper")[0] == "partial"
