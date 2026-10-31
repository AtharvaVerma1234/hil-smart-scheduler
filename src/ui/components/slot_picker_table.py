"""Right-panel rig recommendations, booking summary, and weekly calendars."""

from contextlib import nullcontext
from datetime import date, datetime, timedelta
from html import escape
import re
from typing import Any

import pandas as pd
import streamlit as st
from google.genai import types

from src.config.constants import SlotType
from src.config.settings import LLM_PROVIDER
from src.repositories import get_repository
from src.services.booking_service import BookingService
from src.utils.logging_config import get_logger
from src.utils.time_utils import extended_windows

logger = get_logger(__name__)


SLOT_TYPE_OPTIONS = [
    "-- Select Slot Type --",
    "MANUAL_TESTING",
    "TEST_PROVEOUT",
    "AUTOMATED_END_TO_END_EXECUTION",
    "DEBUGGING",
    "TRIAGING",
    "RIG_MAINTENANCE",
]

_STATUS_STYLES = {
    "Booked": ("#2E6BE6", "#2E6BE6"),
    "Selected": ("#E11D74", "#FF6AC1"),
    "Available": ("#7CB342", "#7CB342"),
}


def render_slot_picker(user_id: str, container: Any = None) -> None:
    """Render the matched/booking and weekly-calendar right-panel views."""
    target = nullcontext() if container is None else container
    with target:
        _render_view_toggle()
        right_scroll = st.container(height=360, border=True)
        with right_scroll:
            if st.session_state.get("right_panel_view", "Matched & Booking") == "Weekly Calendars":
                _render_weekly_calendars()
            else:
                _render_matched_and_booking()
        _render_booking_footer(user_id)


def _set_right_view(view_name: str) -> None:
    st.session_state["right_panel_view"] = view_name


def _render_view_toggle() -> None:
    with st.container(key="right_panel_view_toggle"):
        left, right = st.columns(2)
        active = st.session_state.get("right_panel_view", "Matched & Booking")
        left.button(
            "📊 Matched & Booking",
            key="right_panel_matched_button",
            type="primary" if active == "Matched & Booking" else "secondary",
            use_container_width=True,
            on_click=_set_right_view,
            args=("Matched & Booking",),
        )
        right.button(
            "📅 Weekly Calendars",
            key="right_panel_calendar_button",
            type="primary" if active == "Weekly Calendars" else "secondary",
            use_container_width=True,
            on_click=_set_right_view,
            args=("Weekly Calendars",),
        )


def _render_matched_and_booking() -> None:
    with st.container(border=True):
        _render_matched_rigs()
    with st.container(border=True):
        _render_selected_bookings()


def _render_matched_rigs() -> None:
    st.markdown(
        '<div class="hil-section-title">Matched Rigs</div>',
        unsafe_allow_html=True,
    )
    rigs = st.session_state.get("matched_rigs", [])
    if rigs:
        rows = []
        for rig in rigs:
            rig_id = escape(str(rig.get("rig_id", rig.get("Rig_ID", ""))))
            platform = escape(_platform_name(rig))
            score = _score(rig.get("match_score", 0))
            filled = max(1, round(score / 100 * 6)) if score > 0 else 0
            color = (
                "#A6E22E"
                if score >= 80
                else "#E6DB74"
                if score >= 70
                else "#FD971F"
            )
            segments = "".join(
                f'<span style="display:inline-block;width:9px;height:7px;'
                f'margin-right:2px;border-radius:2px;background:'
                f'{color if index < filled else "#3A3D45"}"></span>'
                for index in range(6)
            )
            summary = escape(_hardware_summary(rig))
            rows.append(
                "<tr>"
                f'<td class="hil-rig-name">{rig_id}</td>'
                f"<td>{platform}</td>"
                f'<td><div style="white-space:nowrap">{segments} '
                f'<span style="color:{color};font-weight:700">{score:.0f}%</span></div></td>'
                f'<td class="hil-hardware-summary">{summary} <span style="color:#66D9EF">›</span></td>'
                "</tr>"
            )
        st.markdown(
            """
            <div class="hil-match-table-wrap"><table class="hil-match-table">
            <thead><tr><th>rig_name</th><th>rig_platform</th><th>percentage_match</th>
            <th>what's missing here if anything at all</th></tr></thead>
            <tbody>"""
            + "".join(rows)
            + "</tbody></table></div>",
            unsafe_allow_html=True,
        )
        with st.expander("🔍 View Full ECU & Rig Engineer Breakdown"):
            for rig in rigs:
                rig_id = str(rig.get("rig_id", rig.get("Rig_ID", "Unknown rig")))
                _render_rig_breakdown(rig, rig_id)
    else:
        st.caption("Rig recommendations will appear here after discovery.")


def _render_selected_bookings() -> None:
    st.markdown(
        '<div class="hil-section-title">Selected Bookings</div>',
        unsafe_allow_html=True,
    )
    st.caption("Confirm the following time slots to proceed with booking.")
    selected = _selected_slots()
    left, right = st.columns([2.3, 1.1])
    selected_hours = sum(_slot_duration(slot) for slot in selected)
    target = float(st.session_state.get("target_duration_hours", 0.0))
    with left:
        if selected:
            for slot in selected:
                day = datetime.strptime(slot["date"], "%Y-%m-%d").strftime("%a")
                duration = _slot_duration(slot)
                st.markdown(
                    f"""
                    <div class="hil-selected-booking">
                      <span class="hil-selected-check">✓</span>
                      <div class="hil-selected-details">
                        <strong>{escape(slot["rig_id"])} ({escape(_platform_for_rig(slot["rig_id"]))})</strong>
                        <div>{escape(slot["date"])} ({day}) ·
                          {escape(slot["start_time"])} - {escape(slot["end_time"])}
                          ({duration:.1f} hrs)</div>
                      </div>
                      <span class="hil-selected-pill">Selected</span>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        else:
            st.caption("Select suggested slots in the chat table to stage a booking.")
    with right:
        st.markdown(
            '<div class="hil-proposed-pill">🎯 Proposed Split</div>'
            '<div class="hil-total-label">Total duration</div>'
            f'<div class="hil-total-value">{selected_hours:.1f} '
            f'<span>/ {target:.1f} hrs</span></div>',
            unsafe_allow_html=True,
        )


def _render_rig_breakdown(rig: dict, rig_id: str) -> None:
    platform = _platform_name(rig)
    program = rig.get("vehicle_program", rig.get("Vehicle_Program", ""))
    domain = rig.get("rig_domain", rig.get("Rig_Domain", ""))
    engineer = rig.get("rig_engineer", rig.get("Rig_Engineer", ""))
    badges = [
        ("Rig", rig_id),
        ("Platform", platform),
        ("Program", program),
        ("Domain", domain),
        ("Engineer", engineer),
    ]
    badge_html = "".join(
        f'<span class="hil-meta-badge"><b>{escape(label)}:</b> '
        f'{escape(str(value or "—"))}</span>'
        for label, value in badges
    )
    ecu_columns = [
        (
            "Real Connected ECUs",
            "#A6E22E",
            rig.get("real_ecus", rig.get("Real_Connected_Components", [])),
        ),
        (
            "CAN Sim ECUs",
            "#66D9EF",
            rig.get("can_sim_ecus", rig.get("CAN_Sim_ECUs", [])),
        ),
        (
            "Eth Sim ECUs",
            "#AE81FF",
            rig.get("eth_sim_ecus", rig.get("Eth_Sim_ECUs", [])),
        ),
    ]
    ecu_cells = []
    for label, color, values in ecu_columns:
        pills = "".join(
            f'<span class="hil-ecu-pill" style="color:{color};border-color:{color}">'
            f"{escape(str(value))}</span>"
            for value in _display_values(values)
        )
        ecu_cells.append(
            f'<td><div class="hil-ecu-heading" style="color:{color}">{label}</div>'
            f'<div class="hil-ecu-pills">{pills or "—"}</div></td>'
        )
    html = (
        '<div class="hil-breakdown-card">'
        f'<div class="hil-meta-badges">{badge_html}</div>'
        '<table class="hil-ecu-table"><tbody><tr>'
        + "".join(ecu_cells)
        + "</tr></tbody></table>"
    )
    breakdown = rig.get("ecu_breakdown", [])
    if breakdown:
        html += (
            '<table class="hil-breakdown-table"><thead><tr>'
            "<th>ECU</th><th>Required</th><th>Available</th>"
            "</tr></thead><tbody>"
        )
        for item in breakdown:
            if not isinstance(item, dict):
                continue
            ecu = item.get("ecu", item.get("ECU", ""))
            required = item.get("required", "")
            available = item.get("available", "")
            html += (
                "<tr>"
                f"<td>{escape(str(ecu))}</td>"
                f"<td>{escape(str(required))}</td>"
                f"<td>{escape(str(available))}</td>"
                "</tr>"
            )
        html += "</tbody></table>"
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def _display_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [item.strip() for item in re.split(r"[,;|]", text) if item.strip()]


def build_rig_day_timeline(
    rig_id: str,
    date_text: str,
    cal_start: str,
    cal_end: str,
    bookings_df: pd.DataFrame,
    selected_slots: list[dict],
) -> list[dict]:
    """Partition a rig-day calendar into contiguous booked, selected, and free blocks."""
    window_start = _minutes(cal_start)
    window_end = _minutes(cal_end)
    if window_end <= window_start:
        return []

    occupied: list[tuple[int, int, str]] = []
    for _, booking in bookings_df.iterrows():
        booking_rig = str(_value(booking, "Rig_ID", "rig_id"))
        booking_date = _date_text(_value(booking, "Date", "date"))
        if booking_rig != rig_id or booking_date != date_text:
            continue
        start = _minutes(_value(booking, "Slot_Start_Time", "start_time"))
        end = _minutes(_value(booking, "Slot_End_Time", "end_time"))
        clipped = _clip_interval(start, end, window_start, window_end)
        if clipped:
            occupied.append((clipped[0], clipped[1], "Booked"))

    for slot in selected_slots:
        if str(slot.get("rig_id", "")) != rig_id or str(slot.get("date", "")) != date_text:
            continue
        start = _minutes(slot["start_time"])
        end = _minutes(slot["end_time"])
        clipped = _clip_interval(start, end, window_start, window_end)
        if clipped:
            occupied.append((clipped[0], clipped[1], "Selected"))

    boundaries = {window_start, window_end}
    for start, end, _ in occupied:
        boundaries.update((start, end))
    ordered = sorted(boundaries)
    blocks: list[dict] = []
    for start, end in zip(ordered, ordered[1:]):
        if end <= start:
            continue
        statuses = [
            status
            for occupied_start, occupied_end, status in occupied
            if occupied_start <= start and occupied_end >= end
        ]
        status = "Booked" if "Booked" in statuses else "Selected" if "Selected" in statuses else "Available"
        block = {
            "rig_id": rig_id,
            "date": date_text,
            "start_time": _clock(start),
            "end_time": _clock(end),
            "duration_hrs": (end - start) / 60.0,
            "status": status,
            "color": _STATUS_STYLES[status][0],
            "border_color": _STATUS_STYLES[status][1],
            "height_px": max(22, round(((end - start) / 60.0) * 24)),
        }
        if blocks and blocks[-1]["status"] == status:
            blocks[-1]["end_time"] = block["end_time"]
            blocks[-1]["duration_hrs"] += block["duration_hrs"]
            blocks[-1]["height_px"] = max(
                22, round(blocks[-1]["duration_hrs"] * 24)
            )
        else:
            blocks.append(block)
    return blocks


def _render_weekly_calendars() -> None:
    st.markdown(
        '<div class="hil-calendar-legend">'
        '<span style="color:#7CB342">●</span> Available&nbsp;&nbsp;&nbsp; '
        '<span style="color:#2E6BE6">●</span> Booked&nbsp;&nbsp;&nbsp; '
        '<span style="color:#F92672">●</span> Selected</div>',
        unsafe_allow_html=True,
    )
    rigs = st.session_state.get("matched_rigs", [])
    if not rigs:
        st.caption("Rig recommendations will appear here after discovery.")
        return
    settings = st.session_state.get("search_settings", {})
    start_text = (
        settings.get("start_date")
        or st.session_state.get("filter_start_date")
        or "2026-10-15"
    )
    start_date = date.fromisoformat(str(start_text))
    allow_weekends = bool(settings.get("allow_weekends", False))
    dates = _active_dates(start_date, allow_weekends)
    include_extended = bool(settings.get("include_extended", False))
    shift_start = str(settings.get("shift_start", "09:00"))
    shift_end = str(settings.get("shift_end", "18:00"))
    if include_extended:
        windows = extended_windows(shift_start, shift_end)
        cal_start, cal_end = windows[0][0], windows[-1][1]
    else:
        cal_start, cal_end = shift_start, shift_end
    bookings = get_repository().get_bookings()

    for index, rig in enumerate(rigs):
        rig_id = str(rig.get("rig_id", rig.get("Rig_ID", "")))
        platform = _platform_name(rig)
        with st.expander(
            f"🟢 {rig_id} ({platform})",
            expanded=index < 2,
        ):
            _render_rig_calendar(
                rig_id,
                dates,
                cal_start,
                cal_end,
                bookings,
            )
            _render_selected_slot_resizers(rig_id)
    target = float(st.session_state.get("target_duration_hours", 0.0))
    selected_hours = sum(_slot_duration(slot) for slot in _selected_slots())
    st.caption(f"Total Selected: {selected_hours:.1f} / {target:.1f} hrs")


def _render_rig_calendar(
    rig_id: str,
    dates: list[date],
    cal_start: str,
    cal_end: str,
    bookings_df: pd.DataFrame,
) -> None:
    columns = st.columns([0.42, *([1] * len(dates))])
    total_height = max(22, round((_minutes(cal_end) - _minutes(cal_start)) / 60 * 24))
    labels = []
    for time_label in ("09:00", "12:00", "15:00", "18:00", "20:00"):
        position = (
            (_minutes(time_label) - _minutes(cal_start))
            / max(1, _minutes(cal_end) - _minutes(cal_start))
            * total_height
        )
        if 0 <= position <= total_height:
            labels.append(
                f'<span style="position:absolute;top:{round(position)}px;left:0">'
                f"{time_label}</span>"
            )
    columns[0].markdown(
        '<div class="hil-calendar-day">&nbsp;</div>'
        f'<div class="hil-calendar-axis" style="height:{total_height}px">'
        f'{"".join(labels)}</div>',
        unsafe_allow_html=True,
    )
    for day_index, day in enumerate(dates, start=1):
        blocks = build_rig_day_timeline(
            rig_id,
            day.isoformat(),
            cal_start,
            cal_end,
            bookings_df,
            _selected_slots(),
        )
        html_blocks = []
        for block in blocks:
            height = block["height_px"]
            if block["status"] == "Selected":
                text = (
                    f'✓ Selected<br>{block["start_time"]} - {block["end_time"]}'
                    f'<br>({block["duration_hrs"]:.1f} hrs)'
                )
            elif block["status"] == "Booked":
                text = f'Booked<br>{block["start_time"]} - {block["end_time"]}'
            else:
                text = "Available"
            html_blocks.append(
                f'<div class="hil-timeline-block" style="height:{height}px;'
                f'background:{block["color"]};border-color:{block["border_color"]}">'
                f"{text}</div>"
            )
        day_label = day.strftime("%a")
        with columns[day_index]:
            st.markdown(
                f'<div class="hil-calendar-day">{day_label}<br>'
                f'<span>{day.strftime("%b %d")}</span></div>'
                f'<div class="hil-calendar-track">{"".join(html_blocks)}</div>',
                unsafe_allow_html=True,
            )


def _stable_slider_key(slot_key: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", slot_key)
    return f"resize_{sanitized}_slider"


def _render_selected_slot_resizers(rig_id: str) -> None:
    selected = [
        slot
        for slot in _selected_slots()
        if str(slot.get("rig_id", "")) == rig_id
    ]
    for slot in selected:
        slot_key = _slot_key(slot)
        slider_key = _stable_slider_key(slot_key)
        original_start = _minutes(slot.get("orig_start_time", slot["start_time"]))
        original_end = _minutes(slot.get("orig_end_time", slot["end_time"]))
        options = [
            _clock(minute)
            for minute in range(original_start, original_end + 1, 30)
        ]
        if not options or options[-1] != _clock(original_end):
            options.append(_clock(original_end))
        current_start = str(slot["start_time"])
        current_end = str(slot["end_time"])
        if current_start not in options:
            current_start = options[0]
        if current_end not in options:
            current_end = options[-1]
        if _minutes(current_end) <= _minutes(current_start):
            current_end = next(
                (value for value in options if _minutes(value) > _minutes(current_start)),
                options[-1],
            )
        existing_val = st.session_state.get(slider_key)
        if existing_val is not None and (
            not isinstance(existing_val, (tuple, list))
            or len(existing_val) != 2
            or existing_val[0] not in options
            or existing_val[1] not in options
            or _minutes(existing_val[1]) <= _minutes(existing_val[0])
        ):
            st.session_state.pop(slider_key, None)
        st.caption(
            f'Resize {slot["rig_id"]} · {slot["date"]} · '
            f'{slot["orig_start_time"]}–{slot["orig_end_time"]}'
        )
        left, slider_col, right = st.columns([0.7, 4, 0.7])
        left.button(
            "−0.5h",
            key=f"{slider_key}_decrease",
            disabled=_minutes(current_end) - _minutes(current_start) <= 30,
            on_click=_resize_selected_slot,
            args=(slot_key, slider_key, -30),
        )
        with slider_col:
            st.select_slider(
                "Selected interval",
                options=options,
                value=(current_start, current_end),
                key=slider_key,
                label_visibility="collapsed",
                on_change=_selected_interval_changed,
                args=(slot_key, slider_key),
            )
        right.button(
            "+0.5h",
            key=f"{slider_key}_increase",
            disabled=_minutes(current_end) >= original_end,
            on_click=_resize_selected_slot,
            args=(slot_key, slider_key, 30),
        )


def _selected_interval_changed(slot_key: str, slider_key: str) -> None:
    selected_range = st.session_state.get(slider_key)
    if not isinstance(selected_range, (tuple, list)) or len(selected_range) != 2:
        return
    start, end = str(selected_range[0]), str(selected_range[1])
    if _minutes(end) <= _minutes(start):
        slot = next(
            (
                candidate
                for candidate in st.session_state.get("candidate_slots", [])
                if _slot_key(candidate) == slot_key
            ),
            None,
        )
        original_end = (
            _minutes(slot.get("orig_end_time", end))
            if slot
            else _minutes(start) + 30
        )
        end = _clock(min(original_end, _minutes(start) + 30))
        st.session_state[slider_key] = (start, end)
    st.session_state["_calendar_slider_just_updated"] = True
    _update_slot(slot_key, start, end)


def _resize_selected_slot(
    slot_key: str,
    slider_key: str,
    delta_minutes: int,
) -> None:
    slot = next(
        (
            candidate
            for candidate in st.session_state.get("candidate_slots", [])
            if _slot_key(candidate) == slot_key
        ),
        None,
    )
    if slot is None:
        return
    original_end = _minutes(slot.get("orig_end_time", slot["end_time"]))
    start = _minutes(slot["start_time"])
    current_end = _minutes(slot["end_time"])
    new_end = min(original_end, max(start + 30, current_end + delta_minutes))
    new_range = (str(slot["start_time"]), _clock(new_end))
    st.session_state[slider_key] = new_range
    st.session_state[f"{slider_key}_slider"] = new_range
    st.session_state["_calendar_slider_just_updated"] = True
    _update_slot(slot_key, *new_range)


def _update_slot(slot_key: str, start: str, end: str) -> None:
    start_minute, end_minute = _minutes(start), _minutes(end)
    if end_minute <= start_minute:
        return
    for slot in st.session_state.get("candidate_slots", []):
        if _slot_key(slot) == slot_key:
            slot["start_time"] = start
            slot["end_time"] = end
            slot["duration_hrs"] = round(
                (end_minute - start_minute) / 60.0, 2
            )
            break
    st.session_state.pop("candidate_slot_editor", None)


def _render_booking_footer(user_id: str) -> None:
    pending_type = st.session_state.pop("_pending_booking_slot_type", None)
    if pending_type in SLOT_TYPE_OPTIONS:
        st.session_state["booking_slot_type"] = pending_type
    elif "booking_slot_type" not in st.session_state:
        st.session_state["booking_slot_type"] = (
            st.session_state.get("selected_slot_type")
            if st.session_state.get("selected_slot_type") in SLOT_TYPE_OPTIONS
            else SLOT_TYPE_OPTIONS[0]
        )
    selected_type = st.selectbox(
        "Slot Type (Mandatory for Booking)",
        options=SLOT_TYPE_OPTIONS,
        key="booking_slot_type",
    )
    if selected_type != SLOT_TYPE_OPTIONS[0]:
        st.session_state.selected_slot_type = selected_type
    with st.container(key="ciara_booking_cta"):
        if st.button(
            "🚀 Confirm & Book in CIARA",
            type="primary",
            use_container_width=True,
            key="confirm_ciara_booking",
        ):
            selected = _selected_slots()
            if not selected:
                st.error("Please select at least one slot before booking.")
                return
            if selected_type == SLOT_TYPE_OPTIONS[0] or selected_type not in {
                item.value for item in SlotType
            }:
                st.error("Please select a mandatory Slot Type before booking.")
                return
            bookings = [
                {
                    "rig_id": str(slot["rig_id"]),
                    "date": str(slot["date"]),
                    "start_time": str(slot["start_time"]).strip(),
                    "end_time": str(slot["end_time"]).strip(),
                    "orig_start_time": str(
                        slot.get("orig_start_time", slot["start_time"])
                    ),
                    "orig_end_time": str(
                        slot.get("orig_end_time", slot["end_time"])
                    ),
                }
                for slot in selected
            ]
            try:
                result = BookingService(get_repository()).validate_and_book_slots(
                    bookings, selected_type, user_id
                )
            except (ValueError, FileNotFoundError) as exc:
                logger.warning(
                    "Booking form validation/persistence failed: exception_type=%s message=%s",
                    type(exc).__name__,
                    exc,
                )
                st.error(str(exc))
                return
            booking_ids = result["booking_ids"]
            if booking_ids:
                _append_booking_history_notice(bookings, booking_ids, selected_type)
            st.session_state.pending_booking_follow_up = (
                f"Booking confirmed: {', '.join(booking_ids)}. "
                "Do you need any further assistance?"
            )
            st.session_state.candidate_slots = []
            st.session_state["selected_slot_keys"] = []
            st.session_state.pop("candidate_slot_editor", None)
            st.success(
                f"Booking confirmed. New Booking IDs: {', '.join(booking_ids)}"
            )
            st.rerun()


def _selected_slots() -> list[dict]:
    keys = set(st.session_state.get("selected_slot_keys", []))
    return [
        slot
        for slot in st.session_state.get("candidate_slots", [])
        if _slot_key(slot) in keys
    ]


def _slot_key(slot: dict) -> str:
    return (
        f'{slot["rig_id"]}|{slot["date"]}|'
        f'{slot.get("orig_start_time", slot["start_time"])}|'
        f'{slot.get("orig_end_time", slot["end_time"])}'
    )


def _slot_duration(slot: dict) -> float:
    return _duration_or_zero(slot.get("start_time", ""), slot.get("end_time", ""))


def _platform_name(rig: dict) -> str:
    raw = str(rig.get("platform", rig.get("Rig_Platform", "")))
    lower = raw.casefold()
    if "vector" in lower:
        return "Vector"
    if lower in {"ni", "national instruments"} or "national instruments" in lower:
        return "NI"
    if "dspace" in lower:
        return "dSPACE"
    return raw or "—"


def _platform_for_rig(rig_id: str) -> str:
    for rig in st.session_state.get("matched_rigs", []):
        if str(rig.get("rig_id", rig.get("Rig_ID", ""))) == rig_id:
            return _platform_name(rig)
    return "—"


def _hardware_summary(rig: dict) -> str:
    items = []
    for key in ("missing", "downgrades", "smart_upgrades"):
        value = rig.get(key) or []
        if isinstance(value, str):
            value = [value]
        for item in value:
            if isinstance(item, dict):
                text = item.get("ecu") or item.get("name") or item.get("description")
                if text:
                    items.append(str(text))
            else:
                items.append(str(item))
    unique = list(dict.fromkeys(items))
    return ", ".join(unique[:3]) if unique else "All required modules available"


def _score(value: Any) -> float:
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def _active_dates(
    start_date: date,
    allow_weekends: bool,
) -> list[date]:
    result: list[date] = []
    cursor = start_date
    while len(result) < 5:
        if allow_weekends or cursor.weekday() < 5:
            result.append(cursor)
        cursor += timedelta(days=1)
    return result


def _minutes(value: Any) -> int:
    text = str(value).strip()
    try:
        parsed = datetime.strptime(text, "%H:%M")
    except ValueError:
        parsed = datetime.strptime(text, "%H:%M:%S")
    return parsed.hour * 60 + parsed.minute


def _clock(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"


def _clip_interval(
    start: int,
    end: int,
    window_start: int,
    window_end: int,
) -> tuple[int, int] | None:
    clipped_start = max(start, window_start)
    clipped_end = min(end, window_end)
    return (
        (clipped_start, clipped_end)
        if clipped_end > clipped_start
        else None
    )


def _value(row: pd.Series, *keys: str) -> str:
    for key in keys:
        if key in row and pd.notna(row[key]):
            return str(row[key])
    return ""


def _date_text(value: Any) -> str:
    text = str(value).strip()
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        try:
            return pd.to_datetime(text).date().isoformat()
        except (TypeError, ValueError):
            return text


def _append_booking_history_notice(
    bookings: list[dict[str, Any]],
    booking_ids: list[str],
    slot_type: str,
) -> None:
    """Add a confirmed booking event to the active agent conversation."""
    booking_lines = []
    for booking_id, booking in zip(booking_ids, bookings):
        booking_lines.append(
            f"- booking_id={booking_id}, rig_id={booking['rig_id']}, "
            f"date={booking['date']}, start_time={booking['start_time']}, "
            f"end_time={booking['end_time']}, selected_type={slot_type}"
        )
    notice = (
        "System Notice (confirmed booking state from the application): "
        f"Booking was successfully persisted with selected_type={slot_type}. "
        "These intervals are now occupied and must not be offered as available:\n"
        + "\n".join(booking_lines)
    )
    if LLM_PROVIDER == "ollama":
        history = st.session_state.setdefault("ollama_history", [])
        history.append({"role": "user", "content": notice})
        confirmation = (
            f"Booking confirmed: {', '.join(booking_ids)}. "
            "Do you need any further assistance?"
        )
        history.append({"role": "assistant", "content": confirmation})
    else:
        history = st.session_state.setdefault("agent_history", [])
        history.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=notice)],
            )
        )
        confirmation = (
            f"Booking confirmed: {', '.join(booking_ids)}. "
            "Do you need any further assistance?"
        )
        history.append(
            types.Content(
                role="model",
                parts=[types.Part.from_text(text=confirmation)],
            )
        )
    st.session_state["target_duration_hours"] = 0.0
    st.session_state["last_booking_message_index"] = (
        len(st.session_state.get("messages", [])) + 1
    )
    logger.info(
        "Confirmed booking context appended to agent history: provider=%s booking_count=%d "
        "booking_ids=%s slot_type=%s",
        LLM_PROVIDER,
        len(booking_ids),
        booking_ids,
        slot_type,
    )


def _duration_or_zero(start: str, end: str) -> float:
    try:
        start_time = datetime.strptime(start.strip(), "%H:%M")
        end_time = datetime.strptime(end.strip(), "%H:%M")
    except (ValueError, AttributeError):
        return 0.0
    return round((end_time - start_time).total_seconds() / 3600.0, 2)
