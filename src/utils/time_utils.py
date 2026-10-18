"""Date and time parsing, interval arithmetic, and schedule horizon helpers."""

from datetime import date, datetime, time, timedelta

from src.config.constants import EXTENDED_SHIFT_DELTA_HOURS


def parse_clock(value: str | time) -> time:
    """Parse an HH:MM value (or pass through a time object)."""
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    return datetime.strptime(str(value).strip(), "%H:%M").time()


def minutes_since_midnight(value: str | time) -> int:
    parsed = parse_clock(value)
    return parsed.hour * 60 + parsed.minute


def clock_from_minutes(minutes: int) -> time:
    bounded = max(0, min(23 * 60 + 59, minutes))
    return time(hour=bounded // 60, minute=bounded % 60)


def add_hours(value: str | time, hours: int) -> time:
    return clock_from_minutes(minutes_since_midnight(value) + hours * 60)


def duration_hours(start: str | time, end: str | time) -> float:
    return round((minutes_since_midnight(end) - minutes_since_midnight(start)) / 60.0, 2)


def week_friday(start: date, allow_weekends: bool = False) -> date:
    """Return Friday for the current search week, advancing weekend starts."""
    if start.weekday() >= 5 and not allow_weekends:
        return start + timedelta(days=(4 - start.weekday()) % 7 or 7)
    return start + timedelta(days=(4 - start.weekday()) % 7)


def extended_windows(shift_start: str, shift_end: str) -> list[tuple[str, str, str]]:
    early_start = add_hours(shift_start, -EXTENDED_SHIFT_DELTA_HOURS).strftime("%H:%M")
    late_end = add_hours(shift_end, EXTENDED_SHIFT_DELTA_HOURS).strftime("%H:%M")
    return [
        (early_start, parse_clock(shift_start).strftime("%H:%M"), "Extended (-2h Early)"),
        (parse_clock(shift_end).strftime("%H:%M"), late_end, "Extended (+2h Late)"),
    ]
