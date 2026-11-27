"""The five rebooking rules, one test each, plus the party-of-4 split."""
from app.candidates import build_candidates
from tests.helpers import AS_OF, RULES, SETTINGS, booking, family_flights, flight, three_together_flights


def run(b, flights):
    return build_candidates(b, flights, RULES, AS_OF, SETTINGS)


def keys(r):
    return [c.key for c in r.candidates]


# ---- rule 1: cancelled flights are skipped, even with open seats
def test_cancelled_flight_is_skipped_even_with_open_seats():
    r = run(booking(party_size=2), [flight("X1", "2026-11-18T10:00", 6, 6, status="cancelled"), flight("X2", "2026-11-18T11:00", 3, 3)])
    assert keys(r) == ["X2"] and "X1" in r.excluded["flight_status_not_usable_2.3"]


def test_a_cancelled_flight_is_never_used_in_a_split():
    r = run(booking(party_size=4), three_together_flights() + [flight("X", "2026-11-18T09:00", 8, 3, status="cancelled")])
    assert all("X" not in c.flights() for c in r.candidates)


# ---- rule 3: open seats must cover the party
def test_flight_whose_open_seats_do_not_cover_the_party_is_skipped():
    r = run(booking(party_size=3), [flight("S2", "2026-11-18T10:00", 2, 2), flight("S3", "2026-11-18T11:00", 3, 3)])
    assert keys(r) == ["S3"] and r.excluded["seats_do_not_cover_party"] == ["S2"]


def test_no_flight_covers_the_party_gives_no_option_and_a_next_step():
    r = run(booking(party_size=3), [flight("S2", "2026-11-18T10:00", 2, 2)])
    assert r.status == "NO_OPTION" and r.candidates == [] and "lead" in r.next_step.lower()


# ---- rule 4: at or after earliest_acceptable_departure
def test_only_flights_at_or_after_the_earliest_acceptable_departure():
    r = run(booking(party_size=1), [flight("E1", "2026-11-18T07:59", 5, 5), flight("E2", "2026-11-18T08:00", 5, 5), flight("E3", "2026-11-18T09:00", 5, 5)])
    assert keys(r) == ["E2", "E3"]


# ---- rule 5: party of 4 with no 4 adjacent seats is split 3 + 1
def test_party_of_four_with_four_adjacent_seats_is_not_split():
    r = run(booking(party_size=4), family_flights())
    assert r.split_needed is False and keys(r)[0] == "F_T" and all(c.kind == "SINGLE" for c in r.candidates)


def test_party_of_four_without_four_adjacent_seats_is_split_three_and_one():
    r = run(booking(party_size=4), three_together_flights())
    assert r.split_needed and r.status == "SUGGESTED"
    first = r.candidates[0]
    assert first.kind == "SPLIT"
    three, one = first.groups
    assert (three["seats"], one["seats"]) == (3, 1)
    assert three["open_seats_adjacent_max"] >= 3 and one["open_seats_total"] >= 1
    assert three["flight_no"] != one["flight_no"]


def test_split_pairs_the_three_together_flight_with_a_different_flight():
    r = run(booking(party_size=4), three_together_flights())
    for c in r.candidates:
        a, b = c.groups
        assert a["flight_no"] != b["flight_no"] and a["open_seats_adjacent_max"] >= 3


def test_split_respects_earliest_acceptable_departure_on_both_flights():
    b = booking(party_size=4, earliest_acceptable_departure="2026-11-19T00:00:00")
    r = run(b, three_together_flights())
    for c in r.candidates:
        assert all(g["departure"] >= "2026-11-19T00:00" for g in c.groups)
    assert "F_A" not in {f for c in r.candidates for f in c.flights()}


def test_split_needs_an_open_seat_on_the_other_flight():
    flights = [flight("A", "2026-11-18T18:00", 5, 3), flight("B", "2026-11-18T19:00", 0, 0)]
    r = run(booking(party_size=4), flights)
    assert not any(c.kind == "SPLIT" for c in r.candidates)  # B has no seat: filtered out


def test_party_of_four_is_never_scattered_when_no_split_is_possible():
    r = run(booking(party_size=4), [flight("ONLY", "2026-11-18T18:00", 4, 2)])
    assert r.status == "NO_OPTION" and r.candidates == [] and "no split is possible" in r.status_reason


def test_party_of_four_with_one_three_together_flight_but_no_second_flight_gets_no_split():
    r = run(booking(party_size=4), [flight("ONLY", "2026-11-18T18:00", 8, 3)])
    assert r.status == "NO_OPTION" and "different flight" in r.status_reason


def test_other_party_sizes_may_get_seats_that_are_not_all_together_ranked_last():
    r = run(booking(party_size=3), [flight("EARLY", "2026-11-18T09:00", 4, 1)])
    assert keys(r) == ["EARLY"] and not r.candidates[0].seats_all_adjacent


def test_the_split_rule_applies_only_to_parties_of_four():
    r = run(booking(party_size=3), [flight("A", "2026-11-18T18:00", 5, 2), flight("B", "2026-11-18T19:00", 5, 2)])
    assert not r.split_needed and all(c.kind == "SINGLE" for c in r.candidates)


# ---- ranking and warnings
def test_seats_together_beat_an_earlier_flight_with_scattered_seats():
    r = run(booking(party_size=3), [flight("EARLY", "2026-11-18T09:00", 4, 1), flight("LATER", "2026-11-18T15:00", 4, 3)])
    assert keys(r) == ["LATER", "EARLY"]


def test_split_warns_about_consent_and_that_the_lone_traveller_must_be_an_adult():
    r = run(booking(party_size=4, agent_note="Party of 4 must sit together."), three_together_flights())
    text = " ".join(r.split_warnings)
    assert "must agree" in text and "adult" in text and "must sit together" in text


def test_children_noted_adds_a_keep_with_an_adult_warning():
    r = run(booking(party_size=4, agent_note="Two children in party of 4."), three_together_flights())
    assert any("every child with an adult" in w for w in r.split_warnings)


def test_wheelchair_party_is_not_split():
    r = run(booking(party_size=4, needs_wheelchair_assist=True), three_together_flights())
    assert r.candidates == [] and "wheelchair" in r.status_reason.lower()


def test_onward_connection_is_flagged_not_assumed_feasible():
    r = run(booking(party_size=1, onward_connection_flight_no="WN3101"), [flight("F1", "2026-11-18T10:00", 3, 3)])
    assert any("WN3101" in w and "cannot be checked" in w for w in r.warnings)


def test_documentation_line_follows_the_waiver_flag_in_every_group():
    cov = run(booking(party_size=4), three_together_flights())
    non = run(booking(party_size=4, waiver_eligible=False), three_together_flights())
    assert all(g["documentation_line"] == "STORM WAIVER DEN NOV26 B1" for c in cov.candidates for g in c.groups)
    assert all(g["documentation_line"] is None for c in non.candidates for g in c.groups)


def test_no_flights_at_all():
    assert run(booking(party_size=1), []).status == "NO_OPTION"
