"""Which rebooking can this booking use? Rules only, no model.

The model (picker.py) chooses among what this module returns, so it can never invent a flight.

Rules, in the order they are applied:
  1. Skip flights whose flight_status is cancelled (and keep to the bulletin's filters in rules.py).
  2. Incomplete flight rows (a departure that is only a year, blank seat counts) never get here:
     ingest quarantines them.
  3. Skip flights whose open seats do not cover the party (open_seats_total < party_size).
  4. Only flights leaving at or after the booking's earliest_acceptable_departure.
  5. A party of 4 with no flight that has 4 adjacent open seats is split: 3 together on one flight
     (open_seats_adjacent_max >= 3) and 1 on a different flight with an open seat.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .config import Settings
from .models import Booking, Flight
from .notes import NoteSignals, parse_note
from .rules import RuleSet

SPLIT_PARTY_SIZE = 4


@dataclass
class Candidate:
    key: str  # "WN1136" or "WN1028+WN1056" (3-together flight first)
    kind: str  # SINGLE | SPLIT
    groups: list[dict]
    arrives_together: bool
    seats_all_adjacent: bool
    arrival_gap_minutes: int
    first_departure: str
    final_arrival: str
    risk_flags: list[str]
    fare_difference_total_usd: float
    summary: str

    def flights(self) -> list[str]:
        return [g["flight_no"] for g in self.groups]


@dataclass
class CandidateResult:
    booking_id: str
    status: str  # SUGGESTED | NO_OPTION | ROUTE_TO_REVENUE_MANAGEMENT | BLOCKED
    status_reason: str = ""
    next_step: str = ""
    candidates: list[Candidate] = field(default_factory=list)
    excluded: dict[str, list[str]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    split_warnings: list[str] = field(default_factory=list)  # shown only when the pick is a split
    signals: Optional[NoteSignals] = None
    split_needed: bool = False


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="minutes")


def _group(booking: Booking, rules: RuleSet, f: Flight, seats: int, adjacent: bool, is_split: bool) -> dict:
    return {
        "flight_no": f.flight_no,
        "seats": seats,
        "departure": _iso(f.departure_datetime),
        "arrival": _iso(f.arrival_datetime),
        "flight_status": f.flight_status,
        "weather_risk": f.weather_risk_flag,
        "seats_adjacent": adjacent,
        "open_seats_total": f.open_seats_total,
        "open_seats_adjacent_max": f.open_seats_adjacent_max,
        "fare_outcome": rules.fare_outcome(booking, seats, f, is_split),
        "documentation_line": rules.documentation_line(booking),
    }


def _candidate(booking: Booking, groups: list[dict]) -> Candidate:
    arrivals = [datetime.fromisoformat(g["arrival"]) for g in groups]
    departures = [datetime.fromisoformat(g["departure"]) for g in groups]
    flags = sorted({"DELAYED" for g in groups if g["flight_status"] == "delayed"} |
                   {"WEATHER_RISK" for g in groups if g["weather_risk"]})
    split = len(groups) > 1
    if split:
        summary = " and ".join(f"{g['seats']} on {g['flight_no']} (departs {g['departure'].replace('T', ' ')})" for g in groups)
    else:
        g = groups[0]
        summary = f"All {g['seats']} on {g['flight_no']}" + ("" if g["seats_adjacent"] else " (seats not all together)")
    gap = int((max(arrivals) - min(arrivals)).total_seconds() // 60)
    return Candidate(
        key="+".join(g["flight_no"] for g in groups),
        kind="SPLIT" if split else "SINGLE",
        groups=groups,
        arrives_together=not split,
        seats_all_adjacent=all(g["seats_adjacent"] for g in groups) and not split,
        arrival_gap_minutes=gap,
        first_departure=_iso(min(departures)),
        final_arrival=_iso(max(arrivals)),
        risk_flags=flags,
        fare_difference_total_usd=round(sum(g["fare_outcome"]["difference_usd"] for g in groups), 2),
        summary=summary,
    )


def rank_key(c: Candidate):
    """Together beats split, adjacent beats scattered, then earliest final arrival, fewer flags, no fare difference."""
    return (0 if c.arrives_together else 1, 0 if c.seats_all_adjacent or not c.arrives_together else 1,
            c.final_arrival, len(c.risk_flags), c.arrival_gap_minutes, c.fare_difference_total_usd)


def build_candidates(booking: Booking, flights: list[Flight], rules: RuleSet, as_of, settings: Settings) -> CandidateResult:
    signals = parse_note(booking.agent_note)
    res = CandidateResult(booking.booking_id, "NO_OPTION", signals=signals)

    gate = rules.gate(booking, as_of)
    if gate.status != "OK":
        res.status = gate.status
        res.status_reason = f"{gate.reason} (clauses {', '.join(gate.clause_refs)})"
        res.next_step = ("Send to Revenue Management for manual review." if gate.status == "ROUTE_TO_REVENUE_MANAGEMENT"
                         else "Resolve the waiver_eligible value before quoting.")
        return res

    # Rules 1, 4 and the bulletin filters: not cancelled, at/after earliest_acceptable_departure, same airports, window.
    eligible, res.excluded = rules.filter_flights(booking, flights)
    _warnings(res, booking, signals)

    n = booking.party_size
    # Rule 3: open seats must cover the party.
    covering = [f for f in eligible if f.open_seats_total >= n]
    res.excluded["seats_do_not_cover_party"] = [f.flight_no for f in eligible if f.open_seats_total < n]

    cands: list[Candidate] = []
    has_four_together = any(f.open_seats_adjacent_max >= SPLIT_PARTY_SIZE for f in eligible)
    if n == SPLIT_PARTY_SIZE and not has_four_together:
        # Rule 5: no flight has 4 adjacent seats, so split: 3 together on one flight, 1 on another flight with an open seat.
        # A party of 4 is never scattered across one flight: if no split exists, there is no automatic suggestion.
        res.split_needed = True
        if booking.needs_wheelchair_assist or signals.wheelchair:
            res.status_reason = "No flight has 4 adjacent seats, and a party with a wheelchair user is not split."
        else:
            for a in (f for f in eligible if f.open_seats_adjacent_max >= 3):
                for b in (f for f in eligible if f.flight_no != a.flight_no and f.open_seats_total >= 1):
                    cands.append(_candidate(booking, [_group(booking, rules, a, 3, True, True),
                                                      _group(booking, rules, b, 1, b.open_seats_adjacent_max >= 1, True)]))
            if cands:
                _split_warnings(res, booking, signals)
            else:
                res.status_reason = ("No flight has 4 adjacent seats, and no split is possible: a split needs one flight with 3 "
                                     "adjacent seats and a different flight with an open seat.")
    else:
        cands = [_candidate(booking, [_group(booking, rules, f, n, f.open_seats_adjacent_max >= n, False)]) for f in covering]

    cands.sort(key=rank_key)
    res.candidates = cands[: settings.max_candidates]
    if res.candidates:
        res.status = "SUGGESTED"
    else:
        if not res.status_reason:
            res.status_reason = ("No eligible flight on this route has open seats that cover the party." if eligible
                                 else "No eligible flight on this route (all cancelled, too early, outside the window, or full).")
        res.next_step = "Escalate to a lead; later dates or other routing are outside this service (SPEC section 10)."
    return res


def _warnings(res: CandidateResult, b: Booking, s: NoteSignals) -> None:
    w = res.warnings
    if b.onward_connection_flight_no:
        w.append(f"Onward connection {b.onward_connection_flight_no} cannot be checked (its schedule is not in the data).")
    if s.no_overnight_connection:
        w.append("Customer said no overnight connection; not verifiable from the data.")
    if s.land_before_hour_local is not None:
        w.append(f"Customer wants to land before {s.land_before_hour_local - 12}pm local; check the arrival time.")
    if b.travels_with_infant:
        w.append("Booking travels with an infant: confirm whether the infant needs a seat.")
    if b.needs_wheelchair_assist or s.wheelchair:
        w.append("Wheelchair assistance needed at both ends.")
    if s.unparsed:
        w.append("Unrecognised note text, read it: " + " | ".join(s.unparsed))


def _split_warnings(res: CandidateResult, b: Booking, s: NoteSignals) -> None:
    w = res.split_warnings
    w.append("Split of a party of 4: the customer must agree before booking, and whoever flies alone must be an adult "
             "(no child or lap infant without an adult). Ask who is a child.")
    if s.must_sit_together:
        w.append("The booking note says the party must sit together: a split needs the customer's explicit agreement.")
    if s.children_count or b.travels_with_infant:
        w.append("Children or an infant are on this booking: keep every child with an adult.")
