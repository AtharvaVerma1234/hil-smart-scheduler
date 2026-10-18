"""Sidebar configuration, browser timezone, and agent observability."""

import os

import streamlit as st

from src.config.settings import ACTIVE_MODEL, LLM_PROVIDER, OLLAMA_BASE_URL
from src.ui.state_manager import reset_session_state
from src.utils.benchmarking import (
    get_benchmark_log_path,
    initialize_benchmark_logging,
)
from src.utils.logging_config import get_log_file_path, get_logger

logger = get_logger(__name__)


def render_sidebar() -> dict[str, str]:
    """Render settings and return credentials and active schedule preferences."""
    with st.sidebar:
        st.header("HIL Scheduler Settings")
        api_key = ""
        if LLM_PROVIDER == "gemini":
            api_key = st.text_input(
                "Gemini API Key",
                value=os.environ.get("GEMINI_API_KEY", ""),
                type="password",
                help="Set GEMINI_API_KEY in .env or enter it for this session.",
            )
        else:
            st.caption(f"Local Ollama model: `{ACTIVE_MODEL}`")
            st.caption(f"Ollama server: `{OLLAMA_BASE_URL}`")
        user_id = st.text_input("Logged-in User ID", value="USER_ENG_01")
        st.caption(f"LLM provider: `{LLM_PROVIDER}`")
        if LLM_PROVIDER == "gemini":
            st.caption(f"Gemini model: `{ACTIVE_MODEL}`")
        timezone = getattr(st.context, "timezone", None) or "Asia/Kolkata"
        st.caption(f"Browser timezone: **{timezone}**")
        left, right = st.columns(2)
        shift_start = left.text_input("Shift Start", value="09:00")
        shift_end = right.text_input("Shift End", value="18:00")
        simulated_date = st.text_input(
            "Simulated Current Date", value="2026-10-15"
        )
        st.session_state.search_settings = {
            "shift_start": shift_start,
            "shift_end": shift_end,
            "start_date": simulated_date,
        }
        logger.debug(
            "Sidebar schedule settings: timezone=%s shift=%s-%s simulated_date=%s "
            "api_key_configured=%s",
            timezone,
            shift_start,
            shift_end,
            simulated_date,
            bool(api_key),
        )
        if st.button("🔄 Reset Conversation", use_container_width=True):
            reset_session_state()
            st.rerun()
        with st.expander("🔍 Live Agent State & Tool Calls", expanded=False):
            trace = st.session_state.get("tool_trace", [])
            if trace:
                for item in reversed(trace[-20:]):
                    with st.expander(
                        f'{item.get("tool", "Tool")} — {item.get("status", "unknown")}'
                    ):
                        st.json(item)
            else:
                st.caption("Tool invocations will appear here.")
        log_path = get_log_file_path()
        st.caption(f"Diagnostic log: `{log_path}`")
        if log_path.is_file():
            try:
                log_data = log_path.read_bytes()
            except OSError:
                logger.exception("Unable to read diagnostic log for download: path=%s", log_path)
                st.warning("The diagnostic log could not be read. Check the app console.")
            else:
                st.download_button(
                    "Download Diagnostic Log",
                    data=log_data,
                    file_name=log_path.name,
                    mime="text/plain",
                    use_container_width=True,
                )
        initialize_benchmark_logging()
        benchmark_path = get_benchmark_log_path()
        st.caption(f"Benchmark log: `{benchmark_path}`")
        if benchmark_path.is_file():
            try:
                benchmark_data = benchmark_path.read_bytes()
            except OSError:
                logger.exception(
                    "Unable to read benchmark log for download: path=%s",
                    benchmark_path,
                )
                st.warning("The benchmark log could not be read. Check the app console.")
            else:
                st.download_button(
                    "Download Benchmark Log",
                    data=benchmark_data,
                    file_name=benchmark_path.name,
                    mime="application/x-ndjson",
                    use_container_width=True,
                )
    return {
        "api_key": api_key,
        "user_id": user_id,
        "timezone": timezone,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "simulated_date": simulated_date,
    }
