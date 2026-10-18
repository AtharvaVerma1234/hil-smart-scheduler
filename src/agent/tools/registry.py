"""Plugin-style registry for Gemini-callable deterministic tools."""

from functools import wraps
import time
from typing import Any, Callable, TypeVar

import streamlit as st

from src.utils.logging_config import get_logger
from src.utils.benchmarking import mark_benchmark

F = TypeVar("F", bound=Callable[..., Any])
AGENT_TOOLS: list[Callable[..., Any]] = []
logger = get_logger(__name__)


def register_tool(function: F) -> F:
    """Register a callable and record its invocation and result for observability."""

    @wraps(function)
    def traced(*args: Any, **kwargs: Any) -> Any:
        started_ns = time.perf_counter_ns()
        benchmark = st.session_state.get("benchmark_trace")
        entry: dict[str, Any] = {
            "tool": function.__name__,
            "argument_names": sorted(kwargs) if kwargs else [],
            "status": "running",
        }
        logger.info(
            "Agent tool started: tool=%s arguments=%s positional_argument_count=%d",
            function.__name__,
            kwargs if kwargs else args,
            len(args),
        )
        mark_benchmark(
            benchmark,
            "tool_execution_started",
            tool=function.__name__,
            positional_argument_count=len(args),
            keyword_argument_names=sorted(kwargs),
        )
        if hasattr(st, "session_state"):
            entry["arguments"] = kwargs if kwargs else {"args": args}
            st.session_state.setdefault("tool_trace", []).append(entry)
        try:
            result = function(*args, **kwargs)
        except Exception as exc:
            elapsed_us = (time.perf_counter_ns() - started_ns) // 1_000
            elapsed_ms = round(elapsed_us / 1_000, 3)
            mark_benchmark(
                benchmark,
                "tool_execution_failed",
                tool=function.__name__,
                exception_type=type(exc).__name__,
                elapsed_us=elapsed_us,
            )
            entry.update({"status": "error", "error": str(exc), "elapsed_ms": elapsed_ms})
            logger.exception(
                "Agent tool failed: tool=%s elapsed_ms=%.2f",
                function.__name__,
                elapsed_ms,
            )
            raise
        elapsed_us = (time.perf_counter_ns() - started_ns) // 1_000
        elapsed_ms = round(elapsed_us / 1_000, 3)
        mark_benchmark(
            benchmark,
            "tool_execution_completed",
            tool=function.__name__,
            elapsed_us=elapsed_us,
        )
        result_summary = _summarize_result(result)
        entry.update(
            {
                "status": "complete",
                "elapsed_ms": elapsed_ms,
                "result_summary": result_summary,
                "result": result,
            }
        )
        logger.info(
            "Agent tool completed: tool=%s elapsed_ms=%.2f result_summary=%s",
            function.__name__,
            elapsed_ms,
            result_summary,
        )
        return result

    AGENT_TOOLS.append(traced)
    return traced  # type: ignore[return-value]


def get_registered_tools() -> list[Callable[..., Any]]:
    """Return the functions enabled for automatic Phase 1 tool calling."""
    logger.debug("Returning registered agent tools: count=%d", len(AGENT_TOOLS))
    return list(AGENT_TOOLS)


def _summarize_result(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"type": type(result).__name__}
    summary: dict[str, Any] = {"keys": sorted(result)}
    for key in ("rigs", "ranked_rigs", "standard_slots", "extended_slots", "rig_conflicts"):
        value = result.get(key)
        if isinstance(value, list):
            summary[f"{key}_count"] = len(value)
    return summary
