from __future__ import annotations

from datetime import date, datetime, timedelta

from app.config import Settings
from app.models import Booking, Flight
from app.rules import RuleSet

AS_OF = date(2026, 11, 17)
SETTINGS = Settings(_env_file=None, as_of_default=AS_OF, use_model=False)
RULES = RuleSet.load(SETTINGS.rules_path)


def booking(**kw) -> Booking:
    d = dict(
        booking_id="B1", party_size=2, lead_passenger_name="T. Tester", cancelled_flight_no="WN3000",
        origin_airport="DEN", destination_airport="PHX",
        scheduled_departure="2026-11-16T07:00:00", cancellation_time="2026-11-16T04:00:00",
        fare_class="Wanna Get Away", fare_paid_usd=400.0, waiver_eligible=True,
        earliest_acceptable_departure="2026-11-18T08:00:00", agent_note="",
    )
    d.update(kw)
    return Booking(**d)


def flight(no: str, dep: str, total: int, adj: int, status="scheduled", wx=False, base=200.0, hours=2.0,
           cls="Wanna Get Away", origin="DEN", dest="PHX") -> Flight:
    d = datetime.fromisoformat(dep)
    return Flight(
        flight_no=no, origin_airport=origin, destination_airport=dest, departure_datetime=d,
        arrival_datetime=d + timedelta(hours=hours), aircraft_type="737-800",
        open_seats_total=total, open_seats_adjacent_max=adj, fare_class_open=cls, base_fare_usd=base,
        flight_status=status, weather_risk_flag=wx,
    )


def three_together_flights():
    """Several flights with three adjacent seats, none with four."""
    return [
        flight("F_A", "2026-11-18T18:20", 7, 3),
        flight("F_B", "2026-11-19T13:25", 6, 3),
        flight("F_C", "2026-11-19T18:20", 9, 2),
    ]


def family_flights():
    """Three adjacent seats on the early flights; four together only three days later."""
    return three_together_flights() + [flight("F_T", "2026-11-21T13:25", 4, 4)]
