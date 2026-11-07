"""12-hour time formatting and clock parsing for slot indexes.

Slot 0 is 6:00 PM on the scenario date. Each slot is 15 minutes. Slot 96 is the
end boundary (6:00 PM the next day). Everything a person reads goes through
these helpers so nothing human-facing shows 24-hour time.
"""

from __future__ import annotations

import re

HORIZON_START_MINUTES = 18 * 60  # 6:00 PM
SLOT_MINUTES = 15
NUM_SLOTS = 96


def _clock(minutes_of_day: int) -> tuple[int, int, str]:
    minutes_of_day %= 24 * 60
    h24, m = divmod(minutes_of_day, 60)
    meridiem = "AM" if h24 < 12 else "PM"
    h12 = h24 % 12 or 12
    return h12, m, meridiem


def slot_to_time(slot: int, slot_minutes: int = SLOT_MINUTES) -> str:
    """Slot index or end boundary -> '9:45 PM'."""
    h, m, mer = _clock(HORIZON_START_MINUTES + int(slot) * slot_minutes)
    return f"{h}:{m:02d} {mer}"


def slot_range(start: int, end: int, slot_minutes: int = SLOT_MINUTES) -> str:
    """'9:00–9:45 PM' when both ends share AM/PM, else '9:00 PM–12:00 AM'."""
    a = slot_to_time(start, slot_minutes)
    b = slot_to_time(end, slot_minutes)
    if a[-2:] == b[-2:]:
        return f"{a[:-3]}–{b}"
    return f"{a}–{b}"


def duration_text(slots: int, slot_minutes: int = SLOT_MINUTES, *, noun: bool = False) -> str:
    """'3-hour' (adjective) or '3 hours' (noun=True)."""
    minutes = slots * slot_minutes
    h, m = divmod(minutes, 60)
    hours = f"{h} hour{'s' if h != 1 else ''}"
    if h and m:
        return f"{hours} {m} minutes"
    if h:
        return hours if noun else f"{h}-hour"
    return f"{m} minutes" if noun else f"{m}-minute"


def clock_to_slot(hhmm: str, *, kind: str, slot_minutes: int = SLOT_MINUTES) -> int:
    """Parse 'HH:MM' (24-hour, as the model returns it) into a slot boundary.

    kind='deadline' rounds down to a slot boundary and maps 6:00 PM to the end
    of the horizon (96), since a deadline at the very start makes no sense.
    kind='start' rounds up.
    """
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*", hhmm or "")
    if not m:
        raise ValueError(f"not an HH:MM time: {hhmm!r}")
    hh, mm = int(m.group(1)), int(m.group(2))
    if not (0 <= hh <= 24 and 0 <= mm < 60) or (hh == 24 and mm):
        raise ValueError(f"not an HH:MM time: {hhmm!r}")
    since_start = (hh * 60 + mm - HORIZON_START_MINUTES) % (24 * 60)
    if kind == "deadline":
        slot = since_start // slot_minutes
        return NUM_SLOTS if slot == 0 else slot
    slot = -(-since_start // slot_minutes)
    return min(slot, NUM_SLOTS)


def slot_to_clock(slot: int, slot_minutes: int = SLOT_MINUTES) -> str:
    """Slot -> 'HH:MM' 24-hour. Only for model input, never for display."""
    total = (HORIZON_START_MINUTES + int(slot) * slot_minutes) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def usd(amount: float) -> str:
    return f"${abs(amount):,.2f}" if amount >= 0 else f"-${abs(amount):,.2f}"


def usd_change(delta: float) -> str:
    """Plain-English money change. Negative delta means the home pays less."""
    if abs(delta) < 0.005:
        return "no change in cost"
    if delta < 0:
        return f"{usd(-delta)} less"
    return f"{usd(delta)} more"


def usd_vs(delta: float, other: str) -> str:
    """'$0.97 less than Plan 1' / 'the same as Plan 1'."""
    if abs(delta) < 0.005:
        return f"the same as {other}"
    return f"{usd(abs(delta))} {'less' if delta < 0 else 'more'} than {other}"


_24H = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b(?!\s*[AaPp]\.?[Mm])")


def to_12_hour_text(text: str) -> str:
    """Rewrite stray 24-hour times in model text ('21:45') as '9:45 PM'."""

    def repl(m: re.Match[str]) -> str:
        h24, mm = int(m.group(1)), int(m.group(2))
        if 1 <= h24 <= 12:
            # Ambiguous like '9:45' with no AM/PM: leave it alone.
            return m.group(0)
        h, mi, mer = _clock(h24 * 60 + mm)
        return f"{h}:{mi:02d} {mer}"

    return _24H.sub(repl, text)
