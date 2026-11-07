"""The one Python time formatter. Slots are integers; every human-facing time is 12-hour."""

from __future__ import annotations

from datetime import datetime, timedelta

HORIZON_START = datetime(2026, 7, 15, 18, 0)  # 6:00 PM, America/New_York (naive local time)
SLOT_MINUTES = 15
SLOTS = 96
START_MINUTE_OF_DAY = 18 * 60


def slot_to_datetime(slot: int) -> datetime:
    return HORIZON_START + timedelta(minutes=SLOT_MINUTES * slot)


def slot_to_time(slot: int) -> str:
    """Slot 0 -> '6:00 PM', slot 15 -> '9:45 PM', slot 24 -> '12:00 AM'."""
    dt = slot_to_datetime(slot)
    hour = dt.hour % 12 or 12
    suffix = "AM" if dt.hour < 12 else "PM"
    return f"{hour}:{dt.minute:02d} {suffix}"


def span_text(start_slot: int, duration_slots: int) -> str:
    """'9:45 PM to 12:45 AM'."""
    return f"{slot_to_time(start_slot)} to {slot_to_time(start_slot + duration_slots)}"


def clock_to_slot(hour24: int, minute: int = 0, *, as_deadline: bool = False) -> int:
    """Map a wall-clock time inside the horizon to a slot.

    Times are resolved against the scenario evening, not the laptop clock:
    11 PM -> 20, 1 AM -> 28, 7 AM -> 52. With as_deadline, 6:00 PM means the end
    of the horizon (slot 96), because a deadline at the very start is meaningless.
    Minutes are rounded down to the slot boundary.
    """
    if not (0 <= hour24 <= 23 and 0 <= minute <= 59):
        raise ValueError("hour or minute out of range")
    minutes = (hour24 * 60 + minute - START_MINUTE_OF_DAY) % (24 * 60)
    slot = minutes // SLOT_MINUTES
    if as_deadline and slot == 0:
        return SLOTS
    return slot


def hours_text(duration_slots: int) -> str:
    minutes = duration_slots * SLOT_MINUTES
    if minutes % 60 == 0:
        h = minutes // 60
        return f"{h} hour" + ("" if h == 1 else "s")
    if minutes < 60:
        return f"{minutes} minutes"
    return f"{minutes / 60:g} hours"


def usd(amount: float) -> str:
    return f"${amount:,.2f}"
