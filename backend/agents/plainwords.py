"""Read everyday wording: which of a home's appliances a resident means, and what time.

Pure standard library, no model. Used three ways:
- the interpreter's fallback when the live model doesn't understand a clear request,
- the no-key rule stub (`RuleStubModel`),
- the backend's backup reader when the agent fails (`agent_seam.stub_interpret`).

It understands nicknames ("AC", "aircon", "the laundry", "the Tesla", "hot water"),
casual times ("8.30 pm", "830pm", "half past 8", "quarter to 11", "noon",
"midnight", "by 11 tonight"), and mentions of other people ("my aunt wants...").
A time with no am/pm is guessed for an evening plan (6-11 -> PM, 12-5 -> after
midnight); the resident always sees the exact time and confirms before anything changes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Any, Iterable, Optional

# kind -> (phrases a person might say, strong?). Strong phrases name the appliance;
# weak ones ("laundry", "charge") only count when nothing stronger is said.
_SAID: dict[str, list[tuple[str, bool]]] = {
    "car": [("electric car", True), ("electric vehicle", True), ("car", True), ("ev", True), ("e.v.", True),
            ("tesla", True), ("vehicle", True), ("truck", True), ("charger", False), ("charging", False),
            ("charge", False), ("plug in", False), ("plugged in", False), ("battery", False)],
    "dryer": [("tumble dryer", True), ("clothes dryer", True), ("dryer", True), ("drier", True),
              ("tumble dry", True), ("drying", False), ("dry the clothes", True), ("laundry", False),
              ("clothes", False)],
    "dishwasher": [("dishwasher", True), ("dish washer", True), ("dishes", True), ("dish", True)],
    "washer": [("washing machine", True), ("clothes washer", True), ("washer", True), ("wash the clothes", True),
               ("washing", False), ("wash", False), ("laundry", False), ("clothes", False)],
    "water_heater": [("water heater", True), ("hot water", True), ("water tank", True), ("boiler", True),
                     ("geyser", True), ("heater", True), ("showers", False), ("shower", False)],
    "ac": [("air conditioning", True), ("air conditioner", True), ("air con", True), ("aircon", True),
           ("a/c", True), ("a.c.", True), ("ac", True), ("hvac", True), ("cooling", False),
           ("cool the house", True), ("cool down", False), ("cool", False)],
    "pool_pump": [("pool pump", True), ("pool filter", True), ("pool", True), ("pump", True)],
}


def kind_of(name: str) -> Optional[str]:
    """Which known kind an appliance's display name is, if any."""
    low = f" {name.lower()} "
    if "dish" in low:
        return "dishwasher"
    if " ev " in low or "car" in low or "vehicle" in low:
        return "car"
    if "dryer" in low:
        return "dryer"
    if "wash" in low:
        return "washer"
    if "water heater" in low or "hot water" in low:
        return "water_heater"
    if "air con" in low or " ac " in low:
        return "ac"
    if "pool" in low:
        return "pool_pump"
    return None


def _phrases(task: dict[str, Any]) -> list[tuple[str, bool]]:
    kind = kind_of(str(task.get("name") or task.get("label") or ""))
    own = str(task.get("name") or task.get("label") or "").lower().strip()
    out = list(_SAID.get(kind, [])) if kind else []
    if own:
        out.append((own, True))
    return out


def _norm(text: str) -> str:
    t = text.lower().replace("’", "'")
    t = re.sub(r"\b([ap])\.\s?m\b\.?", r"\1m", t)  # "p.m." -> "pm"
    return f" {t} "


def _mentions(text: str, tasks: Iterable[dict[str, Any]]) -> list[tuple[str, int, bool]]:
    """(task_id, position, strong) for each place an appliance is mentioned."""
    hay = _norm(text)
    out = []
    for t in tasks:
        is_dish = kind_of(str(t.get("name") or t.get("label") or "")) == "dishwasher"
        # "dishwasher" contains "washer": only the dishwasher may claim those words.
        h = hay if is_dish else re.sub(r"dish\s?wash\w*|dishes", lambda m: " " * len(m.group(0)), hay)
        for phrase, strong in _phrases(t):
            for m in re.finditer(rf"(?<![a-z]){re.escape(phrase)}(?![a-z])", h):
                out.append((t["id"], m.start(), strong))
    return out


# --- times -------------------------------------------------------------------

_WORD_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
             "nine": 9, "ten": 10, "eleven": 11, "twelve": 12}
_NUM = r"(\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve)"
_MER = r"\s?(am|pm)\b"


def _n(s: str) -> int:
    return _WORD_NUM.get(s, None) or int(s)


@dataclass
class TimeRead:
    hour: int          # 0-23
    minute: int
    pos: int
    guessed: bool      # am/pm was not said


def _meridiem(hour12: int, said: Optional[str], tail: str) -> tuple[int, bool]:
    """24-hour hour from a 1-12 hour, an explicit am/pm, or nearby words."""
    if said:
        return hour12 % 12 + (12 if said == "pm" else 0), False
    if re.match(r"\s*(in the morning|tomorrow morning|this morning|a\.?m)", tail):
        return hour12 % 12, False
    if re.match(r"\s*(tonight|this evening|in the evening|at night|p\.?m)", tail):
        # "1 tonight" means 1 AM: a small hour at night is after midnight.
        return (hour12 % 12 + 12, False) if 6 <= hour12 <= 11 else (hour12 % 12, False)
    # Evening plan: 6-11 are PM, 12 is midnight, 1-5 are the small hours.
    return (hour12 + 12, True) if 6 <= hour12 <= 11 else (hour12 % 12, True)


def find_time(text: str) -> Optional[TimeRead]:
    t = _norm(text)
    found: list[TimeRead] = []

    for m in re.finditer(r"(?<![a-z])(noon|midday|midnight)(?![a-z])", t):
        found.append(TimeRead(12 if m.group(1) != "midnight" else 0, 0, m.start(), False))

    for m in re.finditer(rf"(?<![a-z\d])(half|quarter)\s(past|after|to|till|before)\s{_NUM}(?:{_MER})?", t):
        h12 = _n(m.group(3))
        if not 1 <= h12 <= 12:
            continue
        if m.group(2) in ("past", "after"):
            mins = 30 if m.group(1) == "half" else 15
        else:
            if m.group(1) == "half":
                continue  # "half to" isn't English
            h12, mins = (h12 - 1) or 12, 45
        hour, guessed = _meridiem(h12, m.group(4), t[m.end():])
        found.append(TimeRead(hour, mins, m.start(), guessed))

    # 8:30 pm, 8.30pm, 8 30 pm, 830pm, 20:30
    for m in re.finditer(r"(?<![\d.:])(\d{1,2})(?:[:.]|\s(?=\d{2}\s?[ap]m))(\d{2})(?![\d.])(?:\s?(am|pm)\b)?", t):
        h, mins = int(m.group(1)), int(m.group(2))
        tail = t[m.end():]
        if mins > 59 or re.match(r"\s?(kw|kwh|h\b|hours?|hrs?|min|%|\$)", tail):
            continue
        if m.group(3) is None and h >= 13 and h <= 23:
            found.append(TimeRead(h, mins, m.start(), False))
        elif 1 <= h <= 12:
            hour, guessed = _meridiem(h, m.group(3), tail)
            found.append(TimeRead(hour, mins, m.start(), guessed))
        elif h == 0:
            found.append(TimeRead(0, mins, m.start(), False))
    for m in re.finditer(r"(?<![\d.:])(\d{1,2})(\d{2})\s?(am|pm)\b", t):
        h, mins = int(m.group(1)), int(m.group(2))
        if 1 <= h <= 12 and mins <= 59:
            found.append(TimeRead(h % 12 + (12 if m.group(3) == "pm" else 0), mins, m.start(), False))

    # 8 pm, eight pm, 8 o'clock, "by 8", "at 11 tonight"
    for m in re.finditer(rf"(?<![a-z\d.:]){_NUM}(?:\so'?clock)?{_MER}", t):
        h12 = _n(m.group(1))
        if 1 <= h12 <= 12:
            found.append(TimeRead(h12 % 12 + (12 if m.group(2) == "pm" else 0), 0, m.start(), False))
    for m in re.finditer(rf"(?<![a-z\d.:]){_NUM}\so'?clock", t):
        h12 = _n(m.group(1))
        if 1 <= h12 <= 12:
            hour, guessed = _meridiem(h12, None, t[m.end():])
            found.append(TimeRead(hour, 0, m.start(), guessed))
    for m in re.finditer(rf"(?<![a-z])(?:by|at|before|until|till|til|around|after|from|for)\s(?:about\s)?{_NUM}(?![\d:.a-z])", t):
        tail = t[m.end():]
        if re.match(r"\s?(am|pm|o'?clock|kw|kwh|h\b|hours?|hrs?|min|minutes|%)", tail):
            continue  # handled above, or not a time
        h12 = _n(m.group(1))
        if 1 <= h12 <= 12:
            hour, guessed = _meridiem(h12, None, tail)
            found.append(TimeRead(hour, 0, m.start(1), guessed))

    if not found:
        return None
    found.sort(key=lambda r: (r.pos, r.guessed))
    return found[0]


# --- the whole request ---------------------------------------------------------

_EARLIEST = re.compile(r"(not|no|don.?t|do not|can.?t|cannot)\s(start|run|begin|turn on|charge)\w*(\s[a-z']+){0,3}?\s(until|till|til|before)|"
                       r"no earlier than|not before|"
                       r"(start|run|begin|turn on|charge)\w*(\s[a-z']+){0,3}?\s(only\s)?after|wait (until|till|til)|not until")
_PREFERRED = re.compile(r"(start|run|begin|turn on)\w*\s(at|around|about)|prefer|like it to (start|run)|"
                        r"rather (start|run)")
_DEADLINE = re.compile(r"\b(by|before|done|ready|finish|finished|complete|completed|end|over|until|till|"
                       r"leave|leaving|need)\b")


@dataclass
class Reading:
    task_id: Optional[str] = None
    field: str = "deadline_slot"
    hhmm: Optional[str] = None
    time: Optional[TimeRead] = None
    choices: list[str] = dc_field(default_factory=list)   # task ids when the wording fits several

    @property
    def complete(self) -> bool:
        return bool(self.task_id and self.hhmm)


def read_request(text: str, tasks: list[dict[str, Any]]) -> Reading:
    """Best reading of one resident message against that home's own appliances."""
    tm = find_time(text)
    mentions = _mentions(text, tasks)
    if any(s for _, _, s in mentions):
        mentions = [m for m in mentions if m[2]]
    out = Reading(time=tm)
    if tm:
        out.hhmm = f"{tm.hour:02d}:{tm.minute:02d}"
    ids = list(dict.fromkeys(m[0] for m in mentions))
    if len(ids) == 1:
        out.task_id = ids[0]
    elif len(ids) > 1:
        # Several appliances named: take the one mentioned closest to the time
        # ("My dryer must finish by 10 pm. You can move the dishwasher.").
        anchor = tm.pos if tm else 0
        best: dict[str, int] = {}
        for tid, pos, _ in mentions:
            best[tid] = min(best.get(tid, 10**6), abs(pos - anchor))
        ranked = sorted(best.items(), key=lambda kv: kv[1])
        if ranked[0][1] < ranked[1][1]:
            out.task_id = ranked[0][0]
        else:
            out.choices = [tid for tid, d in ranked if d == ranked[0][1]]
    elif len(tasks) == 1 and tm:
        out.task_id = tasks[0]["id"]  # only one appliance: "have it done by 10" can only mean that one

    low = _norm(text)
    if _EARLIEST.search(low):
        out.field = "earliest_slot"
    elif _PREFERRED.search(low) and not _DEADLINE.search(low):
        out.field = "preferred_start_slot"
    return out


def without_questions(text: str) -> str:
    """Drop the agent's own earlier questions from a follow-up, so code reads only what the
    resident said: 'AC by 11 pm' + 'The agent asked: "...finished or started?"' + 'Finished'."""
    t = re.sub(r'\nThe agent asked: ".*?"(?=\n|$)', " ", text, flags=re.S)
    return re.sub(r'\nThe resident answered: "(.*?)"(?=\n|$)', r" \1", t, flags=re.S)
