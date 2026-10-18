"""Streamlit entry point for HIL Testbench Discovery & Smart Scheduler."""

from src.config.settings import ACTIVE_MODEL, LLM_PROVIDER
import streamlit as st
from google.genai.errors import APIError

from src.agent.orchestrator import AgentOrchestrator
from src.config.constants import SlotType
from src.ui.components.chat_panel import render_chat_history, render_chat_input
from src.ui.components.sidebar import render_sidebar
from src.ui.components.slot_picker_table import render_slot_picker
from src.ui.state_manager import initialize_session_state
from src.utils.benchmarking import mark_benchmark, start_benchmark
from src.utils.logging_config import get_logger

logger = get_logger(__name__)
logger.info(
    "Starting HIL Smart Scheduler entry point: provider=%s model=%s",
    LLM_PROVIDER,
    ACTIVE_MODEL,
)


def main() -> None:
    """Render the chat-led HIL discovery, scheduling, and booking application."""
    st.set_page_config(
        page_title="HIL Smart Scheduler",
        page_icon="🛠️",
        layout="wide",
    )
    initialize_session_state()
    sidebar = render_sidebar()
    logger.debug("Streamlit page initialized.")
    st.title("HIL Testbench Discovery & Smart Scheduler")
    st.caption(
        "Discover compatible rigs, compare ECU configurations, and stage "
        "available CIARA booking slots."
    )
    render_chat_history()
    pending_follow_up = st.session_state.pop("pending_booking_follow_up", None)
    if pending_follow_up:
        with st.chat_message("assistant"):
            st.markdown(pending_follow_up)
        st.session_state.messages.append(
            {"role": "assistant", "content": pending_follow_up}
        )
        logger.info("Rendered and persisted post-booking assistant follow-up.")
    submitted = render_chat_input()
    benchmark = None
    if submitted:
        benchmark = start_benchmark(
            message_characters=len(submitted),
            provider=LLM_PROVIDER,
            model=ACTIVE_MODEL,
        )
        st.session_state.benchmark_trace = benchmark
        logger.info("Chat message submitted: message_characters=%d", len(submitted))
        mark_benchmark(benchmark, "user_message_received")
        st.session_state.messages.append({"role": "user", "content": submitted})
        mark_benchmark(benchmark, "user_message_saved_to_session")
        mentioned_type = next(
            (
                item.value
                for item in SlotType
                if item.value.casefold() in submitted.casefold()
            ),
            None,
        )
        if mentioned_type:
            st.session_state.selected_slot_type = mentioned_type
            st.session_state.booking_slot_type = mentioned_type
        mark_benchmark(
            benchmark,
            "booking_type_extraction_completed",
            slot_type_detected=bool(mentioned_type),
        )
        with st.chat_message("user"):
            st.markdown(submitted)
        mark_benchmark(benchmark, "user_message_rendered")
        with st.chat_message("assistant"):
            try:
                mark_benchmark(benchmark, "agent_initialization_started")
                response = AgentOrchestrator(sidebar["api_key"]).respond(submitted)
                mark_benchmark(
                    benchmark,
                    "agent_response_returned",
                    response_characters=len(response),
                )
                st.markdown(response)
                mark_benchmark(benchmark, "assistant_response_render_submitted")
                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": response,
                        "tool_trace": st.session_state.get("tool_trace", [])[:],
                    }
                )
                mark_benchmark(benchmark, "assistant_message_saved_to_session")
            except APIError as exc:
                mark_benchmark(
                    benchmark,
                    "turn_failed",
                    exception_type=type(exc).__name__,
                    status_code=getattr(exc, "code", getattr(exc, "status_code", "unknown")),
                )
                logger.exception(
                    "Gemini API request failed: exception_type=%s status_code=%s model=%s",
                    type(exc).__name__,
                    getattr(exc, "code", getattr(exc, "status_code", "unknown")),
                    ACTIVE_MODEL,
                )
                st.error(
                    f"Gemini API request failed for model `{ACTIVE_MODEL}`: {exc}. "
                    "The full traceback is in the diagnostic log."
                )
                mark_benchmark(benchmark, "assistant_error_render_submitted")
            except Exception as exc:
                mark_benchmark(
                    benchmark,
                    "turn_failed",
                    exception_type=type(exc).__name__,
                )
                logger.exception(
                    "Unhandled chat request failure: exception_type=%s "
                    "provider=%s model=%s",
                    type(exc).__name__,
                    LLM_PROVIDER,
                    ACTIVE_MODEL,
                )
                st.error(
                    f"Unable to complete the request ({type(exc).__name__}): {exc}. "
                    "The full traceback is in the diagnostic log."
                )
                mark_benchmark(benchmark, "assistant_error_render_submitted")
    render_slot_picker(sidebar["user_id"])
    if benchmark is not None:
        mark_benchmark(
            benchmark,
            "streamlit_rerun_render_complete",
        )


if __name__ == "__main__":
    main()
