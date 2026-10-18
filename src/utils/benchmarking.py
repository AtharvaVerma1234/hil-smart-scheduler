"""Microsecond-resolution per-turn benchmark logging."""

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from src.utils.logging_config import PROJECT_ROOT, get_logger

_LOCK = threading.Lock()
_BENCHMARK_LOGGER_NAME = "hil_scheduler.benchmark"


def get_benchmark_log_path() -> Path:
    """Return the separate JSONL benchmark log path."""
    log_dir = Path(os.environ.get("HIL_LOG_DIR", PROJECT_ROOT / "logs"))
    return log_dir / "hil-smart-scheduler-benchmark.jsonl"


def _get_benchmark_logger() -> logging.Logger:
    logger = logging.getLogger(_BENCHMARK_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    path = get_benchmark_log_path().resolve()
    if any(
        isinstance(handler, RotatingFileHandler)
        and Path(handler.baseFilename).resolve() == path
        for handler in logger.handlers
    ):
        return logger
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
    except OSError:
        get_logger(__name__).exception(
            "Benchmark file logger initialization failed: path=%s",
            path,
        )
        raise
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    return logger


def initialize_benchmark_logging() -> None:
    """Create the benchmark log destination before the first chat request."""
    _get_benchmark_logger()


@dataclass
class BenchmarkTrace:
    """Monotonic per-request clock for precise elapsed-time measurements."""

    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    started_ns: int = field(default_factory=time.perf_counter_ns)
    previous_event_ns: int = field(default_factory=time.perf_counter_ns)

    def mark(self, stage: str, **metadata: Any) -> None:
        """Write one JSONL event with absolute and since-previous durations."""
        now_ns = time.perf_counter_ns()
        record = {
            "request_id": self.request_id,
            "stage": stage,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(
                timespec="microseconds"
            ),
            "elapsed_us": (now_ns - self.started_ns) // 1_000,
            "since_previous_us": (now_ns - self.previous_event_ns) // 1_000,
            **metadata,
        }
        self.previous_event_ns = now_ns
        try:
            encoded = json.dumps(record, sort_keys=True, default=str)
            with _LOCK:
                _get_benchmark_logger().info(encoded)
        except Exception:
            get_logger(__name__).exception(
                "Failed to write benchmark event: request_id=%s stage=%s",
                self.request_id,
                stage,
            )


def start_benchmark(stage: str = "submit_received", **metadata: Any) -> BenchmarkTrace:
    """Start a request trace and record its first server-side event."""
    trace = BenchmarkTrace()
    trace.mark(stage, **metadata)
    return trace


def mark_benchmark(
    trace: BenchmarkTrace | None,
    stage: str,
    **metadata: Any,
) -> None:
    """Record an event when this rerun has an active request trace."""
    if trace is not None:
        trace.mark(stage, **metadata)


def elapsed_microseconds(started_ns: int) -> int:
    """Return elapsed monotonic time in whole microseconds."""
    return (time.perf_counter_ns() - started_ns) // 1_000
