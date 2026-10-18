"""Phase 1 availability search and UI staging tools."""

from typing import Optional

import streamlit as st

from src.agent.tools.registry import register_tool
from src.repositories.csv_repository import CSVHILRepository
from src.services.slot_scheduler import SlotSchedulerService


@register_tool
def find_available_slots(
    rig_ids: list[str],
    duration_hours: float,
    start_date: str = "2026-10-15",
    deadline_date: Optional[str] = None,
    shift_start: str = "09:00",
    shift_end: str = "18:00",
    include_extended: bool = False,
    allow_weekends: bool = False,
) -> dict:
    """Find all usable free intervals and load them into the booking table.

    Args:
        rig_ids: Rig identifiers to search.
        duration_hours: Total requested hours; individual gaps are retained
            when they meet the 30-minute minimum, even if shorter than this.
        start_date: First search date, YYYY-MM-DD.
        deadline_date: Optional final search date; absent means Friday of the
            start date's week.
        shift_start: Standard working-day start as HH:MM.
        shift_end: Standard working-day end as HH:MM.
        include_extended: Add early and late two-hour windows to UI choices.
        allow_weekends: Include Saturday and Sunday when true.
    Returns:
        Standard and extended free intervals, hours totals, and booking
        conflicts/maintenance metadata.
    """
    settings = st.session_state.get("search_settings", {})
    if start_date == "2026-10-15":
        start_date = settings.get("start_date", start_date)
    if shift_start == "09:00":
        shift_start = settings.get("shift_start", shift_start)
    if shift_end == "18:00":
        shift_end = settings.get("shift_end", shift_end)
    result = SlotSchedulerService(CSVHILRepository()).find_free_slots(
        rig_ids=rig_ids,
        start_date=start_date,
        deadline_date=deadline_date,
        shift_start=shift_start,
        shift_end=shift_end,
        include_extended=include_extended,
        allow_weekends=allow_weekends,
    )
    candidates = result["standard_slots"][:]
    if include_extended:
        candidates.extend(result["extended_slots"])
    st.session_state.candidate_slots = _enrich_slots(candidates)
    st.session_state.target_duration_hours = duration_hours
    st.session_state.slot_search_context = {
        "rig_ids": rig_ids,
        "start_date": start_date,
        "deadline_date": deadline_date,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "include_extended": include_extended,
        "allow_weekends": allow_weekends,
    }
    return {
        **result,
        "extended_slots_preview": result["extended_slots"],
    }


@register_tool
def stage_filtered_slots_for_ui(
    rig_ids: list[str],
    duration_hours: float,
    start_date: str = "2026-10-15",
    deadline_date: Optional[str] = None,
    include_extended: bool = False,
    allow_weekends: bool = False,
    slot_type: Optional[str] = None,
) -> dict:
    """Refresh UI candidates after a user narrows rigs or schedule preferences.

    Args:
        rig_ids: Rig identifiers to keep in the refreshed availability search.
        duration_hours: Total requested hours for the booking progress metric.
        start_date: First date to search, YYYY-MM-DD.
        deadline_date: Optional inclusive final search date.
        include_extended: Include the early/late extended shift intervals.
        allow_weekends: Include weekends when true.
        slot_type: Optional booking type already mentioned in chat.
    Returns:
        The filtered availability data and updated interactive UI state.
    """
    prior = st.session_state.get("slot_search_context", {})
    settings = st.session_state.get("search_settings", {})
    if start_date == "2026-10-15":
        start_date = settings.get("start_date", start_date)
    result = SlotSchedulerService(CSVHILRepository()).find_free_slots(
        rig_ids=rig_ids,
        start_date=start_date,
        deadline_date=deadline_date,
        shift_start=prior.get("shift_start", settings.get("shift_start", "09:00")),
        shift_end=prior.get("shift_end", settings.get("shift_end", "18:00")),
        include_extended=include_extended,
        allow_weekends=allow_weekends,
    )
    candidates = result["standard_slots"][:]
    if include_extended:
        candidates.extend(result["extended_slots"])
    st.session_state.candidate_slots = _enrich_slots(candidates)
    st.session_state.target_duration_hours = duration_hours
    st.session_state.selected_slot_type = slot_type or st.session_state.get(
        "selected_slot_type"
    )
    st.session_state.slot_search_context = {
        **prior,
        "rig_ids": rig_ids,
        "start_date": start_date,
        "deadline_date": deadline_date,
        "include_extended": include_extended,
        "allow_weekends": allow_weekends,
    }
    return {**result, "extended_slots_preview": result["extended_slots"]}


def _enrich_slots(slots: list[dict]) -> list[dict]:
    rig_metadata = {
        str(rig.get("rig_id", rig.get("Rig_ID", ""))): rig
        for rig in st.session_state.get("matched_rigs", [])
    }
    enriched = []
    for slot in slots:
        rig = rig_metadata.get(slot["rig_id"], {})
        details = slot.get("rig_details") or " | ".join(
            str(value)
            for value in (
                f'{rig.get("match_score", "")}% Match' if rig else "",
                rig.get("platform", rig.get("Rig_Platform", "")),
                rig.get("vehicle_program", rig.get("Vehicle_Program", "")),
                rig.get("rig_engineer", rig.get("Rig_Engineer", "")),
            )
            if value
        )
        enriched.append({**slot, "rig_details": details})
    return enriched
