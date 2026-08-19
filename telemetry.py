"""Per-call model tracing to JSONL.

Replaces the web app's database-backed observability. Every model call in a
sweep writes one line: stage, model, tokens, latency, stop reason, and the full
request/response envelope. That envelope is what made the frontmatter tool-call
failure diagnosable at all — a score alone tells you a run got worse, not why.

JSONL rather than a table because a sweep is a batch job whose output is read
by `jq` and by the report command, not by a UI, and because the file is the
unit of resumability: if it exists and is complete, the sample is done.
"""

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Trace:
    """Append-only JSONL sink for one sample's model calls."""

    path: Path
    _seq: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def begin_stage(self, stage: str) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    def finish_call(self, **record: Any) -> None:
        with self._lock:
            with self.path.open("a") as fh:
                fh.write(json.dumps(record, default=str) + "\n")


current_trace: ContextVar[Trace | None] = ContextVar("current_trace", default=None)


@contextmanager
def tracing(path: Path) -> Iterator[Trace]:
    """Route every model call made inside this block to `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    trace = Trace(path=path)
    token = current_trace.set(trace)
    try:
        yield trace
    finally:
        current_trace.reset(token)
