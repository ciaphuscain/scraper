"""Optional live tests against real YouTube / Ollama. Not run by default.

    YTCS_LIVE_CHANNEL=https://www.youtube.com/@SomeSmallChannel pytest -m live
"""
import os

import pytest

pytestmark = pytest.mark.live


@pytest.mark.skipif(not os.getenv("YTCS_LIVE_CHANNEL"), reason="set YTCS_LIVE_CHANNEL")
def test_live_channel_resolution_and_first_video(db):
    from app.services.transcripts.captions import parse_captions
    from app.services.transcripts.selection import choose_track
    from app.services.youtube.client import YtDlpClient
    from app.services.youtube.discovery import resolve_channel
    from app.services.youtube.urls import parse_channel_url

    client = YtDlpClient(request_delay=2)
    ch = resolve_channel(db, client, os.environ["YTCS_LIVE_CHANNEL"])
    assert ch.id.startswith("UC")
    entry = next(iter(client.iter_tab(parse_channel_url(ch.url), "videos")))
    info = client.video_info(entry["id"])
    track = choose_track(info, ["en"])
    if track:
        assert parse_captions(client.fetch_text(track.url), track.ext).segments


@pytest.mark.skipif(not os.getenv("YTCS_LIVE_OLLAMA"), reason="set YTCS_LIVE_OLLAMA=1 with Ollama running")
def test_live_ollama_structured_output():
    from app.core.settings_store import AppSettings
    from app.services.ai.llm import OllamaStructuredLLM
    from app.services.ai.ollama import client_from_settings
    from app.services.ai.schemas import ChunkExtraction

    st = AppSettings(ollama_model=os.getenv("YTCS_LIVE_MODEL", "qwen2.5:7b"))
    llm = OllamaStructuredLLM(client_from_settings(st), st)
    out = llm.generate('Extract ideas from: [S00000 | 0:00] Compound interest means you earn interest on interest. '
                       'Return {"ideas": [...]}', ChunkExtraction)
    assert isinstance(out.ideas, list)
