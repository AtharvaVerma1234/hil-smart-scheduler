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
    "last_booking_message_index": 0,
    "right_panel_view": "Matched & Booking",
    "selected_slot_keys": [],
    "filter_include_extended": False,
    "filter_allow_weekends": False,
    "filter_shift_range": ("09:00", "18:00"),
    "filter_start_date": "2026-10-15",
    "filter_end_date": "2026-10-21",
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
    st.session_state["selected_slot_keys"] = []
    for key in (
        "booking_slot_type",
        "candidate_slot_editor",
        "filter_include_extended_widget",
        "filter_allow_weekends_widget",
        "filter_shift_range",
        "filter_shift_range_widget",
        "filter_start_date_picker",
        "filter_end_date_picker",
        "_last_picker_start_date",
        "_pending_filter_toggle_sync",
        "_pending_booking_slot_type",
    ):
        st.session_state.pop(key, None)
    logger.info("Conversation and booking session state reset.")
