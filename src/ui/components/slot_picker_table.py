"""Editable candidate slot table and Stage 2 booking controls."""

from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st
from google.genai import types

from src.config.constants import SlotType
from src.config.settings import LLM_PROVIDER
from src.repositories.csv_repository import CSVHILRepository
from src.services.booking_service import BookingService
from src.utils.logging_config import get_logger

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


def render_slot_picker(user_id: str) -> None:
    """Render candidates, validate editable intervals, and book selections."""
    slots = st.session_state.get("candidate_slots", [])
    if not slots:
        st.session_state.pop("candidate_slot_editor", None)
        return
    logger.debug(
        "Rendering slot selector: candidate_count=%d target_duration_hours=%.2f",
        len(slots),
        float(st.session_state.get("target_duration_hours", 0.0)),
    )
    st.subheader("Interactive Slot Selector")
    rig_metadata = {
        str(rig.get("rig_id", rig.get("Rig_ID", ""))): rig
        for rig in st.session_state.get("matched_rigs", [])
    }
    rows = []
    for slot in slots:
        metadata = rig_metadata.get(slot.get("rig_id", ""), {})
        details = slot.get("rig_details") or " | ".join(
            str(value)
            for value in (
                f'{metadata.get("match_score", "")}% Match' if metadata else "",
                metadata.get("platform", metadata.get("Rig_Platform", "")),
                metadata.get("vehicle_program", metadata.get("Vehicle_Program", "")),
                metadata.get("rig_engineer", metadata.get("Rig_Engineer", "")),
            )
            if value
        )
        date_value = datetime.strptime(slot["date"], "%Y-%m-%d").date()
        rows.append(
            {
                "Select": False,
                "rig_id": slot["rig_id"],
                "Rig_Details": details,
                "date": f'{slot["date"]} ({date_value.strftime("%a")})',
                "start_time": slot["start_time"],
                "end_time": slot["end_time"],
                "duration_hrs": _duration_or_zero(
                    slot["start_time"], slot["end_time"]
                ),
                "window_type": slot["window_type"],
                "orig_start_time": slot.get("orig_start_time", slot["start_time"]),
                "orig_end_time": slot.get("orig_end_time", slot["end_time"]),
            }
        )
    frame = pd.DataFrame(rows)
    edited = st.data_editor(
        frame,
        use_container_width=True,
        hide_index=True,
        key="candidate_slot_editor",
        column_config={
            "Select": st.column_config.CheckboxColumn("Select"),
            "rig_id": st.column_config.TextColumn("Rig", disabled=True),
            "Rig_Details": st.column_config.TextColumn("Rig Details", disabled=True),
            "date": st.column_config.TextColumn("Date", disabled=True),
            "start_time": st.column_config.TextColumn("Start Time (HH:MM)"),
            "end_time": st.column_config.TextColumn("End Time (HH:MM)"),
            "duration_hrs": st.column_config.NumberColumn("Duration (hrs)", disabled=True),
            "window_type": st.column_config.TextColumn("Window", disabled=True),
            "orig_start_time": None,
            "orig_end_time": None,
        },
    )
    computed_durations = []
    for _, row in edited.iterrows():
        computed_durations.append(
            _duration_or_zero(str(row["start_time"]), str(row["end_time"]))
        )
    selected_hours = sum(
        hours
        for hours, (_, row) in zip(computed_durations, edited.iterrows())
        if bool(row["Select"])
    )
    target = float(st.session_state.get("target_duration_hours", 0.0))
    progress, booking_type = st.columns(2)
    indicator = "✅" if selected_hours >= target and target > 0 else "⏳"
    progress.metric(
        "Selected Time",
        f"{indicator} {selected_hours:.1f} hrs / Target Requested: {target:.1f} hrs",
    )
    prior_type = st.session_state.get("selected_slot_type")
    default_index = SLOT_TYPE_OPTIONS.index(prior_type) if prior_type in SLOT_TYPE_OPTIONS else 0
    selected_type = booking_type.selectbox(
        "Slot Type (Mandatory for Booking)",
        options=SLOT_TYPE_OPTIONS,
        index=default_index,
        key="booking_slot_type",
    )
    if selected_type != SLOT_TYPE_OPTIONS[0]:
        st.session_state.selected_slot_type = selected_type

    if st.button("✅ Confirm & Book Selected Slots", type="primary"):
        chosen = edited[edited["Select"]]
        if chosen.empty:
            logger.warning("Booking button pressed with no selected availability rows.")
            st.error("Please select at least one slot before booking.")
            return
        if selected_type == SLOT_TYPE_OPTIONS[0] or selected_type not in {
            item.value for item in SlotType
        }:
            logger.warning(
                "Booking button pressed without valid Slot_Type: selected_type=%s",
                selected_type,
            )
            st.error("Please select a mandatory Slot Type before booking.")
            return
        bookings: list[dict[str, Any]] = []
        try:
            for _, row in chosen.iterrows():
                date_text = str(row["date"]).split(" ", 1)[0]
                bookings.append(
                    {
                        "rig_id": str(row["rig_id"]),
                        "date": date_text,
                        "start_time": str(row["start_time"]).strip(),
                        "end_time": str(row["end_time"]).strip(),
                        "orig_start_time": str(row["orig_start_time"]),
                        "orig_end_time": str(row["orig_end_time"]),
                    }
                )
            result = BookingService(CSVHILRepository()).validate_and_book_slots(
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
        else:
            logger.warning(
                "Booking service returned no booking IDs; Gemini booking context was not updated."
            )
        st.success(f"Booking confirmed. New Booking IDs: {', '.join(booking_ids)}")
        logger.info(
            "Booking confirmed in UI: booking_count=%d booking_ids=%s",
            len(booking_ids),
            booking_ids,
        )
        st.session_state.pending_booking_follow_up = (
            f"Booking confirmed: {', '.join(booking_ids)}. "
            "Do you need any further assistance?"
        )
        st.session_state.candidate_slots = []
        logger.info(
            "Booking flow completed: candidate slots cleared and a visible "
            "assistant follow-up queued for the next Streamlit render."
        )
        st.rerun()


def _append_booking_history_notice(
    bookings: list[dict[str, Any]],
    booking_ids: list[str],
    slot_type: str,
) -> None:
    """Add a confirmed booking event to the active agent conversation."""
    booking_lines = [
        (
            f"- {booking_id}: {booking['rig_id']} on {booking['date']} "
            f"{booking['start_time']}-{booking['end_time']}"
        )
        for booking_id, booking in zip(booking_ids, bookings)
    ]
    notice = (
        "System Notice (confirmed booking state from the application): "
        f"Booking was successfully persisted with Slot_Type={slot_type}. "
        "These intervals are now occupied and must not be offered as available:\n"
        + "\n".join(booking_lines)
    )
    if LLM_PROVIDER == "ollama":
        st.session_state.setdefault("ollama_history", []).append(
            {"role": "user", "content": notice}
        )
    else:
        history = st.session_state.setdefault("agent_history", [])
        history.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=notice)],
            )
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
