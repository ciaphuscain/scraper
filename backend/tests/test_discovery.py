from fakes import CH_ID, vid

from app.models import Channel, Video
from app.services.youtube import discovery


def test_resolve_and_scan_dedupes_and_classifies(db, fake_yt):
    ch = discovery.resolve_channel(db, fake_yt, "https://www.youtube.com/@alpha/videos")
    assert ch.id == CH_ID and ch.name == "Alpha Finance" and ch.handle == "@alpha"
    stats = discovery.scan_channel(db, fake_yt, ch)
    assert db.query(Video).count() == 5  # vid(2) appears in both tabs but is stored once
    v2 = db.get(Video, vid(2))
    assert v2.video_type == "short" and set(v2.listing_sources) == {"videos", "shorts"}
    assert db.get(Video, vid(5)).video_type == "short"
    assert db.get(Video, vid(1)).video_type == "video"
    assert len(stats["new_video_ids"]) == 5
    # rescanning creates nothing new
    again = discovery.scan_channel(db, fake_yt, ch)
    assert again["new_video_ids"] == []
    assert db.query(Video).count() == 5


def test_scan_since_skips_older(db, fake_yt):
    ch = discovery.resolve_channel(db, fake_yt, "@alpha")
    discovery.scan_channel(db, fake_yt, ch, tabs=("videos",), since="20240115")
    ids = {v.id for v in db.query(Video)}
    assert ids == {vid(1), vid(2)}


def test_incremental_stops_after_known(db, fake_yt, monkeypatch):
    from app.utils.time import utcnow

    ch = discovery.resolve_channel(db, fake_yt, "@alpha")
    discovery.scan_channel(db, fake_yt, ch)
    ch.last_sync_at = utcnow()
    monkeypatch.setattr(discovery, "KNOWN_STOP_THRESHOLD", 2)
    fake_yt.tabs[(CH_ID, "videos")].insert(0, {"id": vid(99), "title": "New upload", "upload_date": "20240401"})
    stats = discovery.scan_channel(db, fake_yt, ch, tabs=("videos",))
    assert stats["new_video_ids"] == [vid(99)]
    assert stats["tabs"]["videos"]["stopped_early"]


def test_apply_video_info_preserves_listing_short(db, fake_yt):
    ch = discovery.resolve_channel(db, fake_yt, "@alpha")
    discovery.scan_channel(db, fake_yt, ch)
    v = db.get(Video, vid(5))
    discovery.apply_video_info(v, {"title": "T", "upload_date": "20240505", "duration": 30, "subtitles": {},
                                   "automatic_captions": {"en": []}})
    assert v.video_type == "short" and v.upload_date == "20240505" and not v.upload_date_approximate
