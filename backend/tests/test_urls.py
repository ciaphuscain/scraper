import pytest

from app.services.youtube.urls import InvalidYouTubeURL, parse_channel_url, parse_video_url, watch_url

CID = "UC" + "x" * 22


@pytest.mark.parametrize("url,kind,value,tab", [
    ("https://www.youtube.com/@handle", "handle", "@handle", None),
    ("youtube.com/@handle/videos", "handle", "@handle", "videos"),
    ("https://m.youtube.com/@some.handle-1/shorts?x=1", "handle", "@some.handle-1", "shorts"),
    ("@handle", "handle", "@handle", None),
    (f"https://youtube.com/channel/{CID}", "channel_id", CID, None),
    (f"https://www.youtube.com/channel/{CID}/videos", "channel_id", CID, "videos"),
    ("https://www.youtube.com/c/CustomName", "custom", "CustomName", None),
    ("https://www.youtube.com/user/legacyuser/videos", "user", "legacyuser", "videos"),
])
def test_parse_channel(url, kind, value, tab):
    ref = parse_channel_url(url)
    assert (ref.kind, ref.value, ref.tab) == (kind, value, tab)
    assert ref.base_url.startswith("https://www.youtube.com/")


@pytest.mark.parametrize("url", ["", "https://example.com/@x", "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                                 "https://www.youtube.com/channel/notanid", "https://youtu.be/dQw4w9WgXcQ"])
def test_parse_channel_invalid(url):
    with pytest.raises(InvalidYouTubeURL):
        parse_channel_url(url)


@pytest.mark.parametrize("url,vid,short", [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10", "dQw4w9WgXcQ", False),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ", False),
    ("https://www.youtube.com/shorts/abcdefghijk", "abcdefghijk", True),
    ("dQw4w9WgXcQ", "dQw4w9WgXcQ", False),
])
def test_parse_video(url, vid, short):
    ref = parse_video_url(url)
    assert ref.video_id == vid and ref.is_short_url is short


def test_watch_url_timestamp():
    assert watch_url("dQw4w9WgXcQ", 125.7) == "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=125s"
    assert watch_url("dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
