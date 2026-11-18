from datetime import timedelta

from fakes import CH_ID

from app.core.errors import DeferredError, PermanentError, TransientError
from app.jobs import queue as Q
from app.models import Channel, Job
from app.utils.time import utcnow


def _channel(db, paused=False):
    c = Channel(id=CH_ID, name="A", url="u", paused=paused)
    db.add(c)
    db.commit()
    return c


def test_enqueue_is_idempotent(db):
    j1 = Q.enqueue(db, "fetch_transcript", video_id="v1")
    j2 = Q.enqueue(db, "fetch_transcript", video_id="v1", priority=5)
    db.commit()
    assert j1.id == j2.id and j2.priority == 5
    assert db.query(Job).count() == 1
    # once completed, new work may be queued
    Q.mark_completed(db, j1)
    db.commit()
    j3 = Q.enqueue(db, "fetch_transcript", video_id="v1")
    db.commit()
    assert j3.id != j1.id


def test_claim_priority_and_lane(db):
    low = Q.enqueue(db, "fetch_transcript", video_id="a", priority=0)
    high = Q.enqueue(db, "fetch_transcript", video_id="b", priority=9)
    Q.enqueue(db, "analyze_video", video_id="c", priority=100)
    db.commit()
    assert Q.claim(db, "network", "w").id == high.id
    assert Q.claim(db, "network", "w").id == low.id
    assert Q.claim(db, "network", "w") is None
    assert Q.claim(db, "llm", "w").job_type == "analyze_video"


def test_paused_channel_jobs_not_claimed(db):
    c = _channel(db)
    j = Q.enqueue(db, "fetch_transcript", channel_id=c.id, video_id="a")
    db.commit()
    Q.set_channel_paused(db, c, True)
    db.commit()
    db.refresh(j)
    assert j.status == "paused"
    assert Q.claim(db, "network", "w") is None
    Q.set_channel_paused(db, c, False)
    db.commit()
    assert Q.claim(db, "network", "w").id == j.id


def test_failure_handling(db):
    j = Q.enqueue(db, "fetch_transcript", video_id="a", max_attempts=2)
    db.commit()
    Q.claim(db, "network", "w")
    db.refresh(j)
    assert Q.mark_failed(db, j, TransientError("net")) == "retry_scheduled"
    assert j.run_after > utcnow()
    j.run_after = utcnow() - timedelta(seconds=1)
    db.commit()
    Q.claim(db, "network", "w")
    db.refresh(j)
    assert Q.mark_failed(db, j, TransientError("net")) == "failed"  # attempts exhausted

    p = Q.enqueue(db, "fetch_transcript", video_id="b")
    db.commit()
    Q.claim(db, "network", "w")
    db.refresh(p)
    assert Q.mark_failed(db, p, PermanentError("gone")) == "failed"  # never retried


def test_deferral_does_not_consume_attempts(db):
    j = Q.enqueue(db, "analyze_video", video_id="a")
    db.commit()
    Q.claim(db, "llm", "w")
    db.refresh(j)
    assert Q.mark_failed(db, j, DeferredError("offline", delay_seconds=60)) == "retry_scheduled"
    assert j.attempts == 0 and j.error_kind == "deferred"


def test_recover_interrupted_keeps_checkpoint(db):
    j = Q.enqueue(db, "analyze_video", video_id="a")
    db.commit()
    Q.claim(db, "llm", "w")
    db.refresh(j)
    j.checkpoint = {"chunks": {"abc": {}}}
    db.commit()
    assert Q.recover_interrupted(db) == 1
    db.commit()
    db.refresh(j)
    assert j.status == "queued" and j.checkpoint == {"chunks": {"abc": {}}} and j.attempts == 0


def test_cancel_and_pause_running(db):
    j = Q.enqueue(db, "fetch_transcript", video_id="a")
    db.commit()
    Q.claim(db, "network", "w")
    db.refresh(j)
    Q.cancel_job(db, j)
    assert j.requested_action == "cancel" and j.status == "running"
    q = Q.enqueue(db, "fetch_transcript", video_id="b")
    Q.pause_job(db, q)
    assert q.status == "paused"
    Q.resume_job(db, q)
    assert q.status == "queued"


def test_retry_failed_skips_permanent_access_errors(db):
    j = Q.enqueue(db, "fetch_transcript", video_id="a")
    k = Q.enqueue(db, "fetch_transcript", video_id="b")
    db.commit()
    for job, kind in ((j, "private"), (k, "transient")):
        job.status, job.error_kind = "failed", kind
    db.commit()
    assert Q.retry_failed(db) == 1
    assert k.status == "queued" and j.status == "failed"
