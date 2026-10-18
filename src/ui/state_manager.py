"""Initialize and reset the Streamlit application session."""

from typing import Any

import streamlit as st

from src.utils.logging_config import get_logger

logger = get_logger(__name__)

DEFAULTS: dict[str, Any] = {
    "messages": [],
    "tool_trace": [],
    "candidate_slots": [],
    "target_duration_hours": 0.0,
    "selected_slot_type": None,
    "matched_rigs": [],
    "agent_history": [],
    "ollama_history": [],
    "slot_search_context": {},
    "benchmark_trace": None,
    "pending_booking_follow_up": None,
}


def initialize_session_state() -> None:
    """Initialize known session keys without overwriting user state."""
    initialized = []
    for key, value in DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value.copy() if isinstance(value, (list, dict)) else value
            initialized.append(key)
    if initialized:
        logger.info("Initialized Streamlit session state keys: %s", initialized)


def reset_session_state() -> None:
    """Reset conversation and candidate state while preserving widget settings."""
    for key, value in DEFAULTS.items():
        st.session_state[key] = value.copy() if isinstance(value, (list, dict)) else value
    for key in ("booking_slot_type", "candidate_slot_editor"):
        st.session_state.pop(key, None)
    logger.info("Conversation and booking session state reset.")
