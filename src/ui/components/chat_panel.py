"""Chat history and coordinator input."""

import streamlit as st


def render_chat_history() -> None:
    """Render previous user and assistant messages."""
    for message in st.session_state.get("messages", []):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("tool_trace"):
                with st.expander("Agent Tool Trace"):
                    st.json(message["tool_trace"])


def render_chat_input() -> str | None:
    """Return the submitted chat message, if any."""
    return st.chat_input("Ask about HIL rigs, ECU configurations, or availability...")
