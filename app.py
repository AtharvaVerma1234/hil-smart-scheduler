"""Streamlit entry point for the Monokai HIL scheduler workspace."""

from html import escape

import streamlit as st
from google.genai.errors import APIError

from src.agent.orchestrator import AgentOrchestrator
from src.config.constants import SlotType
from src.config.settings import ACTIVE_MODEL, LLM_PROVIDER
from src.ui.components.chat_panel import (
    render_chat_header,
    render_chat_history,
    render_chat_input,
    render_chat_slot_selector,
)
from src.ui.components.sidebar import render_sidebar, render_top_navbar
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

_MONOKAI_CSS = """
<style>
:root {
  color-scheme: dark;
  --hil-bg: #191A1E;
  --hil-panel: #202226;
  --hil-card: #25272C;
  --hil-border: #2E323B;
  --hil-border-soft: #3A3F47;
  --hil-text: #F8F8F2;
  --hil-muted: #9B9DA5;
  --hil-cyan: #66D9EF;
  --hil-yellow: #E6DB74;
}
[data-testid="stAppViewContainer"], [data-testid="stHeader"] {
  background: var(--hil-bg);
  color: var(--hil-text);
}
header[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stAppDeployButton"],
.stDeployButton,
#MainMenu,
footer {
  display: none !important;
  visibility: hidden !important;
  height: 0 !important;
}
[data-testid="stMain"] > div { padding-top: 0.25rem !important; }
.block-container { max-width: 100%; padding: 0.35rem 1.0rem 0.4rem !important; }
.hil-topbar-brand {
  min-height: 2.5rem; display:flex; align-items:center; gap:1rem;
  background:#202226; border:1px solid #2E323B; border-radius:12px;
  padding:.35rem .85rem; color:#F8F8F2; white-space:nowrap;
}
.hil-brand-title { font-size:1.04rem; color:#F8F8F2; }
.hil-brand-divider { color:#555963; }
.hil-brand-crumb { color:#A6A8AE; font-size:.88rem; }
.hil-filter-heading { color:#F8F8F2; font-weight:700; font-size:1.0rem; margin:0 0 .4rem; }
.hil-filter-spacer { min-height:0.4rem; }
.hil-date-caption { color:#A6A8AE; font-size:.72rem; margin:.2rem 0 .1rem; }
.hil-date-range {
  color:#F8F8F2; font-size:.82rem; font-weight:600; white-space:nowrap;
  border:1px solid #3A3D45; border-radius:7px; padding:.45rem .35rem;
  text-align:center; background:#1E2025;
}
.hil-chat-header {
  display:flex; align-items:center; gap:.85rem; margin:0 0 .45rem;
  border-bottom:1px solid #2E323B; padding:.15rem 0 .45rem;
}
.hil-chip-badge, .hil-assistant-avatar, .hil-user-avatar {
  display:flex; align-items:center; justify-content:center; flex:0 0 auto;
  border-radius:50%; font-weight:700;
}
.hil-chip-badge { width:2.25rem; height:2.25rem; color:#66D9EF; background:#193238; border:1px solid #2C5962; }
.hil-chat-title { color:#F8F8F2; font-size:1.16rem; font-weight:700; }
.hil-chat-subtitle { color:#9B9DA5; font-size:.82rem; margin-top:.16rem; }
.hil-user-row { display:flex; justify-content:flex-end; align-items:flex-end; gap:.6rem; margin:.8rem 0; }
.hil-user-bubble {
  max-width:88%; background:#1E2025; border:1px solid #3A3D45;
  color:#F8F8F2; border-radius:14px; padding:12px 16px; line-height:1.55;
}
.hil-user-avatar { width:2rem; height:2rem; color:#F8F8F2; background:#3A3D45; font-size:.7rem; }
.hil-assistant-card {
  display:flex; gap:.75rem; align-items:flex-start; margin:.8rem 0;
  background:#25272C; border:1px solid #3A3F47; color:#F8F8F2;
  border-radius:14px; padding:14px 18px;
}
.hil-assistant-avatar { width:2rem; height:2rem; color:#66D9EF; background:#193238; border:1px solid #2C5962; }
.hil-assistant-body { min-width:0; flex:1; }
.hil-assistant-label { color:#66D9EF; font-size:.76rem; font-weight:700; margin:0 0 .4rem; }
.hil-assistant-content { color:#F8F8F2; line-height:1.6; overflow-wrap:anywhere; }
.hil-assistant-content p:last-child { margin-bottom:0; }
.hil-section-title { color:#F8F8F2; font-weight:700; font-size:.96rem; margin:.4rem 0 .35rem; }
.hil-rig-card { background:#25272C; border:1px solid #3A3F47; border-radius:10px; padding:.75rem; margin:.55rem 0; }
.hil-rig-card-top { display:flex; justify-content:space-between; gap:.4rem; color:#F8F8F2; }
.hil-match-score { color:#A6E22E; font-size:.75rem; white-space:nowrap; }
.hil-rig-matched { color:#E6DB74; font-size:.78rem; margin-top:.4rem; overflow-wrap:anywhere; }
.hil-rig-meta { color:#9B9DA5; font-size:.72rem; margin-top:.35rem; overflow-wrap:anywhere; }
[data-testid="stVerticalBlockBorderWrapper"] { background:#202226; border-color:#2E323B; border-radius:12px; }
[data-testid="stDataFrame"], [data-testid="stDataEditor"] { border:1px solid #2E323B; border-radius:10px; overflow:hidden; }
[data-testid="stMetric"] { background:#202226; border:1px solid #2E323B; border-radius:10px; padding:.7rem; }
[data-testid="stPopover"] button, .stButton > button { border-radius:9px; }
div[data-testid="stExpander"] { border-color:#3A3D45; border-radius:9px; }
.stForm [data-testid="stFormSubmitButton"] button {
  color:#191A1E; font-weight:800; border:0;
  background:linear-gradient(135deg,#FD971F,#F92672);
}
.stForm [data-testid="stFormSubmitButton"] button:hover {
  color:#F8F8F2; box-shadow:0 0 14px rgba(249,38,114,.35);
}
.st-key-right_panel_view_toggle button[kind="primary"] {
  color:#66D9EF; background:#193238; border:1px solid #66D9EF;
  box-shadow:0 0 10px rgba(102,217,239,.28);
}
.st-key-ciara_booking_cta button[kind="primary"] {
  color:#F8F8F2; border:1px solid #F92672;
  background:#F92672; box-shadow:0 0 10px rgba(249,38,114,.2);
}
.hil-match-table-wrap { overflow-x:auto; }
.hil-match-table { width:100%; border-collapse:collapse; font-size:.72rem; color:#F8F8F2; }
.hil-match-table th { color:#9B9DA5; font-weight:600; text-align:left; padding:.45rem .25rem; border-bottom:1px solid #3A3D45; }
.hil-match-table td { padding:.55rem .25rem; border-bottom:1px solid #32353C; vertical-align:middle; }
.hil-rig-name { font-weight:700; color:#F8F8F2; white-space:nowrap; }
.hil-hardware-summary { color:#C8C9CD; }
.hil-selected-booking { display:flex; align-items:center; gap:.55rem; background:#202226; border:1px solid #66D9EF; box-shadow:0 0 7px rgba(102,217,239,.12); border-radius:9px; padding:.6rem; margin:.45rem 0; font-size:.75rem; }
.hil-selected-check { display:flex; align-items:center; justify-content:center; width:1.35rem; height:1.35rem; color:#191A1E; background:#A6E22E; border-radius:50%; font-weight:900; }
.hil-selected-details { min-width:0; flex:1; color:#F8F8F2; }
.hil-selected-details div { color:#B8BAC0; margin-top:.2rem; }
.hil-selected-pill { background:#193238; color:#66D9EF; border:1px solid #2C5962; border-radius:99px; padding:.2rem .45rem; white-space:nowrap; font-size:.67rem; }
.hil-proposed-pill { display:inline-block; padding:.3rem .5rem; border-radius:99px; color:#66D9EF; background:#193238; border:1px solid #2C5962; white-space:nowrap; font-size:.68rem; }
.hil-total-label { color:#9B9DA5; font-size:.72rem; margin-top:.9rem; }
.hil-total-value { color:#E6DB74; font-size:1.25rem; font-weight:700; }
.hil-total-value span { color:#AE81FF; font-size:.72rem; font-weight:500; }
.hil-calendar-legend { text-align:right; color:#D0D0D0; font-size:.7rem; margin:.2rem 0 .65rem; }
.hil-calendar-day { text-align:center; font-size:.72rem; color:#F8F8F2; font-weight:700; min-height:2.5rem; }
.hil-calendar-day span { color:#9B9DA5; font-size:.64rem; font-weight:500; }
.hil-calendar-track { display:flex; flex-direction:column; width:100%; gap:0; }
.hil-timeline-block { width:100%; box-sizing:border-box; overflow:hidden; border:1px solid; border-radius:4px; padding:2px; color:#F8F8F2; font-size:.58rem; line-height:1.15; text-align:center; }
.hil-calendar-axis { position:relative; color:#9B9DA5; font-size:.6rem; }
.hil-timeline-block + .hil-timeline-block { border-top-width:0; }
.hil-breakdown-card { background:#202226; border:1px solid #3A3F47; border-radius:9px; padding:.7rem; margin:.6rem 0; }
.hil-meta-badges { display:flex; flex-wrap:wrap; gap:.3rem; margin-bottom:.55rem; }
.hil-meta-badge { border:1px solid #3A3D45; background:#1E2025; border-radius:99px; padding:.22rem .42rem; color:#D5D5D0; font-size:.62rem; }
.hil-meta-badge b { color:#66D9EF; }
.hil-ecu-table, .hil-breakdown-table { width:100%; border-collapse:collapse; font-size:.65rem; }
.hil-ecu-table td { width:33.33%; vertical-align:top; padding:.35rem .2rem; }
.hil-ecu-heading { font-weight:700; margin-bottom:.35rem; }
.hil-ecu-pills { display:flex; flex-wrap:wrap; gap:.2rem; color:#9B9DA5; }
.hil-ecu-pill { display:inline-block; padding:.12rem .32rem; border:1px solid; border-radius:99px; font-size:.6rem; }
.hil-breakdown-table { margin-top:.55rem; }
.hil-breakdown-table th, .hil-breakdown-table td { padding:.35rem .3rem; text-align:left; border-bottom:1px solid #363940; }
.hil-breakdown-table th { color:#9B9DA5; }
@media (max-width: 1100px) {
  .hil-brand-crumb { display:none; }
  .block-container { padding-left:.75rem; padding-right:.75rem; }
}
</style>
"""


def main() -> None:
    """Render the three-column discovery, scheduling, and booking workspace."""
    st.set_page_config(
        page_title="HIL Smart Scheduler",
        page_icon="🧊",
        layout="wide",
    )
    st.markdown(_MONOKAI_CSS, unsafe_allow_html=True)
    initialize_session_state()
    nav_info = render_top_navbar()
    left_col, center_col, right_col = st.columns([1.0, 2.25, 1.35], gap="medium")
    with left_col:
        sidebar_info = render_sidebar(left_col, nav_info)
    pending_follow_up = st.session_state.pop("pending_booking_follow_up", None)
    if pending_follow_up:
        st.session_state.messages.append(
            {"role": "assistant", "content": pending_follow_up}
        )

    with center_col:
        render_chat_header()
        chat_scroll = st.container(height=380, border=False)
        with chat_scroll:
            render_chat_history()
            render_chat_slot_selector()
        submitted = render_chat_input()
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
            with chat_scroll:
                st.markdown(
                    f"""
                    <div class="hil-user-row">
                      <div class="hil-user-bubble">{escape(submitted)}</div>
                      <div class="hil-user-avatar">AV</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
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
                st.session_state["_pending_booking_slot_type"] = mentioned_type
            mark_benchmark(
                benchmark,
                "booking_type_extraction_completed",
                slot_type_detected=bool(mentioned_type),
            )
            mark_benchmark(benchmark, "user_message_rendered")
            should_rerun = False
            try:
                status_box = st.status(
                    "🤖 Coordinator is evaluating rig topologies & CIARA schedules...",
                    expanded=True,
                )
                with status_box:
                    mark_benchmark(benchmark, "agent_initialization_started")
                    response = AgentOrchestrator(sidebar_info["api_key"]).respond(
                        submitted
                    )
                    mark_benchmark(
                        benchmark,
                        "agent_response_returned",
                        response_characters=len(response),
                    )
                    st.session_state.messages.append(
                        {
                            "role": "assistant",
                            "content": response,
                            "tool_trace": st.session_state.get("tool_trace", [])[:],
                        }
                    )
                    mark_benchmark(benchmark, "assistant_message_saved_to_session")
                status_box.update(
                    label="✅ Analysis complete",
                    state="complete",
                    expanded=False,
                )
                mark_benchmark(benchmark, "assistant_response_render_submitted")
                mark_benchmark(benchmark, "streamlit_rerun_render_complete")
                should_rerun = True
            except APIError as exc:
                mark_benchmark(
                    benchmark,
                    "turn_failed",
                    exception_type=type(exc).__name__,
                    status_code=getattr(
                        exc, "code", getattr(exc, "status_code", "unknown")
                    ),
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
            if should_rerun:
                st.rerun()

    render_slot_picker(sidebar_info["user_id"], right_col)

if __name__ == "__main__":
    main()
