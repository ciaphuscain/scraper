"""Deterministic end-to-end workflow through the HTTP API with fake YouTube/Whisper/LLM."""
import json
import zipfile
from pathlib import Path

from fakes import CH2_ID, CH_ID, vid
from fastapi.testclient import TestClient


def make_client():
    from app.main import create_app

    return TestClient(create_app(init=False))


def test_full_workflow(archive, fake_yt, fake_whisper, fake_llm, no_delay, drain):
    c = make_client()
    # 1-3: add a channel and discover
    r = c.post("/api/channels", json={"url": "https://www.youtube.com/@alpha"})
    assert r.status_code == 202, r.text
    # adding the same URL twice does not duplicate work
    assert c.post("/api/channels", json={"url": "https://www.youtube.com/@alpha"}).json()["job_id"] == r.json()["job_id"]
    results = drain()
    statuses = {(t, s) for _, t, s in results}
    assert ("discover_channel", "completed") in statuses

    chans = c.get("/api/channels").json()["channels"]
    assert len(chans) == 1 and chans[0]["id"] == CH_ID
    ch = chans[0]
    assert ch["videos"] == 3 and ch["shorts"] == 2  # vid(2) counted once, as a Short

    videos = {v["id"]: v for v in c.get("/api/videos", params={"channel_id": CH_ID, "page_size": 100}).json()["videos"]}
    assert len(videos) == 5
    # manual captions -> transcript + ideas
    assert videos[vid(1)]["transcript_status"] == "completed"
    assert videos[vid(1)]["analysis_status"] == "completed" and videos[vid(1)]["idea_count"] > 0
    # private video: unavailable, never retried automatically
    assert videos[vid(4)]["transcript_status"] == "unavailable"
    # no captions -> whisper fallback
    assert videos[vid(3)]["transcript_status"] == "completed"
    assert fake_whisper.calls >= 1 and fake_yt.audio_downloads >= 1
    # auto (rolling) captions, translated track ignored
    assert "fetch:https://subs/translated" not in fake_yt.calls

    # 5-6: transcript with timestamps
    t = c.get(f"/api/videos/{vid(1)}/transcript").json()
    assert t["method"] == "manual_captions" and t["completeness"] == "complete"
    assert t["segments"][0]["id"] == "S00000" and "&t=0s" in t["segments"][0]["url"]
    t3 = c.get(f"/api/videos/{vid(3)}/transcript").json()
    assert t3["method"] == "whisper" and t3["segments"][1]["confidence"] == 0.8
    # temporary audio removed after success
    assert not list((archive / "_work").rglob("*.m4a"))

    # 7-8: ideas are source-linked
    ideas = c.get(f"/api/videos/{vid(1)}/ideas").json()["ideas"]
    assert ideas and all(i["segment_ids"] for i in ideas)
    assert not any(i["title"] == "Invented idea" for i in ideas)
    seg_by_key = {s["id"]: s for s in t["segments"]}
    for i in ideas:
        assert i["start_time"] == seg_by_key[i["segment_ids"][0]]["start"]
        for ex in i["excerpts"]:
            assert ex["segment_key"] in seg_by_key

    # 9-10: search -> open supporting segment
    res = c.get("/api/search", params={"q": "compound interest"}).json()
    kinds = {r["kind"] for r in res["results"]}
    assert {"ideas", "segments", "videos"} <= kinds
    idea_hit = next(r for r in res["results"] if r["kind"] == "ideas")
    detail = c.get(f"/api/ideas/{idea_hit['idea_id']}").json()
    assert detail["source_segments"] and detail["source_segments"][0]["url"].startswith("https://www.youtube.com/watch?v=")
    assert c.get("/api/ideas", params={"q": "interest", "sort": "relevance"}).json()["total"] >= 1
    assert c.get(f"/api/videos/{vid(1)}/transcript/search", params={"q": "inflation"}).json()["matches"]

    # annotations survive re-analysis
    iid = ideas[0]["id"]
    c.put(f"/api/ideas/{iid}/annotation", json={"note": "my note", "tags": ["finance"], "bookmarked": True})
    c.post(f"/api/videos/{vid(1)}/analyze")
    drain()
    ideas2 = c.get(f"/api/videos/{vid(1)}/ideas").json()["ideas"]
    ann = [i for i in ideas2 if i["annotation"]]
    assert len(ann) == 1 and ann[0]["annotation"]["note"] == "my note" and ann[0]["title"] == ideas[0]["title"]
    assert c.get("/api/ideas", params={"bookmarked": True}).json()["total"] == 1
    assert c.get("/api/ideas", params={"tag": "finance"}).json()["total"] == 1

    # archive files written per video
    vdir = archive / "channels" / CH_ID / "videos" / vid(1)
    for f in ("metadata.json", "transcript.txt", "transcript_timestamped.json", "transcript.vtt",
              "transcript_metadata.json", "ideas.json", "summary.md"):
        assert (vdir / f).exists(), f
    assert (archive / "channels" / CH_ID / "shorts" / vid(2) / "transcript.txt").exists()
    meta = json.loads((vdir / "transcript_metadata.json").read_text())
    assert meta["source_url"].endswith(vid(1))

    # 11: export the video record + channel zip
    e = c.post("/api/exports", json={"scope": "video", "ids": [vid(1)], "format": "json"}).json()
    e2 = c.post("/api/exports", json={"scope": "channel", "ids": [CH_ID], "format": "zip"}).json()
    e3 = c.post("/api/exports", json={"scope": "all", "format": "csv", "content": ["ideas"]}).json()
    e4 = c.post("/api/exports", json={"scope": "all", "format": "sqlite"}).json()
    drain()
    for ex in (e, e2, e3, e4):
        info = c.get(f"/api/exports/{ex['id']}").json()
        assert info["status"] == "completed", info
        assert c.get(f"/api/exports/{ex['id']}/download").status_code == 200
    data = json.loads(c.get(f"/api/exports/{e['id']}/download").content)
    assert data["records"][0]["video_id"] == vid(1) and data["records"][0]["ideas"]
    zpath = Path(archive / "exports")
    zf = zipfile.ZipFile(next(zpath.glob("*.zip")))
    names = zf.namelist()
    assert f"YouTube_Content_Archive/channels/{CH_ID}/ideas_catalog.csv" in names
    assert f"YouTube_Content_Archive/channels/{CH_ID}/videos/{vid(1)}/transcript.txt" in names

    # channel report: uncited narrative statements are dropped
    c.post(f"/api/reports/channels/{CH_ID}")
    drain()
    rep = c.get(f"/api/reports/channels/{CH_ID}").json()["report"]
    assert rep["data"]["totals"]["ideas"] > 0
    assert rep["narrative"]["recurring_themes"] == [] and rep["narrative"]["dropped_uncited"] == 1

    # dashboard reflects real data
    d = c.get("/api/dashboard").json()
    assert d["channels"] == 1 and d["ideas"] > 0 and d["jobs"]["failed"] >= 1

    # 12-13: restart (fresh engine + app) keeps data
    from app.database import session as S

    S._engine.dispose()
    S._engine = None
    from app.database.init_db import init_db

    init_db()
    c2 = make_client()
    assert c2.get(f"/api/videos/{vid(1)}/ideas").json()["ideas"]
    assert c2.get("/api/channels").json()["channels"][0]["id"] == CH_ID


def test_incremental_rescan_only_processes_new(archive, fake_yt, fake_whisper, fake_llm, no_delay, drain):
    c = make_client()
    c.post("/api/channels", json={"url": "@beta"})
    drain()
    calls_before = [x for x in fake_yt.calls if x.startswith("info:")]
    fake_yt.tabs[(CH2_ID, "videos")].insert(0, {"id": vid(11), "title": "Brand new", "upload_date": "20240401"})
    c.post(f"/api/channels/{CH2_ID}/scan", json={})
    drain()
    new_calls = [x for x in fake_yt.calls if x.startswith("info:")][len(calls_before):]
    assert new_calls == [f"info:{vid(11)}"]


def test_ollama_offline_keeps_transcripts(archive, fake_yt, fake_whisper, no_delay, drain, monkeypatch):
    from app.services.ai import ollama

    monkeypatch.setattr(ollama.OllamaClient, "version", lambda self: None)
    c = make_client()
    c.post("/api/channels", json={"url": "@beta"})
    drain()
    v = c.get(f"/api/videos/{vid(10)}").json()
    assert v["transcript_status"] == "completed"
    jobs = c.get("/api/jobs", params={"job_type": "analyze_video"}).json()["jobs"]
    assert jobs and jobs[0]["status"] == "retry_scheduled" and jobs[0]["error_kind"] == "deferred"
    assert jobs[0]["attempts"] == 0


def test_pause_resume_channel_and_worker_recovery(archive, fake_yt, fake_whisper, fake_llm, no_delay, drain):
    c = make_client()
    c.post("/api/channels", json={"url": "@alpha", "auto_process": True})
    # run discovery only
    from app.database.session import session_scope
    from app.jobs.executor import execute
    from app.jobs.queue import claim, recover_interrupted

    with session_scope() as s:
        j = claim(s, "network", "t")
        jid = j.id
    execute(jid)
    assert c.post(f"/api/channels/{CH_ID}/pause").json()["jobs_affected"] > 0
    assert drain() == []  # nothing runs while paused
    c.post(f"/api/channels/{CH_ID}/resume")
    # simulate crash: claim a job, then "restart"
    with session_scope() as s:
        j = claim(s, "network", "t")
        crashed = j.id
    with session_scope() as s:
        assert recover_interrupted(s) == 1
    drain()
    assert c.get(f"/api/jobs/{crashed}").json()["status"] == "completed"


def test_settings_validation(archive):
    c = make_client()
    s = c.get("/api/settings").json()
    assert s["values"]["processing_concurrency"] == 1 and s["values"]["llm_concurrency"] == 1
    assert c.put("/api/settings", json={"download_concurrency": 99}).status_code == 422
    assert c.put("/api/settings", json={"chunk_tokens": 8000, "llm_context_size": 4096}).status_code == 422
    assert c.put("/api/settings", json={"nonsense": 1}).status_code == 400
    ok = c.put("/api/settings", json={"preferred_languages": ["en", "de"], "whisper_model": "base"})
    assert ok.status_code == 200 and ok.json()["values"]["whisper_model"] == "base"


def test_prompt_versioning(archive):
    c = make_client()
    p = {x["key"]: x for x in c.get("/api/prompts").json()["prompts"]}
    assert p["chunk_extraction"]["version"] == 1 and p["chunk_extraction"]["is_default"]
    assert c.put("/api/prompts/chunk_extraction", json={"body": "missing placeholder here"}).status_code == 400
    assert c.put("/api/prompts/chunk_extraction", json={"body": "Extract ideas: {{chunk_text}}"}).json()["version"] == 2
    assert c.post("/api/prompts/chunk_extraction/reset").json()["version"] == 3
    p = {x["key"]: x for x in c.get("/api/prompts").json()["prompts"]}
    assert p["chunk_extraction"]["is_default"]


def test_cross_channel(archive, fake_yt, fake_whisper, fake_llm, no_delay, drain):
    c = make_client()
    c.post("/api/channels", json={"url": "@alpha"})
    c.post("/api/channels", json={"url": "@beta"})
    drain()
    r = c.post("/api/reports/cross-channel", json={"channel_ids": [CH_ID, CH2_ID]})
    assert r.status_code == 202
    drain()
    lst = c.get("/api/reports/cross-channel").json()["reports"]
    rep = c.get(f"/api/reports/cross-channel/{lst[0]['id']}").json()
    assert rep["semantic_validation"] is True
    assert rep["data"]["shared_topics"]
    assert rep["data"]["similar_ideas"]
    pair = rep["data"]["similar_ideas"][0]
    assert pair["a"]["channel_id"] != pair["b"]["channel_id"] and "&t=" in pair["a"]["url"]


def test_add_single_video_and_batch(archive, fake_yt, fake_whisper, fake_llm, no_delay, drain):
    c = make_client()
    r = c.post("/api/videos", json={"url": f"https://www.youtube.com/shorts/{vid(1)}"}).json()
    assert r["created"]
    drain()
    v = c.get(f"/api/videos/{vid(1)}").json()
    assert v["video_type"] == "short" and v["transcript_status"] == "completed"
    assert c.post("/api/videos", json={"url": "https://example.com"}).status_code == 400
    assert c.post("/api/videos/batch", json={"ids": [vid(1)], "action": "deselect"}).json()["affected"] == 1
    for fmt in ("txt", "vtt", "json", "timestamped", "original"):
        assert c.get(f"/api/videos/{vid(1)}/transcript/download", params={"format": fmt}).status_code == 200
