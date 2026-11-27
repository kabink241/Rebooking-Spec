"""The storm waiver bulletin as code. Every decision cites its clause.

Source of truth: rules/storm-waiver-den-nov26.yaml (loaded, never hard-coded here).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import yaml

from .models import Booking, Flight


@dataclass
class Gate:
    status: str  # OK | ROUTE_TO_REVENUE_MANAGEMENT | BLOCKED
    reason: str = ""
    clause_refs: list[str] = field(default_factory=list)


class RuleSet:
    def __init__(self, data: dict):
        self.data = data
        self.name: str = data["rule_set"]
        self.version: int = data["version"]
        self.requests_through: date = _as_date(data["requests_accepted_through"])
        win = data["flight_filters"]["covered"]["departure_window"]
        self.covered_window: tuple[date, date] = (_as_date(win[0]), _as_date(win[1]))
        self.usable_status: set[str] = set(data["flight_filters"]["covered"]["usable_status"])
        self.non_covered_applies_window: bool = bool(data["flight_filters"]["not_covered"]["apply_departure_window"])
        self.affected_stations: set[str] = set(data["scope"]["affected_stations"])
        self.doc_template: str = data["documentation"]["covered"]["line"]

    @classmethod
    def load(cls, path: str | Path) -> "RuleSet":
        with open(path, encoding="utf-8") as fh:
            return cls(yaml.safe_load(fh))

    # --- gates -----------------------------------------------------------------
    def gate(self, booking: Booking, as_of: date) -> Gate:
        if as_of > self.requests_through:
            return Gate(
                "ROUTE_TO_REVENUE_MANAGEMENT",
                f"Request dated {as_of} is after {self.requests_through}; agents do not process it.",
                ["1.5", "2.5"],
            )
        if booking.waiver_eligible is None:
            return Gate("BLOCKED", "waiver_eligible is missing, so no fare outcome can be stated.", ["1.3", "1.4"])
        return Gate("OK")

    # --- flight filters (clauses 2.1 to 2.4, 4.3) -----------------------------
    def filter_flights(self, booking: Booking, flights: list[Flight]) -> tuple[list[Flight], dict[str, list[str]]]:
        covered = bool(booking.waiver_eligible)
        kept: list[Flight] = []
        excluded: dict[str, list[str]] = {}

        def drop(reason: str, f: Flight) -> None:
            excluded.setdefault(reason, []).append(f.flight_no)

        lo, hi = self.covered_window
        for f in flights:
            if f.origin_airport != booking.origin_airport or f.destination_airport != booking.destination_airport:
                continue  # 2.2: original airport pair only. Not reported, it is every other route.
            if f.flight_status not in self.usable_status:
                drop("flight_status_not_usable_2.3", f)
            elif f.departure_datetime < booking.earliest_acceptable_departure:
                drop("departs_before_earliest_acceptable_2.4", f)
            elif (covered or self.non_covered_applies_window) and not (lo <= f.departure_datetime.date() <= hi):
                drop("outside_travel_window_2.1", f)
            elif f.open_seats_total <= 0:
                drop("no_open_seats", f)
            else:
                kept.append(f)
        kept.sort(key=lambda f: (f.departure_datetime, f.flight_no))
        return kept, excluded

    # --- fare outcome (Section 3 and 4.1) -------------------------------------
    def fare_outcome(self, booking: Booking, group_size: int, flight: Flight, is_split: bool) -> dict:
        paid_share = round(booking.fare_paid_usd * group_size / booking.party_size, 2)
        if booking.waiver_eligible:
            refs = ["3.1", "3.2", "3.3", "3.4"] + (["3.5"] if is_split else [])
            return {
                "status": "COVERED_NO_DIFFERENCE",
                "fare_paid_usd": paid_share,
                "difference_usd": 0.0,
                "clause_refs": refs,
            }
        # Not covered: original fare class rules, difference collected if the open fare is higher (4.1).
        # ASSUMPTION (OQ-01): fare_paid_usd is the whole-booking total; base_fare_usd is per passenger.
        paid_pp = booking.fare_paid_usd / booking.party_size
        diff = round(max(0.0, flight.base_fare_usd - paid_pp) * group_size, 2)
        return {
            "status": "NOT_COVERED_DIFFERENCE",
            "fare_paid_usd": paid_share,
            "difference_usd": diff,
            "clause_refs": ["4.1"],
        }

    def documentation_line(self, booking: Booking) -> Optional[str]:
        """3.6 for covered bookings; 4.4 forbids it otherwise.

        ASSUMPTION (OQ-12): booking_id stands in for the original confirmation number.
        """
        if not booking.waiver_eligible:
            return None
        return self.doc_template.format(original_confirmation_number=booking.booking_id)


def _as_date(v) -> date:
    return v if isinstance(v, date) else date.fromisoformat(str(v))
