"""Phase 1 availability search and UI staging tools."""

import re
from datetime import datetime, timedelta
from typing import Optional

import streamlit as st

from src.config.constants import MIN_SLOT_DURATION_HOURS
from src.agent.tools.registry import register_tool
from src.repositories import get_repository
from src.repositories.base import AbstractHILRepository
from src.services.slot_scheduler import SlotSchedulerService
from src.utils.logging_config import get_logger
from src.utils.parsers import parse_pipe_list, resolve_rig_id

logger = get_logger(__name__)


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
        Standard and extended free intervals, pooled and per-rig hour totals,
        and booking conflicts/maintenance metadata.
    """
    settings = st.session_state.get("search_settings", {})
    if not start_date or start_date == "2026-10-15":
        start_date = settings.get("start_date") or "2026-10-15"
    if not shift_start or shift_start == "09:00":
        shift_start = settings.get("shift_start") or "09:00"
    if not shift_end or shift_end == "18:00":
        shift_end = settings.get("shift_end") or "18:00"
    if not include_extended and settings.get("include_extended"):
        include_extended = True
    if not allow_weekends and settings.get("allow_weekends"):
        allow_weekends = True
    if deadline_date is None and settings.get("deadline_date"):
        deadline_date = settings["deadline_date"]
    if deadline_date is not None and str(deadline_date) < str(start_date):
        setting_deadline = settings.get("deadline_date")
        deadline_date = (
            setting_deadline
            if setting_deadline and str(setting_deadline) >= str(start_date)
            else None
        )
    repository = get_repository()
    valid_rig_ids = _valid_rig_ids(repository)
    rig_ids = _sanitize_rig_ids(rig_ids, valid_rig_ids)
    requested_rig_tuple = tuple(rig_ids)
    turn_matched_rigs = st.session_state.get("_turn_matched_rigs_by_id")
    if turn_matched_rigs is None:
        turn_matched_rigs = st.session_state.get("matched_rigs", [])
    matched_rigs = (
        list(turn_matched_rigs.values())
        if isinstance(turn_matched_rigs, dict)
        else list(turn_matched_rigs)
    )
    matched_ids = (
        _sanitize_rig_ids(list(turn_matched_rigs), valid_rig_ids)
        if isinstance(turn_matched_rigs, dict)
        else _sanitize_rig_ids(
            [
                str(rig.get("rig_id", rig.get("Rig_ID", "")))
                for rig in matched_rigs
                if rig.get("rig_id") or rig.get("Rig_ID")
            ],
            valid_rig_ids,
        )
    )
    batch_ids = [
        _canonical_rig_id(rig_id, valid_rig_ids)
        for rig_id in st.session_state.get("_turn_last_batch_rig_ids", [])
        if _canonical_rig_id(rig_id, valid_rig_ids) in valid_rig_ids
    ]
    direct_rig_ids = {
        _canonical_rig_id(rig_id, valid_rig_ids)
        for rig_id in st.session_state.get("_turn_direct_rig_ids", [])
    }
    if st.session_state.get("_turn_match_targets") and matched_ids:
        valid_turn_ids = set(matched_ids) | direct_rig_ids
        filtered_rig_ids = [
            rig_id for rig_id in rig_ids if rig_id in valid_turn_ids
        ]
        rig_ids = list(dict.fromkeys([*filtered_rig_ids, *matched_ids]))
    elif (
        batch_ids
        and rig_ids
        and set(rig_ids).issubset(batch_ids)
    ):
        rig_ids = list(dict.fromkeys([*rig_ids, *batch_ids]))
    elif (
        not batch_ids
        and rig_ids
        and matched_ids
        and set(rig_ids).issubset(matched_ids)
    ):
        rig_ids = list(dict.fromkeys([*rig_ids, *matched_ids]))
    if not requested_rig_tuple and rig_ids:
        requested_rig_tuple = tuple(rig_ids)
    result = SlotSchedulerService(repository).find_free_slots(
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
    enriched_candidates = _enrich_slots(candidates)
    accumulated_candidates = st.session_state.setdefault(
        "_turn_candidate_slots", []
    )
    candidate_keys = {
        (
            slot["rig_id"],
            slot["date"],
            slot["start_time"],
            slot["end_time"],
            slot["window_type"],
        )
        for slot in accumulated_candidates
    }
    for slot in enriched_candidates:
        key = (
            slot["rig_id"],
            slot["date"],
            slot["start_time"],
            slot["end_time"],
            slot["window_type"],
        )
        if key not in candidate_keys:
            accumulated_candidates.append(slot)
            candidate_keys.add(key)
    st.session_state.candidate_slots = list(accumulated_candidates)
    st.session_state.pop("candidate_slot_editor", None)

    slot_durations = st.session_state.setdefault("_turn_slot_durations", [])
    slot_durations.append((requested_rig_tuple, float(duration_hours)))
    st.session_state.target_duration_hours = _combined_turn_duration(
        slot_durations,
        st.session_state.get("messages", []),
        st.session_state.get("_turn_user_message"),
    )
    st.session_state["selected_slot_keys"] = _auto_select_proposed_split(
        st.session_state.candidate_slots,
        float(st.session_state.target_duration_hours),
    )

    prior_context = st.session_state.get("slot_search_context", {})
    context_rig_ids = list(
        dict.fromkeys([*prior_context.get("rig_ids", []), *rig_ids])
    )
    st.session_state.slot_search_context = {
        **prior_context,
        "rig_ids": context_rig_ids,
        "start_date": start_date,
        "deadline_date": deadline_date,
        "shift_start": shift_start,
        "shift_end": shift_end,
        "include_extended": include_extended,
        "allow_weekends": allow_weekends,
    }
    return _tool_availability_payload(result, include_extended)


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

    Call this ONLY on follow-up turns AFTER initial discovery when the user
    narrows down specific rig IDs, sets a new deadline, enables extended hours,
    allows weekends, or specifies a slot_type. NEVER call this in the same turn
    as `find_available_slots`, because `find_available_slots` already stages
    candidate slots into the UI.

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
    if not start_date or start_date == "2026-10-15":
        start_date = settings.get("start_date") or "2026-10-15"
    if deadline_date is None and settings.get("deadline_date"):
        deadline_date = settings["deadline_date"]
    if deadline_date is not None and str(deadline_date) < str(start_date):
        setting_deadline = settings.get("deadline_date")
        deadline_date = (
            setting_deadline
            if setting_deadline and str(setting_deadline) >= str(start_date)
            else None
        )
    if not include_extended and settings.get("include_extended"):
        include_extended = True
    if not allow_weekends and settings.get("allow_weekends"):
        allow_weekends = True
    st.session_state["filter_include_extended"] = bool(include_extended)
    st.session_state["filter_allow_weekends"] = bool(allow_weekends)
    st.session_state["_pending_filter_toggle_sync"] = {
        "include_extended": bool(include_extended),
        "allow_weekends": bool(allow_weekends),
    }
    repository = get_repository()
    rig_ids = _sanitize_rig_ids(rig_ids, _valid_rig_ids(repository))
    result = SlotSchedulerService(repository).find_free_slots(
        rig_ids=rig_ids,
        start_date=start_date,
        deadline_date=deadline_date,
        shift_start=(
            settings.get("shift_start")
            or prior.get("shift_start")
            or "09:00"
        ),
        shift_end=(
            settings.get("shift_end")
            or prior.get("shift_end")
            or "18:00"
        ),
        include_extended=include_extended,
        allow_weekends=allow_weekends,
    )
    candidates = result["standard_slots"][:]
    if include_extended:
        candidates.extend(result["extended_slots"])
    st.session_state.candidate_slots = _enrich_slots(candidates)
    st.session_state.pop("candidate_slot_editor", None)
    st.session_state.target_duration_hours = duration_hours
    st.session_state["selected_slot_keys"] = _auto_select_proposed_split(
        st.session_state.candidate_slots,
        float(duration_hours),
    )
    st.session_state.selected_slot_type = slot_type or st.session_state.get(
        "selected_slot_type"
    )
    if slot_type:
        st.session_state["_pending_booking_slot_type"] = slot_type
    st.session_state.slot_search_context = {
        **prior,
        "rig_ids": rig_ids,
        "start_date": start_date,
        "deadline_date": deadline_date,
        "include_extended": include_extended,
        "allow_weekends": allow_weekends,
    }
    return _tool_availability_payload(result, include_extended)


def _enrich_slots(slots: list[dict]) -> list[dict]:
    rig_metadata = {
        _canonical_rig_id(rig.get("rig_id", rig.get("Rig_ID", ""))): rig
        for rig in st.session_state.get("matched_rigs", [])
    }
    turn_rigs = st.session_state.get("_turn_matched_rigs_by_id", {})
    if isinstance(turn_rigs, dict):
        rig_metadata.update(
            {
                _canonical_rig_id(rig.get("rig_id", rig.get("Rig_ID", rig_id))): rig
                for rig_id, rig in turn_rigs.items()
            }
        )
    direct_rig_ids = {
        _canonical_rig_id(rig_id)
        for rig_id in st.session_state.get("_turn_direct_rig_ids", [])
    }
    enriched = []
    for slot in slots:
        rig_id = _canonical_rig_id(slot.get("rig_id", ""))
        rig = rig_metadata.get(rig_id)
        if rig is None:
            if rig_id not in direct_rig_ids:
                logger.warning(
                    "Dropping slot without matched rig metadata: rig_id=%s date=%s",
                    rig_id,
                    slot.get("date"),
                )
                continue
            details = slot.get("rig_details") or rig_id
        else:
            score_labels = [
                f"{target} ({float(score):.1f}% Match)"
                for target, score in rig.get("scores_by_target", {}).items()
            ]
            match_details = (
                " & ".join(score_labels)
                if score_labels
                else " | ".join(
                    part
                    for part in (
                        str(rig.get("matched_for", "")).strip(),
                        (
                            f'{float(rig.get("match_score")):.1f}% Match'
                            if rig.get("match_score") is not None
                            else ""
                        ),
                    )
                    if part
                )
            )
            details_parts = [
                match_details,
                str(rig.get("platform", rig.get("Rig_Platform", ""))).strip(),
                str(rig.get("vehicle_program", rig.get("Vehicle_Program", ""))).strip(),
                str(rig.get("rig_engineer", rig.get("Rig_Engineer", ""))).strip(),
            ]
            details_parts = [part for part in details_parts if part]
            existing_details = str(slot.get("rig_details", "")).strip()
            if existing_details and existing_details not in details_parts:
                details_parts.append(existing_details)
            details = " | ".join(details_parts)
        if not details:
            logger.warning(
                "Dropping slot with empty rig details: rig_id=%s date=%s",
                rig_id,
                slot.get("date"),
            )
            continue
        enriched.append({**slot, "rig_details": details})
    return enriched


def _auto_select_proposed_split(
    slots: list[dict],
    target_hours: float,
) -> list[str]:
    """Greedily select available intervals and trim the final interval to target."""
    selected_keys: list[str] = []
    remaining = max(0.0, float(target_hours))
    for slot in slots:
        if remaining < MIN_SLOT_DURATION_HOURS:
            break
        start = str(slot.get("orig_start_time", slot.get("start_time", "")))
        end = str(slot.get("orig_end_time", slot.get("end_time", "")))
        available_hours = _duration_between(start, end)
        if available_hours < MIN_SLOT_DURATION_HOURS:
            continue
        selected_hours = min(available_hours, remaining)
        selected_end = _add_duration(start, selected_hours)
        if selected_end is None or _duration_between(start, selected_end) < MIN_SLOT_DURATION_HOURS:
            continue
        slot["start_time"] = start
        slot["end_time"] = selected_end
        slot["duration_hrs"] = round(_duration_between(start, selected_end), 2)
        slot_key = (
            f'{slot["rig_id"]}|{slot["date"]}|'
            f'{slot.get("orig_start_time", start)}|'
            f'{slot.get("orig_end_time", end)}'
        )
        selected_keys.append(slot_key)
        remaining = max(0.0, remaining - slot["duration_hrs"])
    return selected_keys


def _duration_between(start: str, end: str) -> float:
    try:
        start_time = datetime.strptime(start, "%H:%M")
        end_time = datetime.strptime(end, "%H:%M")
    except (TypeError, ValueError):
        return 0.0
    return (end_time - start_time).total_seconds() / 3600.0


def _add_duration(start: str, duration_hours: float) -> str | None:
    try:
        start_time = datetime.strptime(start, "%H:%M")
    except (TypeError, ValueError):
        return None
    end_time = start_time + timedelta(minutes=round(duration_hours * 60))
    return end_time.strftime("%H:%M")


def _tool_availability_payload(result: dict, include_extended: bool) -> dict:
    keys = [
        "standard_slots",
        "hours_by_rig",
        "total_standard_hours_available",
        "total_extended_hours_available",
        "total_with_extended_hours",
        "rig_conflicts",
        "search_end_date",
    ]
    if include_extended:
        keys.extend(["extended_slots", "extended_slots_preview"])
        return {
            **{key: result[key] for key in keys if key in result},
            "extended_slots_preview": result.get("extended_slots", []),
        }
    return {key: result[key] for key in keys if key in result}


def _valid_rig_ids(repository: AbstractHILRepository) -> set[str]:
    rigs = repository.get_all_rigs()
    return {
        str(rig_id).strip()
        for rig_id in rigs["Rig_ID"].dropna().astype(str)
        if str(rig_id).strip()
    }


def _canonical_rig_id(
    rig_id: object, valid_rig_ids: set[str] | list[str] | None = None
) -> str:
    return resolve_rig_id(rig_id, valid_rig_ids)


def _sanitize_rig_ids(
    rig_ids: list[str], valid_rig_ids: set[str]
) -> list[str]:
    normalized_ids = []
    for raw_rig_id in rig_ids:
        normalized = _canonical_rig_id(raw_rig_id, valid_rig_ids)
        if normalized and normalized in valid_rig_ids:
            normalized_ids.append(normalized)
        else:
            logger.warning(
                "Dropping unverified rig ID before availability lookup: raw_rig_id=%r",
                raw_rig_id,
            )
    return list(dict.fromkeys(normalized_ids))


def _combined_turn_duration(
    slot_durations: list[tuple[tuple[str, ...], float]],
    messages: list[dict],
    user_message: Optional[str] = None,
) -> float:
    if not slot_durations:
        return 0.0
    if user_message is None:
        user_text = "\n".join(
            str(message.get("content", ""))
            for message in messages
            if message.get("role") == "user"
        )
    else:
        user_text = user_message
    explicit_total = _duration_explicitly_requested(user_text)
    if explicit_total is not None:
        return explicit_total

    duration_by_rig_set: dict[tuple[str, ...], float] = {}
    for rig_ids, duration in slot_durations:
        normalized_rig_set = tuple(sorted(set(rig_ids)))
        duration_by_rig_set[normalized_rig_set] = max(
            duration_by_rig_set.get(normalized_rig_set, 0.0),
            float(duration),
        )
    distinct_durations = list(duration_by_rig_set.values())
    if len(distinct_durations) == 1:
        return distinct_durations[0]
    if len(set(distinct_durations)) > 1:
        return sum(distinct_durations)
    if re.search(r"\b(?:each|per)\b", user_text, re.IGNORECASE):
        return distinct_durations[0] * len(distinct_durations)
    return distinct_durations[0]


_SHIFT_OFFSET_PREFIX_RE = re.compile(
    r"(?:\+\s*/?\s*-|\+-|-\+|±|[+\-]|within\s+|by\s+)\s*$",
    re.IGNORECASE,
)
_SHIFT_OFFSET_SUFFIX_RE = re.compile(
    r"^\s*(?:extended\b|outside\b|shift\b|early\b|late\b|before\s+shift\b|after\s+shift\b|window\b)",
    re.IGNORECASE,
)
_DURATION_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?)\b",
    re.IGNORECASE,
)


def find_booking_duration_matches(text: str) -> list[re.Match[str]]:
    """Return duration matches while excluding +-2h shift-extension phrases."""
    matches: list[re.Match[str]] = []
    for match in _DURATION_TOKEN_RE.finditer(text):
        prefix = text[max(0, match.start() - 20) : match.start()]
        suffix = text[match.end() : min(len(text), match.end() + 30)]
        if _SHIFT_OFFSET_PREFIX_RE.search(prefix):
            continue
        if _SHIFT_OFFSET_SUFFIX_RE.search(suffix):
            continue
        if float(match.group(1)) > 0:
            matches.append(match)
    return matches


def _duration_explicitly_requested(user_text: str) -> Optional[float]:
    """Sum user-stated booking durations, applying local each/per qualifiers."""
    durations = find_booking_duration_matches(user_text)
    if not durations:
        return None

    try:
        catalog_categories = _known_target_categories()
    except Exception:
        catalog_categories = {
            "rig": set(),
            "feature": set(),
            "vehicle_program": set(),
            "ecu": set(),
        }
    target_categories: dict[str, set[str]] = {
        cat: set(items) for cat, items in catalog_categories.items()
    }
    for value in st.session_state.get("_turn_match_targets", []):
        for target in re.split(r"\s*(?:\+|&|,)\s*", str(value).upper()):
            if not target:
                continue
            category = _infer_target_category(target, target_categories)
            if category:
                target_categories.setdefault(category, set()).add(target)
            else:
                target_categories.setdefault("other", set()).add(target)

    known_targets = (
        set().union(*target_categories.values()) if target_categories else set()
    )
    total = 0.0
    previous_end = 0
    for index, duration in enumerate(durations):
        next_start = (
            durations[index + 1].start()
            if index + 1 < len(durations)
            else len(user_text)
        )
        prefix = user_text[previous_end : duration.start()]
        suffix = user_text[duration.end() : next_start]
        qualifier_match = re.match(
            r"\s*(?:for\s+)?(?:each\b(?:\s+[A-Za-z0-9_-]+)?|per\b(?:\s+[A-Za-z0-9_-]+)?|apiece\b)",
            suffix,
            re.IGNORECASE,
        )
        qualifier = bool(
            re.search(r"\b(?:each|per)\b", prefix, re.IGNORECASE)
            or qualifier_match
        )
        clause = f"{prefix} {suffix}"
        identifiers = {
            target
            for target in known_targets
            if re.search(
                rf"(?<![A-Z0-9]){re.escape(target)}(?![A-Z0-9])",
                clause,
                re.IGNORECASE,
            )
        }
        category_qualifier = re.search(
            r"\b(?:each|per)\s+(ecu|ecus|feature|features|rig|rigs|"
            r"vehicle[_ ]programs?)\b",
            clause,
            re.IGNORECASE,
        )
        if category_qualifier:
            category_name = (
                category_qualifier.group(1)
                .casefold()
                .replace(" ", "_")
                .rstrip("s")
            )
            category_targets = set(target_categories.get(category_name, set()))
            category_targets.update(
                target
                for target in identifiers
                if _infer_target_category(target, target_categories)
                == category_name
            )
            identifiers = {
                target for target in identifiers if target in category_targets
            }
        else:
            scoped_programs = {
                target
                for target in identifiers
                if (
                    target in target_categories.get("vehicle_program", set())
                    or _infer_target_category(target, target_categories)
                    == "vehicle_program"
                )
                and re.search(
                    rf"\b(?:on|in|for|under)\s+{re.escape(target)}\b",
                    clause,
                    re.IGNORECASE,
                )
            }
            non_program_targets = identifiers.difference(scoped_programs)
            if non_program_targets:
                identifiers = non_program_targets
        if not identifiers:
            identifiers = {
                token
                for token in re.findall(r"\b[A-Z][A-Z0-9_-]*\b", clause)
                if any(char.isdigit() for char in token)
                or "_" in token
                or "-" in token
            }
        multiplier = max(1, len(identifiers)) if qualifier else 1
        value = float(duration.group(1))
        if duration.group(2).casefold().startswith(("minute", "min")):
            value /= 60.0
        total += value * multiplier
        previous_end = duration.end()
        if qualifier_match:
            previous_end += qualifier_match.end()
    return total


def _known_target_identifiers() -> set[str]:
    return set().union(*_known_target_categories().values())


def _known_target_categories() -> dict[str, set[str]]:
    repository = get_repository()
    categories: dict[str, set[str]] = {
        "rig": set(),
        "feature": set(),
        "vehicle_program": set(),
        "ecu": set(),
    }

    rigs = repository.get_all_rigs()
    if "Rig_ID" in rigs:
        categories["rig"].update(
            str(value).strip().upper()
            for value in rigs["Rig_ID"].dropna()
            if str(value).strip()
        )
    for column in (
        "Real_Connected_Components",
        "CAN_Sim_ECUs",
        "Eth_Sim_ECUs",
    ):
        if column in rigs:
            for value in rigs[column].dropna():
                categories["ecu"].update(
                    item.upper() for item in parse_pipe_list(value)
                )

    features = repository.get_feature_requirements()
    if "Feature_Name" in features:
        categories["feature"].update(
            str(value).strip().upper()
            for value in features["Feature_Name"].dropna()
            if str(value).strip()
        )
    if "Vehicle_Program" in features:
        categories["vehicle_program"].update(
            str(value).strip().upper()
            for value in features["Vehicle_Program"].dropna()
            if str(value).strip()
        )

    programs = repository.get_vehicle_program_ecus()
    for column in ("Vehicle_Program", "Applicable_ECUs"):
        if column in programs:
            for value in programs[column].dropna():
                if column == "Applicable_ECUs":
                    categories["ecu"].update(
                        item.upper() for item in parse_pipe_list(value)
                    )
                elif str(value).strip():
                    categories["vehicle_program"].add(
                        str(value).strip().upper()
                    )
    return categories


def _infer_target_category(
    target: str,
    catalog_categories: Optional[dict[str, set[str]]] = None,
) -> Optional[str]:
    normalized = target.strip().upper()
    if catalog_categories:
        for category in ("vehicle_program", "feature", "ecu", "rig"):
            if normalized in catalog_categories.get(category, set()):
                return category
    if normalized.startswith("VEHICLE_PROGRAM"):
        return "vehicle_program"
    if normalized.startswith("FEATURE"):
        return "feature"
    if normalized.startswith("ECU"):
        return "ecu"
    if normalized.startswith("RIG"):
        return "rig"
    return None
