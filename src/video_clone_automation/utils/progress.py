from __future__ import annotations

import sys
import threading
import time
from contextlib import contextmanager
from collections.abc import Iterator
from typing import TextIO


class ProgressReporter:
    def __init__(self, *, enabled: bool = True, stream: TextIO | None = None) -> None:
        self.enabled = enabled
        self.stream = stream or sys.stderr
        self.started_at = time.monotonic()

    def log(self, message: str, *, stage: str | None = None) -> None:
        if not self.enabled:
            return
        elapsed = self._format_elapsed(time.monotonic() - self.started_at)
        prefix = f"[{elapsed}]"
        if stage:
            prefix += f" {stage}"
        print(f"{prefix} {message}", file=self.stream, flush=True)

    @staticmethod
    def _format_elapsed(seconds: float) -> str:
        total_seconds = int(seconds)
        hours, remainder = divmod(total_seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"


def progress_log(progress: object | None, message: str, *, stage: str | None = None) -> None:
    if progress is None:
        return
    log = getattr(progress, "log", None)
    if callable(log):
        log(message, stage=stage)


@contextmanager
def progress_heartbeat(
    progress: object | None,
    message: str,
    *,
    stage: str | None = None,
    interval_seconds: float = 30.0,
) -> Iterator[None]:
    if progress is None:
        yield
        return

    stop_event = threading.Event()

    def run() -> None:
        while not stop_event.wait(interval_seconds):
            progress_log(progress, message, stage=stage)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
        thread.join(timeout=0.2)
