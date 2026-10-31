"""Deterministic interval subtraction for rig availability."""

from datetime import datetime, timedelta
from typing import Any, Optional

from src.config.constants import MIN_SLOT_DURATION_HOURS
from src.repositories.base import AbstractHILRepository
from src.utils.parsers import resolve_rig_id
from src.utils.time_utils import duration_hours, extended_windows, parse_clock, week_friday
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class SlotSchedulerService:
    """Find free windows while respecting bookings and shift boundaries."""

    def __init__(self, repository: AbstractHILRepository) -> None:
        self.repository = repository

    def find_free_slots(
        self,
        rig_ids: list[str],
        start_date: str = "2026-10-15",
        deadline_date: Optional[str] = None,
        shift_start: str = "09:00",
        shift_end: str = "18:00",
        include_extended: bool = False,
        allow_weekends: bool = False,
        min_slot_hours: float = MIN_SLOT_DURATION_HOURS,
    ) -> dict[str, Any]:
        logger.info(
            "Availability search started: rigs=%s start_date=%s deadline=%s "
            "shift=%s-%s include_extended=%s allow_weekends=%s min_slot_hours=%.2f",
            rig_ids,
            start_date,
            deadline_date,
            shift_start,
            shift_end,
            include_extended,
            allow_weekends,
            min_slot_hours,
        )
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        friday = week_friday(start, allow_weekends)
        end = datetime.strptime(deadline_date, "%Y-%m-%d").date() if deadline_date else friday
        if end < start:
            logger.error(
                "Invalid availability date range: start_date=%s end_date=%s",
                start,
                end,
            )
            raise ValueError("deadline_date must be on or after start_date.")
        if parse_clock(shift_start) >= parse_clock(shift_end):
            logger.error(
                "Invalid shift window: shift_start=%s shift_end=%s",
                shift_start,
                shift_end,
            )
            raise ValueError("shift_start must be earlier than shift_end.")
        rig_rows = self.repository.get_all_rigs()
        valid_rig_ids = {
            str(rig_id).strip()
            for rig_id in rig_rows["Rig_ID"].dropna().astype(str)
            if str(rig_id).strip()
        }
        requested_rig_count = len(rig_ids)
        normalized_rig_ids = []
        for raw_rig_id in rig_ids:
            normalized = self._canonical_rig_id(raw_rig_id, valid_rig_ids)
            if normalized in valid_rig_ids:
                normalized_rig_ids.append(normalized)
            else:
                logger.warning(
                    "Ignoring unverified rig ID in availability search: raw_rig_id=%r",
                    raw_rig_id,
                )
        rig_ids = list(dict.fromkeys(normalized_rig_ids))
        logger.info(
            "Availability rig IDs validated: requested_count=%d validated_count=%d rigs=%s",
            requested_rig_count,
            len(rig_ids),
            rig_ids,
        )
        bookings = self.repository.get_bookings().fillna("")
        standard_slots: list[dict[str, Any]] = []
        extended_slots: list[dict[str, Any]] = []
        rig_conflicts: list[dict[str, Any]] = []
        hours_by_rig = {
            str(rig): {"standard_hours": 0.0, "extended_hours": 0.0}
            for rig in rig_ids
        }

        for offset in range((end - start).days + 1):
            current = start + timedelta(days=offset)
            if current.weekday() >= 5 and not allow_weekends:
                continue
            date_text = current.isoformat()
            for rig in rig_ids:
                day_bookings = bookings[
                    (bookings["Rig_ID"].astype(str) == rig)
                    & (bookings["Date"].astype(str) == date_text)
                ]
                if not day_bookings.empty:
                    user_bookings = [
                        {
                            "Booked_By_User": row.get("Booked_By_User", ""),
                            "Slot_Start_Time": row.get("Slot_Start_Time", ""),
                            "Slot_End_Time": row.get("Slot_End_Time", ""),
                            "Slot_Type": row.get("Slot_Type", ""),
                        }
                        for _, row in day_bookings.iterrows()
                    ]
                    rig_conflicts.append(
                        {
                            "rig_id": rig,
                            "date": date_text,
                            "maintenance_blocks": [
                                {
                                    "start_time": row.get("Slot_Start_Time", ""),
                                    "end_time": row.get("Slot_End_Time", ""),
                                    "Booked_By_User": row.get("Booked_By_User", ""),
                                }
                                for _, row in day_bookings.iterrows()
                                if row.get("Slot_Type") == "RIG_MAINTENANCE"
                            ],
                            "user_bookings": user_bookings,
                        }
                    )
                busy = [
                    (
                        parse_clock(row["Slot_Start_Time"]),
                        parse_clock(row["Slot_End_Time"]),
                    )
                    for _, row in day_bookings.iterrows()
                    if row.get("Slot_Start_Time") and row.get("Slot_End_Time")
                ]
                day_standard_slots = self._gaps(
                    rig, date_text, shift_start, shift_end, busy,
                    "Standard Shift", min_slot_hours,
                )
                standard_slots.extend(day_standard_slots)
                hours_by_rig[rig]["standard_hours"] += sum(
                    slot["duration_hrs"] for slot in day_standard_slots
                )
                for window_start, window_end, label in extended_windows(shift_start, shift_end):
                    day_extended_slots = self._gaps(
                        rig, date_text, window_start, window_end, busy,
                        label, min_slot_hours,
                    )
                    extended_slots.extend(day_extended_slots)
                    hours_by_rig[rig]["extended_hours"] += sum(
                        slot["duration_hrs"] for slot in day_extended_slots
                    )

        result = {
            "standard_slots": standard_slots,
            "extended_slots": extended_slots,
            "rig_conflicts": rig_conflicts,
            "search_end_date": end.isoformat(),
            "total_standard_hours_available": round(
                sum(slot["duration_hrs"] for slot in standard_slots), 2
            ),
            "total_extended_hours_available": round(
                sum(slot["duration_hrs"] for slot in extended_slots), 2
            ),
            "total_with_extended_hours": round(
                sum(slot["duration_hrs"] for slot in standard_slots + extended_slots), 2
            ),
            "hours_by_rig": {
                rig: {
                    "standard_hours": round(hours["standard_hours"], 2),
                    "extended_hours": round(hours["extended_hours"], 2),
                }
                for rig, hours in hours_by_rig.items()
            },
        }
        logger.info(
            "Availability search completed: search_end=%s standard_slots=%d "
            "extended_slots=%d standard_hours=%.2f total_with_extended=%.2f "
            "conflict_days=%d",
            result["search_end_date"],
            len(standard_slots),
            len(extended_slots),
            result["total_standard_hours_available"],
            result["total_with_extended_hours"],
            len(rig_conflicts),
        )
        return result

    @staticmethod
    def _canonical_rig_id(
        rig_id: object, valid_rig_ids: set[str] | list[str] | None = None
    ) -> str:
        return resolve_rig_id(rig_id, valid_rig_ids)

    @staticmethod
    def _gaps(
        rig_id: str,
        date_text: str,
        window_start: str,
        window_end: str,
        bookings: list[tuple[Any, Any]],
        window_type: str,
        min_slot_hours: float,
    ) -> list[dict[str, Any]]:
        start = parse_clock(window_start)
        end = parse_clock(window_end)
        clipped = sorted(
            (max(start, busy_start), min(end, busy_end))
            for busy_start, busy_end in bookings
            if max(start, busy_start) < min(end, busy_end)
        )
        merged: list[list[Any]] = []
        for busy_start, busy_end in clipped:
            if merged and busy_start <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], busy_end)
            else:
                merged.append([busy_start, busy_end])
        gaps = []
        current = start
        for busy_start, busy_end in merged:
            if current < busy_start:
                gaps.append((current, busy_start))
            current = max(current, busy_end)
        if current < end:
            gaps.append((current, end))
        result = []
        for gap_start, gap_end in gaps:
            hours = duration_hours(gap_start, gap_end)
            if hours >= min_slot_hours:
                result.append(
                    {
                        "rig_id": rig_id,
                        "date": date_text,
                        "start_time": gap_start.strftime("%H:%M"),
                        "end_time": gap_end.strftime("%H:%M"),
                        "duration_hrs": hours,
                        "window_type": window_type,
                        "orig_start_time": gap_start.strftime("%H:%M"),
                        "orig_end_time": gap_end.strftime("%H:%M"),
                    }
                )
        return result
