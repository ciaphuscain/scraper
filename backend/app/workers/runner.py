"""Background worker process.

Run with ``python -m app.workers.runner``. Only one instance may run per
database (file lock). Lanes run in threads; CPU-heavy Whisper and LLM jobs
share a "heavy" lock unless ``allow_parallel_heavy`` is enabled.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import threading
import time
from datetime import timedelta

from app.core.config import get_env
from app.core.logging import setup_logging
from app.core.settings_store import load_settings
from app.database.init_db import init_db
from app.database.session import session_scope, with_db_retry
from app.jobs.executor import execute
from app.jobs.queue import claim, recover_interrupted
from app.models import AppSetting, Job
from app.utils.lock import AlreadyRunning, InstanceLock
from app.utils.time import utcnow

log = logging.getLogger("worker")

LANE_MAX = {"network": 8, "cpu": 4, "llm": 4, "general": 1}
HEARTBEAT_KEY = "_worker_status"


class Worker:
    def __init__(self, poll_interval: float = 2.0):
        self.poll_interval = poll_interval
        self.stop = threading.Event()
        self.heavy_lock = threading.Lock()
        self.running: dict[int, str] = {}
        self.running_lock = threading.Lock()
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"
        self.threads: list[threading.Thread] = []
        self._settings = None
        self._settings_at = 0.0

    def settings(self):
        if time.monotonic() - self._settings_at > 5 or self._settings is None:
            with session_scope() as s:
                self._settings = load_settings(s)
            self._settings_at = time.monotonic()
        return self._settings

    def lane_limit(self, lane: str) -> int:
        st = self.settings()
        return {"network": st.download_concurrency, "cpu": st.processing_concurrency,
                "llm": st.llm_concurrency, "general": 1}[lane]

    def lane_loop(self, lane: str, index: int) -> None:
        name = f"{lane}-{index}"
        while not self.stop.is_set():
            try:
                st = self.settings()
                if st.queue_paused or index >= self.lane_limit(lane):
                    self.stop.wait(self.poll_interval * 2)
                    continue
                heavy = lane in ("cpu", "llm") and not st.allow_parallel_heavy
                if heavy and not self.heavy_lock.acquire(timeout=self.poll_interval):
                    continue
                try:
                    with session_scope() as s:
                        job = with_db_retry(lambda: claim(s, lane, f"{self.worker_id}/{name}"))
                        job_id = job.id if job else None
                        jtype = job.job_type if job else None
                    if job_id is None:
                        if heavy:
                            self.heavy_lock.release()
                            heavy = False
                        self.stop.wait(self.poll_interval)
                        continue
                    log.info("[%s] running job %s (%s)", name, job_id, jtype)
                    with self.running_lock:
                        self.running[job_id] = name
                    try:
                        status = execute(job_id, f"{self.worker_id}/{name}")
                    finally:
                        with self.running_lock:
                            self.running.pop(job_id, None)
                    log.info("[%s] job %s -> %s", name, job_id, status)
                    # be polite between network jobs
                    if lane == "network":
                        self.stop.wait(min(st.request_delay_seconds, 30))
                finally:
                    if heavy:
                        self.heavy_lock.release()
            except Exception:  # never let a lane thread die
                log.exception("[%s] lane loop error", name)
                self.stop.wait(5)

    def heartbeat_loop(self) -> None:
        last_recover = time.monotonic()
        while not self.stop.is_set():
            try:
                with session_scope() as s:
                    with self.running_lock:
                        ids = list(self.running)
                    if ids:
                        for job in s.query(Job).filter(Job.id.in_(ids)).all():
                            job.heartbeat_at = utcnow()
                    row = s.get(AppSetting, HEARTBEAT_KEY)
                    status = {"worker_id": self.worker_id, "pid": os.getpid(), "at": utcnow().isoformat(),
                              "running": ids}
                    if row is None:
                        s.add(AppSetting(key=HEARTBEAT_KEY, value=status))
                    else:
                        row.value = status
                if time.monotonic() - last_recover > 300:
                    with session_scope() as s:
                        # jobs whose thread vanished (should not happen) are requeued
                        n = recover_interrupted(s, stale_after_seconds=1800)
                        if n:
                            log.warning("requeued %d stale jobs", n)
                    last_recover = time.monotonic()
            except Exception:
                log.exception("heartbeat error")
            self.stop.wait(10)

    def start(self) -> None:
        with session_scope() as s:
            n = recover_interrupted(s)
            if n:
                log.warning("recovered %d interrupted job(s) from previous run", n)
        for lane, mx in LANE_MAX.items():
            for i in range(mx):
                t = threading.Thread(target=self.lane_loop, args=(lane, i), name=f"{lane}-{i}", daemon=True)
                t.start()
                self.threads.append(t)
        hb = threading.Thread(target=self.heartbeat_loop, name="heartbeat", daemon=True)
        hb.start()
        self.threads.append(hb)

    def shutdown(self, timeout: float = 15) -> None:
        self.stop.set()
        deadline = time.monotonic() + timeout
        for t in self.threads:
            t.join(max(0.1, deadline - time.monotonic()))
        with session_scope() as s:
            row = s.get(AppSetting, HEARTBEAT_KEY)
            if row is not None:
                row.value = {"worker_id": self.worker_id, "stopped_at": utcnow().isoformat()}


def worker_online(value: dict | None, max_age: float = 45) -> bool:
    if not value or "at" not in value:
        return False
    from datetime import datetime

    try:
        at = datetime.fromisoformat(value["at"])
    except ValueError:
        return False
    return utcnow() - at < timedelta(seconds=max_age)


def main() -> int:
    parser = argparse.ArgumentParser(description="YouTube Content Studio worker")
    parser.add_argument("--poll", type=float, default=2.0)
    args = parser.parse_args()
    env = get_env()
    setup_logging(env.log_dir, "worker", env.log_level)
    lock = InstanceLock(env.archive_dir / "worker.lock")
    try:
        lock.acquire()
    except AlreadyRunning:
        log.error("Another worker is already running for %s. Exiting.", env.archive_dir)
        return 2
    try:
        init_db()
        worker = Worker(args.poll)
        stop = threading.Event()

        def _sig(*_a):
            log.info("shutdown requested")
            stop.set()

        signal.signal(signal.SIGINT, _sig)
        signal.signal(signal.SIGTERM, _sig)
        if hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, _sig)  # type: ignore[attr-defined]
        worker.start()
        log.info("worker %s started (archive: %s)", worker.worker_id, env.archive_dir)
        while not stop.is_set():
            stop.wait(1)
        worker.shutdown()
        log.info("worker stopped")
    finally:
        lock.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
