"""Monokai navigation, live schedule filters, and diagnostic controls."""

import os
from datetime import date, timedelta
from typing import Any

import streamlit as st

from src.config.settings import ACTIVE_MODEL, LLM_PROVIDER, OLLAMA_BASE_URL
from src.repositories import get_repository
from src.services.slot_scheduler import SlotSchedulerService
from src.ui.state_manager import reset_session_state
from src.utils.benchmarking import (
    get_benchmark_log_path,
    initialize_benchmark_logging,
)
from src.utils.logging_config import get_log_file_path, get_logger

logger = get_logger(__name__)
SHIFT_TIME_OPTIONS = [
    f"{minute // 60:02d}:{minute % 60:02d}"
    for minute in range(6 * 60, 22 * 60 + 1, 30)
]


def _on_shift_slider_change() -> None:
    raw = st.session_state.get("filter_shift_range_widget")
    if (
        isinstance(raw, (tuple, list))
        and len(raw) == 2
        and raw[0] in SHIFT_TIME_OPTIONS
        and raw[1] in SHIFT_TIME_OPTIONS
    ):
        start_idx = SHIFT_TIME_OPTIONS.index(raw[0])
        end_idx = SHIFT_TIME_OPTIONS.index(raw[1])
        if end_idx <= start_idx:
            end_idx = min(len(SHIFT_TIME_OPTIONS) - 1, start_idx + 2)
        valid_pair = (SHIFT_TIME_OPTIONS[start_idx], SHIFT_TIME_OPTIONS[end_idx])
        st.session_state["filter_shift_range"] = valid_pair
        st.session_state["filter_shift_range_widget"] = valid_pair


def render_top_navbar() -> dict[str, str]:
    """Render the global navigation and compact developer controls."""
    with st.container(border=True):
        left, right = st.columns([3.5, 1.0], vertical_alignment="center")
        with left:
            st.markdown(
                """
                <div class="hil-topbar-brand">
                  <span class="hil-brand-title">🧊 <strong>HIL Rig Scheduler</strong></span>
                  <span class="hil-brand-divider">|</span>
                  <span class="hil-brand-crumb">Workspace&nbsp; › &nbsp;HIL Rig Discovery &amp; Scheduler</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with right:
            with st.popover("AV  Atharva Verma ▾", use_container_width=True):
                user_id = st.text_input(
                    "Logged-in User ID",
                    value=st.session_state.get("logged_in_user_id", "USER_ENG_01"),
                    key="logged_in_user_id",
                )
                api_key = ""
                if LLM_PROVIDER == "gemini":
                    api_key = st.text_input(
                        "Gemini API Key",
                        value=os.environ.get("GEMINI_API_KEY", ""),
                        type="password",
                        key="gemini_api_key",
                        help="Set GEMINI_API_KEY in .env or enter it for this session.",
                    )
                st.caption(f"Provider: `{LLM_PROVIDER}` · Model: `{ACTIVE_MODEL}`")
                if LLM_PROVIDER == "ollama":
                    st.caption(f"Ollama server: `{OLLAMA_BASE_URL}`")
                with st.expander("🔍 Live Agent State & Tool Calls", expanded=False):
                    trace = st.session_state.get("tool_trace", [])[-20:]
                    if trace:
                        for index, item in enumerate(reversed(trace)):
                            title = (
                                f'{item.get("tool", "Tool")} — '
                                f'{item.get("status", "unknown")} — {index + 1}'
                            )
                            with st.expander(title):
                                st.json(item)
                    else:
                        st.caption("Tool invocations will appear here.")
                _render_log_download("Download Diagnostic Log", get_log_file_path())
                initialize_benchmark_logging()
                _render_log_download(
                    "Download Benchmark Log", get_benchmark_log_path()
                )
    return {"api_key": api_key, "user_id": user_id}


def _toggle_left_sidebar() -> None:
    st.session_state["left_sidebar_collapsed"] = not bool(
        st.session_state.get("left_sidebar_collapsed", False)
    )


def render_sidebar(
    container: Any = None,
    nav_info: dict[str, str] | None = None,
) -> dict[str, str]:
    """Render schedule filters or collapsed rail and return active preferences."""
    target = st.sidebar if container is None else container
    detected_tz = getattr(st.context, "timezone", None) or "Asia/Kolkata"
    collapsed = bool(st.session_state.get("left_sidebar_collapsed", False))

    if collapsed:
        with target:
            st.button(
                "☰ »",
                key="expand_left_sidebar_button",
                help="Open Filters sidebar",
                on_click=_toggle_left_sidebar,
                use_container_width=True,
            )
        saved_shift = st.session_state.get("filter_shift_range", ("09:00", "18:00"))
        shift_start, shift_end = str(saved_shift[0]), str(saved_shift[1])
        start_date_text = str(st.session_state.get("filter_start_date", "2026-10-15"))
        allow_weekends = bool(st.session_state.get("filter_allow_weekends", False))
        include_extended = bool(st.session_state.get("filter_include_extended", False))
        try:
            parsed_start = date.fromisoformat(start_date_text)
        except ValueError:
            parsed_start = date(2026, 10, 15)
            start_date_text = parsed_start.isoformat()
        end_date_text = _five_active_dates(parsed_start, allow_weekends)[-1].isoformat()
        timezone = str(st.session_state.get("saved_filter_timezone") or detected_tz)
        st.session_state.search_settings = {
            "shift_start": shift_start,
            "shift_end": shift_end,
            "start_date": start_date_text,
            "deadline_date": end_date_text,
            "include_extended": include_extended,
            "allow_weekends": allow_weekends,
        }
        nav_info = nav_info or {}
        return {
            **nav_info,
            "timezone": timezone,
            "shift_start": shift_start,
            "shift_end": shift_end,
            "simulated_date": start_date_text,
            "deadline_date": end_date_text,
        }

    with target:
        with st.container(border=True):
            head_left, head_right = st.columns([3.2, 0.9], vertical_alignment="center")
            with head_left:
                st.markdown(
                    '<div class="hil-filter-heading" style="margin:0;">☰ Filters</div>',
                    unsafe_allow_html=True,
                )
            with head_right:
                st.button(
                    "«",
                    key="collapse_left_sidebar_button",
                    help="Close Filters sidebar",
                    on_click=_toggle_left_sidebar,
                    use_container_width=True,
                )
            timezone_options = list(
                dict.fromkeys(
                    [
                        detected_tz,
                        "Asia/Kolkata",
                        "UTC",
                        "Europe/Berlin",
                        "Europe/Stockholm",
                        "America/Detroit",
                    ]
                )
            )
            saved_tz = st.session_state.get("saved_filter_timezone") or detected_tz
            default_tz_index = (
                timezone_options.index(saved_tz) if saved_tz in timezone_options else 0
            )
            if "filter_timezone" not in st.session_state and saved_tz in timezone_options:
                st.session_state["filter_timezone"] = saved_tz
            timezone = st.selectbox(
                "Timezone",
                options=timezone_options,
                index=default_tz_index,
                key="filter_timezone",
            )
            st.session_state["saved_filter_timezone"] = timezone

            saved_shift = st.session_state.get(
                "filter_shift_range", ("09:00", "18:00")
            )
            if (
                not isinstance(saved_shift, (tuple, list))
                or len(saved_shift) != 2
                or saved_shift[0] not in SHIFT_TIME_OPTIONS
                or saved_shift[1] not in SHIFT_TIME_OPTIONS
            ):
                saved_shift = ("09:00", "18:00")
                st.session_state["filter_shift_range"] = saved_shift
            existing_shift_widget = st.session_state.get(
                "filter_shift_range_widget"
            )
            if (
                not isinstance(existing_shift_widget, (tuple, list))
                or len(existing_shift_widget) != 2
                or existing_shift_widget[0] not in SHIFT_TIME_OPTIONS
                or existing_shift_widget[1] not in SHIFT_TIME_OPTIONS
            ):
                st.session_state["filter_shift_range_widget"] = (
                    str(saved_shift[0]),
                    str(saved_shift[1]),
                )

            shift_range = st.select_slider(
                "Shift timings",
                options=SHIFT_TIME_OPTIONS,
                value=("09:00", "18:00"),
                key="filter_shift_range_widget",
                on_change=_on_shift_slider_change,
                help="Drag the start and end handles to set your working shift window.",
            )
            if isinstance(shift_range, (tuple, list)) and len(shift_range) == 2:
                shift_start, shift_end = str(shift_range[0]), str(shift_range[1])
            else:
                shift_start, shift_end = str(saved_shift[0]), str(saved_shift[1])
            if (
                SHIFT_TIME_OPTIONS.index(shift_end)
                <= SHIFT_TIME_OPTIONS.index(shift_start)
            ):
                next_idx = min(
                    len(SHIFT_TIME_OPTIONS) - 1,
                    SHIFT_TIME_OPTIONS.index(shift_start) + 2,
                )
                shift_end = SHIFT_TIME_OPTIONS[next_idx]
            st.session_state["filter_shift_range"] = (shift_start, shift_end)
            st.caption(f"🕒 Active shift: **{shift_start} – {shift_end}**")

            pending_toggle_sync = st.session_state.pop(
                "_pending_filter_toggle_sync", None
            )
            if pending_toggle_sync:
                st.session_state["filter_include_extended_widget"] = (
                    pending_toggle_sync["include_extended"]
                )
                st.session_state["filter_allow_weekends_widget"] = (
                    pending_toggle_sync["allow_weekends"]
                )
            else:
                st.session_state.setdefault(
                    "filter_include_extended_widget",
                    bool(st.session_state.get("filter_include_extended", False)),
                )
                st.session_state.setdefault(
                    "filter_allow_weekends_widget",
                    bool(st.session_state.get("filter_allow_weekends", False)),
                )
            allow_weekends = bool(
                st.session_state["filter_allow_weekends_widget"]
            )
            st.session_state["filter_include_extended"] = bool(
                st.session_state["filter_include_extended_widget"]
            )
            start_date, end_date = _render_date_picker(allow_weekends)
            include_extended = st.toggle(
                "Allow extended shifts",
                key="filter_include_extended_widget",
                help="Unlock +-2h extended shift windows",
            )
            allow_weekends = st.toggle(
                "Include weekends",
                key="filter_allow_weekends_widget",
                help="Include Saturday and Sunday in availability searches",
            )
            st.session_state["filter_include_extended"] = bool(include_extended)
            st.session_state["filter_allow_weekends"] = bool(allow_weekends)

            current_filters = {
                "shift_start": shift_start,
                "shift_end": shift_end,
                "start_date": start_date,
                "deadline_date": end_date,
                "include_extended": include_extended,
                "allow_weekends": allow_weekends,
            }
            previous_filters = st.session_state.get(
                "_last_applied_search_filters",
                st.session_state.get("search_settings"),
            )
            st.session_state.search_settings = current_filters.copy()
            _refresh_candidates_if_filters_changed(
                current_filters,
                previous_filters,
            )

            st.markdown('<div class="hil-filter-spacer"></div>', unsafe_allow_html=True)
            if st.button(
                "🗑️ Reset Session",
                use_container_width=True,
                key="reset_session_button",
            ):
                reset_session_state()
                st.rerun()

    nav_info = nav_info or {}
    return {
        **nav_info,
        "timezone": timezone,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "simulated_date": start_date,
        "deadline_date": end_date,
    }


def _five_active_dates(start_date: date, allow_weekends: bool) -> list[date]:
    days: list[date] = []
    cursor = start_date
    while len(days) < 5:
        if allow_weekends or cursor.weekday() < 5:
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


def _render_date_picker(allow_weekends: bool) -> tuple[str, str]:
    start_date_text = st.session_state.get(
        "filter_start_date", "2026-10-15"
    )
    try:
        start_date = date.fromisoformat(str(start_date_text))
    except ValueError:
        logger.warning(
            "Invalid filter start date; restoring default: %r",
            start_date_text,
        )
        start_date = date(2026, 10, 15)
        st.session_state["filter_start_date"] = start_date.isoformat()
    if "filter_start_date_picker" not in st.session_state:
        st.session_state["filter_start_date_picker"] = start_date
    chosen_start = st.date_input(
        "Currently searching slots from:",
        key="filter_start_date_picker",
        help="First date to check for rig availability",
    )
    st.session_state["filter_start_date"] = chosen_start.isoformat()
    active_days = _five_active_dates(chosen_start, allow_weekends)
    end_date = active_days[-1]
    st.session_state["filter_end_date"] = end_date.isoformat()
    st.markdown(
        f'<div class="hil-date-range">📅 {active_days[0]:%b %d} – '
        f'{end_date:%b %d, %Y} (5 active days)</div>',
        unsafe_allow_html=True,
    )
    return chosen_start.isoformat(), end_date.isoformat()


def _refresh_candidates_if_filters_changed(
    filters: dict[str, Any],
    previous: dict[str, Any] | None = None,
) -> None:
    if previous is None:
        previous = st.session_state.get("_last_applied_search_filters")
    changed = previous is not None and any(
        previous.get(key) != value for key, value in filters.items()
    )
    st.session_state["_last_applied_search_filters"] = filters.copy()
    matched_rigs = st.session_state.get("matched_rigs", [])
    if not changed or not matched_rigs:
        return

    rig_ids = list(
        dict.fromkeys(
            str(rig.get("rig_id", rig.get("Rig_ID", ""))).strip()
            for rig in matched_rigs
            if rig.get("rig_id") or rig.get("Rig_ID")
        )
    )
    if not rig_ids:
        return
    try:
        repository = get_repository()
        context = st.session_state.get("slot_search_context", {})
        result = SlotSchedulerService(repository).find_free_slots(
            rig_ids=rig_ids,
            start_date=filters["start_date"],
            deadline_date=filters["deadline_date"],
            shift_start=filters["shift_start"],
            shift_end=filters["shift_end"],
            include_extended=filters["include_extended"],
            allow_weekends=filters["allow_weekends"],
        )
        candidates = result["standard_slots"][:]
        if filters["include_extended"]:
            candidates.extend(result["extended_slots"])
        from src.agent.tools.scheduling_tools import (
            _auto_select_proposed_split,
            _enrich_slots,
        )

        st.session_state.candidate_slots = _enrich_slots(candidates)
        st.session_state["_turn_candidate_slots"] = list(
            st.session_state.candidate_slots
        )
        st.session_state["selected_slot_keys"] = _auto_select_proposed_split(
            st.session_state.candidate_slots,
            float(st.session_state.get("target_duration_hours", 0.0)),
        )
        st.session_state.pop("candidate_slot_editor", None)
        st.session_state["slot_search_context"] = {
            **context,
            "rig_ids": rig_ids,
            "start_date": filters["start_date"],
            "deadline_date": filters["deadline_date"],
            "shift_start": filters["shift_start"],
            "shift_end": filters["shift_end"],
            "include_extended": filters["include_extended"],
            "allow_weekends": filters["allow_weekends"],
        }
    except Exception:
        logger.exception("Live availability refresh failed for changed UI filters.")
        st.warning("Availability could not be refreshed. Check the diagnostic log.")


def _render_log_download(label: str, log_path: Any) -> None:
    st.caption(f"{label.removeprefix('Download ')}: `{log_path}`")
    if not log_path.is_file():
        return
    try:
        log_data = log_path.read_bytes()
    except OSError:
        logger.exception("Unable to read log for download: path=%s", log_path)
        st.warning(f"{label} is unavailable. Check the app console.")
        return
    st.download_button(
        label,
        data=log_data,
        file_name=log_path.name,
        mime="application/x-ndjson" if "Benchmark" in label else "text/plain",
        use_container_width=True,
    )
