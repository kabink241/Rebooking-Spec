from datetime import date

from app.candidates import build_candidates
from tests.helpers import AS_OF, RULES, SETTINGS, booking, flight


def test_cancelled_flight_is_never_usable_even_with_seats():  # clause 2.3
    kept, ex = RULES.filter_flights(booking(), [flight("X1", "2026-11-18T10:00", 5, 5, status="cancelled"),
                                                flight("X2", "2026-11-18T11:00", 5, 5)])
    assert [f.flight_no for f in kept] == ["X2"]
    assert ex["flight_status_not_usable_2.3"] == ["X1"]


def test_delayed_flight_is_usable():  # clause 2.3
    kept, _ = RULES.filter_flights(booking(), [flight("D1", "2026-11-18T10:00", 3, 3, status="delayed")])
    assert [f.flight_no for f in kept] == ["D1"]


def test_flights_before_earliest_acceptable_departure_are_dropped():  # clause 2.4
    kept, ex = RULES.filter_flights(booking(), [flight("E1", "2026-11-18T07:59", 5, 5), flight("E2", "2026-11-18T08:00", 5, 5)])
    assert [f.flight_no for f in kept] == ["E2"]
    assert "departs_before_earliest_acceptable_2.4" in ex


def test_other_airport_pair_is_never_offered():  # clause 2.2
    kept, _ = RULES.filter_flights(booking(), [flight("A1", "2026-11-18T10:00", 5, 5, dest="LAS")])
    assert kept == []


def test_window_applies_to_covered_but_not_to_non_covered():  # 2.1 and the literal reading of 4.3
    late = flight("L1", "2026-11-24T10:00", 5, 5)
    covered, ex = RULES.filter_flights(booking(waiver_eligible=True), [late])
    assert covered == [] and "outside_travel_window_2.1" in ex
    not_covered, _ = RULES.filter_flights(booking(waiver_eligible=False), [late])
    assert [f.flight_no for f in not_covered] == ["L1"]


def test_zero_seat_flights_are_dropped():
    kept, ex = RULES.filter_flights(booking(), [flight("Z1", "2026-11-18T10:00", 0, 0)])
    assert kept == [] and ex["no_open_seats"] == ["Z1"]


def test_requests_after_the_waiver_ends_go_to_revenue_management():  # 1.5, 2.5
    r = build_candidates(booking(), [flight("F1", "2026-11-19T10:00", 5, 5)], RULES, date(2026, 11, 24), SETTINGS)
    assert r.status == "ROUTE_TO_REVENUE_MANAGEMENT" and r.candidates == []
    assert "2.5" in r.status_reason


def test_missing_waiver_flag_blocks_the_quote():  # 1.4
    r = build_candidates(booking(waiver_eligible=None), [flight("F1", "2026-11-19T10:00", 5, 5)], RULES, AS_OF, SETTINGS)
    assert r.status == "BLOCKED" and r.candidates == []


def test_covered_fare_is_unchanged_whatever_the_open_fare_or_class():  # 3.1 to 3.3
    b = booking(party_size=2, fare_paid_usd=300.0, fare_class="Wanna Get Away")
    f = flight("H1", "2026-11-18T10:00", 4, 4, base=480.0, cls="Business Select")
    out = RULES.fare_outcome(b, 2, f, False)
    assert out["status"] == "COVERED_NO_DIFFERENCE" and out["difference_usd"] == 0.0 and out["fare_paid_usd"] == 300.0
    assert {"3.1", "3.2", "3.3", "3.4"} <= set(out["clause_refs"])


def test_covered_split_cites_clause_3_5_and_prorates_nothing_extra():
    out = RULES.fare_outcome(booking(party_size=4, fare_paid_usd=1000.0), 3, flight("H1", "2026-11-18T10:00", 4, 4), True)
    assert "3.5" in out["clause_refs"] and out["difference_usd"] == 0.0 and out["fare_paid_usd"] == 750.0


def test_non_covered_difference_only_when_open_fare_is_higher():  # 4.1
    b = booking(waiver_eligible=False, party_size=2, fare_paid_usd=400.0)  # $200 each
    higher = RULES.fare_outcome(b, 2, flight("H1", "2026-11-18T10:00", 4, 4, base=230.0), False)
    lower = RULES.fare_outcome(b, 2, flight("H2", "2026-11-18T10:00", 4, 4, base=150.0), False)
    assert higher["difference_usd"] == 60.0 and higher["status"] == "NOT_COVERED_DIFFERENCE"
    assert lower["difference_usd"] == 0.0


def test_loyalty_tier_never_changes_the_fare():  # 4.2
    f = flight("H1", "2026-11-18T10:00", 4, 4, base=230.0)
    a = RULES.fare_outcome(booking(waiver_eligible=False, loyalty_tier="None"), 2, f, False)
    b = RULES.fare_outcome(booking(waiver_eligible=False, loyalty_tier="A-List Preferred"), 2, f, False)
    assert a == b


def test_documentation_line_only_on_covered_bookings():  # 3.6, 4.4
    assert RULES.documentation_line(booking(booking_id="BKG-1", waiver_eligible=True)) == "STORM WAIVER DEN NOV26 BKG-1"
    assert RULES.documentation_line(booking(waiver_eligible=False)) is None
