"""Turn the free-text agent_note into structured signals.

Anything the parser does not recognise stays in `unparsed` and is still shown to the model.
The note is customer/agent text: it is data, never instructions.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


@dataclass
class NoteSignals:
    raw: str = ""
    must_sit_together: bool = False  # customer position: no split, no seats apart
    happy_to_split: bool = False  # a hint only; never replaces consent
    children_count: int | None = None
    lap_infant: bool = False
    wheelchair: bool = False
    needs_two_rows: bool = False
    urgent_earliest: bool = False  # "first flight out", "funeral", "at the gate now"
    no_overnight_connection: bool = False
    land_before_hour_local: int | None = None
    needs_aisle: bool = False
    wants_same_fare_class: bool = False
    call_back: bool = False
    bags_tagged_to: str | None = None
    info: list[str] = field(default_factory=list)  # recognised but already encoded elsewhere
    unparsed: list[str] = field(default_factory=list)


def parse_note(note: str) -> NoteSignals:
    s = NoteSignals(raw=note or "")
    for sentence in [x.strip() for x in re.split(r"(?<=[.!?])\s+", note or "") if x.strip()]:
        t = sentence.lower()
        if "must sit together" in t:
            s.must_sit_together = True
        elif "happy to split" in t:
            s.happy_to_split = True
        elif m := re.search(r"\b(one|two|three|four|five|six)\s+children\b", t):
            s.children_count = _NUM[m.group(1)]
        elif "lap infant" in t:
            s.lap_infant = True
        elif "wheelchair" in t:
            s.wheelchair = True
            s.info.append(sentence)
        elif "needs two rows" in t:
            s.needs_two_rows = True
        elif "first flight out" in t or "funeral" in t or "at the gate now" in t:
            s.urgent_earliest = True
            s.info.append(sentence)
        elif "no overnight connection" in t:
            s.no_overnight_connection = True
        elif m := re.search(r"land before (\d{1,2})\s*pm", t):
            s.land_before_hour_local = int(m.group(1)) + 12
        elif "aisle" in t:
            s.needs_aisle = True
            s.info.append(sentence)
        elif "same fare class" in t:
            s.wants_same_fare_class = True
        elif "call back" in t:
            s.call_back = True
            s.info.append(sentence)
        elif m := re.search(r"bags tagged to ([a-z]{3})", t):
            s.bags_tagged_to = m.group(1).upper()
            s.info.append(sentence)
        elif "friday" in t or "original fare rules" in t or "own fare" in t:
            s.info.append(sentence)  # Friday is already in earliest_acceptable_departure
        else:
            s.unparsed.append(sentence)
    return s
