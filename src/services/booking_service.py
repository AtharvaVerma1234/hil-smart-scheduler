"""Booking boundary validation and persistence."""

from datetime import datetime
from typing import Any

from src.config.constants import MIN_SLOT_DURATION_HOURS, SlotType
from src.repositories.base import AbstractHILRepository
from src.utils.time_utils import duration_hours, parse_clock
from src.utils.logging_config import get_logger

logger = get_logger(__name__)


class BookingService:
    """Validate selected free windows before writing any booking rows."""

    def __init__(self, repository: AbstractHILRepository) -> None:
        self.repository = repository

    def validate_and_book_slots(
        self,
        selected_slots: list[dict[str, Any]],
        slot_type: str,
        user_id: str,
    ) -> dict[str, Any]:
        logger.info(
            "Booking validation started: selected_count=%d slot_type=%s user_id=%s",
            len(selected_slots),
            slot_type,
            user_id,
        )
        try:
            validated_type = SlotType(slot_type)
        except (ValueError, TypeError):
            logger.warning("Booking rejected: missing or invalid Slot_Type=%r", slot_type)
            raise ValueError("A valid Slot_Type is mandatory to complete a booking.") from None
        if not selected_slots:
            logger.warning("Booking rejected: no slots selected.")
            raise ValueError("Select at least one available slot to book.")

        existing = self.repository.get_bookings().fillna("")
        new_intervals: list[tuple[str, str, Any, Any]] = []
        rows = []
        for slot in selected_slots:
            required = ("rig_id", "date", "start_time", "end_time")
            if any(not slot.get(key) for key in required):
                logger.warning(
                    "Booking rejected: incomplete slot fields present=%s required=%s",
                    sorted(key for key in slot if key in required),
                    required,
                )
                raise ValueError("Each selected slot must include rig_id, date, start_time, and end_time.")
            try:
                start = parse_clock(slot["start_time"])
                end = parse_clock(slot["end_time"])
                original_start = parse_clock(slot.get("orig_start_time", slot["start_time"]))
                original_end = parse_clock(slot.get("orig_end_time", slot["end_time"]))
                datetime.strptime(str(slot["date"]), "%Y-%m-%d")
            except (ValueError, TypeError):
                logger.warning(
                    "Booking rejected: invalid date/time values for rig=%s date=%s",
                    slot.get("rig_id"),
                    slot.get("date"),
                )
                raise ValueError("A selected slot contains an invalid date or HH:MM time.") from None
            if start < original_start or end > original_end or start >= end:
                logger.warning(
                    "Booking rejected: edited interval outside available interval "
                    "rig=%s date=%s selected=%s-%s available=%s-%s",
                    slot["rig_id"],
                    slot["date"],
                    start.strftime("%H:%M"),
                    end.strftime("%H:%M"),
                    original_start.strftime("%H:%M"),
                    original_end.strftime("%H:%M"),
                )
                raise ValueError("Edited booking times must remain within the selected available window.")
            if duration_hours(start, end) < MIN_SLOT_DURATION_HOURS:
                logger.warning(
                    "Booking rejected: below minimum duration rig=%s date=%s "
                    "duration_hours=%.2f minimum_hours=%.2f",
                    slot["rig_id"],
                    slot["date"],
                    duration_hours(start, end),
                    MIN_SLOT_DURATION_HOURS,
                )
                raise ValueError("Each booking must be at least 30 minutes long.")
            rig_id, date_text = str(slot["rig_id"]), str(slot["date"])
            for _, booking in existing.iterrows():
                if str(booking.get("Rig_ID")) != rig_id or str(booking.get("Date")) != date_text:
                    continue
                busy_start = parse_clock(booking["Slot_Start_Time"])
                busy_end = parse_clock(booking["Slot_End_Time"])
                if start < busy_end and busy_start < end:
                    logger.warning(
                        "Booking rejected due to existing conflict: rig=%s date=%s "
                        "booking_id=%s selected=%s-%s existing=%s-%s",
                        rig_id,
                        date_text,
                        booking.get("Booking_ID", ""),
                        start.strftime("%H:%M"),
                        end.strftime("%H:%M"),
                        busy_start.strftime("%H:%M"),
                        busy_end.strftime("%H:%M"),
                    )
                    raise ValueError(
                        f"Selected interval overlaps existing booking {booking.get('Booking_ID', '')}."
                    )
            for other_rig, other_date, other_start, other_end in new_intervals:
                if other_rig == rig_id and other_date == date_text and start < other_end and other_start < end:
                    logger.warning(
                        "Booking rejected due to overlap among selected rows: "
                        "rig=%s date=%s selected=%s-%s other=%s-%s",
                        rig_id,
                        date_text,
                        start.strftime("%H:%M"),
                        end.strftime("%H:%M"),
                        other_start.strftime("%H:%M"),
                        other_end.strftime("%H:%M"),
                    )
                    raise ValueError("Selected booking slots overlap each other.")
            new_intervals.append((rig_id, date_text, start, end))
            rows.append(
                {
                    "Rig_ID": rig_id,
                    "Date": date_text,
                    "Slot_Start_Time": start.strftime("%H:%M"),
                    "Slot_End_Time": end.strftime("%H:%M"),
                    "Slot_Type": validated_type.value,
                    "Booked_By_User": user_id,
                }
            )
        try:
            booking_ids = self.repository.append_bookings(rows)
        except Exception:
            logger.exception(
                "Booking persistence failed after validation: booking_count=%d "
                "slot_type=%s user_id=%s",
                len(rows),
                validated_type.value,
                user_id,
            )
            raise
        logger.info(
            "Booking operation completed: requested_count=%d created_count=%d booking_ids=%s",
            len(rows),
            len(booking_ids),
            booking_ids,
        )
        return {"success": True, "booking_ids": booking_ids}
