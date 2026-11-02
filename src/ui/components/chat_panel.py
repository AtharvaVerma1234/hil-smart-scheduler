"""Monokai-styled persistent chat and suggested slot selector."""

import re
from datetime import datetime

import pandas as pd

import streamlit as st

_CODE_BLOCK_RE = re.compile(r"(```[\s\S]*?```|`[^`]+`)")
_ENTITY_RE = re.compile(
    r"\b(?:FEATURE_\d+|VEHICLE_PROGRAM_\d+|RIG_0*\d+|ECU\d+|ENG_\d+|"
    r"USER_\d+|BK_\d+|\d+(?:\.\d+)?\s*(?:hours?|hrs?|minutes?|mins?))\b",
    re.IGNORECASE,
)


def _highlight_entities(text: str) -> str:
    """Highlight domain identifiers and durations without changing code spans."""
    parts = _CODE_BLOCK_RE.split(text)
    for index, part in enumerate(parts):
        if part.startswith("`"):
            continue
        parts[index] = _ENTITY_RE.sub(
            r'<span style="color: #E6DB74; font-weight: 600;">\g<0></span>',
            part,
        )
    return "".join(parts)


def render_chat_header() -> None:
    """Render the chat panel title and concise product description."""
    st.markdown(
        """
        <div class="hil-chat-header">
          <div class="hil-chip-badge">⌘</div>
          <div>
            <div class="hil-chat-title">HIL Rig Discovery &amp; Scheduler</div>
            <div class="hil-chat-subtitle">
              Find compatible rigs and schedule them efficiently for your test requirements.
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_chat_history() -> None:
    """Render persistent user and assistant messages as Monokai cards."""
    for message in st.session_state.get("messages", []):
        role = message.get("role", "assistant")
        content = str(message.get("content", ""))
        if role == "user":
            st.markdown(
                f"""
                <div class="hil-user-row">
                  <div class="hil-user-bubble">{_highlight_entities(content)}</div>
                  <div class="hil-user-avatar">AV</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            with st.container(border=True):
                avatar, body = st.columns([0.45, 9.55])
                with avatar:
                    st.markdown(
                        '<div class="hil-assistant-avatar">✦</div>',
                        unsafe_allow_html=True,
                    )
                with body:
                    st.markdown(
                        '<div class="hil-assistant-label">AI Assistant</div>',
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"\n\n{_highlight_entities(content)}\n\n",
                        unsafe_allow_html=True,
                    )
            if message.get("tool_trace"):
                with st.expander("Agent Tool Trace", expanded=False):
                    st.json(message["tool_trace"])


def render_chat_slot_selector() -> None:
    """Render and synchronize editable candidate slots below the chat history."""
    slots = st.session_state.get("candidate_slots", [])
    if not slots:
        return

    selected_keys = set(st.session_state.get("selected_slot_keys", []))
    rows = []
    for slot in slots:
        start = slot.get("start_time", "")
        end = slot.get("end_time", "")
        original_start = slot.get("orig_start_time", start)
        original_end = slot.get("orig_end_time", end)
        slot_key = (
            f'{slot["rig_id"]}|{slot["date"]}|{original_start}|{original_end}'
        )
        day = datetime.strptime(slot["date"], "%Y-%m-%d").strftime("%A")
        rows.append(
            {
                "Select": slot_key in selected_keys,
                "rig_id": slot["rig_id"],
                "Rig_Details": slot.get("rig_details", ""),
                "date": f'{slot["date"]} ({day})',
                "start_time": start,
                "end_time": end,
                "duration_hrs": _duration_or_zero(start, end),
                "window_type": slot.get("window_type", ""),
                "orig_start_time": original_start,
                "orig_end_time": original_end,
                "slot_key": slot_key,
            }
        )
    frame = pd.DataFrame(rows)
    edited = st.data_editor(
        frame,
        key="candidate_slot_editor",
        hide_index=True,
        use_container_width=True,
        column_config={
            "Select": st.column_config.CheckboxColumn("Select"),
            "rig_id": st.column_config.TextColumn("Rig", disabled=True),
            "Rig_Details": st.column_config.TextColumn(
                "Rig Details", disabled=True
            ),
            "date": st.column_config.TextColumn("Date", disabled=True),
            "start_time": st.column_config.TextColumn("Start Time (HH:MM)"),
            "end_time": st.column_config.TextColumn("End Time (HH:MM)"),
            "duration_hrs": st.column_config.NumberColumn(
                "Duration (hrs)", disabled=True
            ),
            "window_type": st.column_config.TextColumn("Window", disabled=True),
            "orig_start_time": None,
            "orig_end_time": None,
            "slot_key": None,
        },
    )
    if st.session_state.pop("_calendar_slider_just_updated", False):
        return
    st.session_state["selected_slot_keys"] = [
        str(row["slot_key"])
        for _, row in edited.iterrows()
        if bool(row["Select"])
    ]
    slots_by_key = {
        f'{slot["rig_id"]}|{slot["date"]}|'
        f'{slot.get("orig_start_time", slot["start_time"])}|'
        f'{slot.get("orig_end_time", slot["end_time"])}': slot
        for slot in slots
    }
    for _, row in edited.iterrows():
        slot = slots_by_key.get(str(row["slot_key"]))
        if slot is None:
            continue
        start = str(row["start_time"]).strip()
        end = str(row["end_time"]).strip()
        original_start = str(slot.get("orig_start_time", slot["start_time"]))
        original_end = str(slot.get("orig_end_time", slot["end_time"]))
        duration = _duration_or_zero(start, end)
        if (
            duration < 0.5
            or not _time_is_within(start, original_start, original_end)
            or not _time_is_within(end, original_start, original_end)
            or _parse_time_minutes(end) <= _parse_time_minutes(start)
        ):
            st.toast(
                f"Invalid time edit for {slot['rig_id']}; kept the previous valid interval.",
                icon="⚠️",
            )
            st.session_state.pop("candidate_slot_editor", None)
            st.rerun()
            return
        edited_interval = (start, end)
        current_interval = (
            str(slot.get("start_time", "")),
            str(slot.get("end_time", "")),
        )
        slot["start_time"] = start
        slot["end_time"] = end
        slot["duration_hrs"] = duration
        if edited_interval != current_interval:
            slider_key = (
                "resize_"
                + re.sub(r"[^A-Za-z0-9_]", "_", str(row["slot_key"]))
                + "_slider"
            )
            st.session_state[slider_key] = (start, end)
            st.session_state[f"modal_{slider_key}"] = (start, end)


def _parse_time_minutes(value: str) -> int:
    parsed = datetime.strptime(value.strip(), "%H:%M")
    return parsed.hour * 60 + parsed.minute


def _time_is_within(value: str, original_start: str, original_end: str) -> bool:
    try:
        minute = _parse_time_minutes(value)
        return (
            _parse_time_minutes(original_start)
            <= minute
            <= _parse_time_minutes(original_end)
        )
    except (ValueError, AttributeError):
        return False


def _duration_or_zero(start: str, end: str) -> float:
    try:
        start_time = datetime.strptime(start.strip(), "%H:%M")
        end_time = datetime.strptime(end.strip(), "%H:%M")
    except (ValueError, AttributeError):
        return 0.0
    return round((end_time - start_time).total_seconds() / 3600.0, 2)


def render_chat_input() -> str | None:
    """Render a compact form at the bottom of the chat column."""
    with st.form("chat_input_form", clear_on_submit=True):
        input_col, submit_col = st.columns([5.2, 1.0], vertical_alignment="bottom")
        with input_col:
            message = st.text_input(
                "Message",
                placeholder="e.g., I want to test FEATURE_1 on VEHICLE_PROGRAM_1 for 3 hours...",
                label_visibility="collapsed",
                key="chat_message_input",
            )
        with submit_col:
            submitted = st.form_submit_button(
                "SEND",
                type="primary",
                use_container_width=True,
            )
    return message.strip() if submitted and message.strip() else None
