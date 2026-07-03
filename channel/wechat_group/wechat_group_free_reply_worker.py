"""Dedicated worker pool for WeChat group free reply candidates."""

import queue
import threading
import time


class WechatGroupFreeReplyWorkerPool:
    def __init__(self, judge, submit_callback, max_workers=2, queue_size=100, ttl_seconds=120):
        self.judge = judge
        self.submit_callback = submit_callback
        self.max_workers = max(1, int(max_workers or 1))
        self.queue_limit = max(1, int(queue_size or 1))
        self.ttl_seconds = max(1, int(ttl_seconds or 120))
        self._queue = queue.Queue(maxsize=self.queue_limit)
        self._stop_event = threading.Event()
        self._threads = []
        self._lock = threading.Lock()
        self._active_workers = 0
        self._running = False
        self.submitted_total = 0
        self.dropped_total = 0
        self.expired_total = 0
        self.approved_total = 0
        self.rejected_total = 0
        self.last_error = ""

    def start(self) -> None:
        if self._running:
            return
        self._stop_event.clear()
        self._running = True
        for idx in range(self.max_workers):
            thread = threading.Thread(target=self._run, name="wechat-free-reply-{}".format(idx), daemon=True)
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        self._stop_event.set()
        self._running = False
        for _ in self._threads:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                pass
        for thread in self._threads:
            thread.join(timeout=1)
        self._threads = []

    def submit(self, task) -> bool:
        try:
            self._queue.put_nowait(task)
        except queue.Full:
            with self._lock:
                self.dropped_total += 1
            return False
        with self._lock:
            self.submitted_total += 1
        return True

    def status(self) -> dict:
        with self._lock:
            return {
                "running": self._running,
                "max_workers": self.max_workers,
                "queue_size": self._queue.qsize(),
                "queue_limit": self.queue_limit,
                "active_workers": self._active_workers,
                "submitted_total": self.submitted_total,
                "dropped_total": self.dropped_total,
                "expired_total": self.expired_total,
                "approved_total": self.approved_total,
                "rejected_total": self.rejected_total,
                "last_error": self.last_error,
            }

    def _run(self):
        while not self._stop_event.is_set():
            try:
                task = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if task is None:
                    return
                self._process(task)
            finally:
                self._queue.task_done()

    def _process(self, task):
        queued_at = float(task.get("queued_at") or 0)
        if queued_at and time.time() - queued_at > self.ttl_seconds:
            with self._lock:
                self.expired_total += 1
            return
        with self._lock:
            self._active_workers += 1
        try:
            decision = self.judge.judge(task, task.get("config") or {})
            if decision.get("approved"):
                self.submit_callback(task, decision)
                with self._lock:
                    self.approved_total += 1
            else:
                with self._lock:
                    self.rejected_total += 1
        except Exception as e:
            with self._lock:
                self.rejected_total += 1
                self.last_error = str(e)
        finally:
            with self._lock:
                self._active_workers -= 1
