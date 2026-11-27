from app.notes import parse_note


def test_must_sit_together_and_split_hint():
    assert parse_note("Party of 4 must sit together.").must_sit_together
    assert parse_note("Happy to split if needed.").happy_to_split


def test_children_counted_from_words():
    assert parse_note("Two children in party of 5.").children_count == 2


def test_urgency_and_constraints():
    s = parse_note("First flight out any routing. Land before 9pm local.")
    assert s.urgent_earliest and s.land_before_hour_local == 21
    assert parse_note("Funeral, time critical.").urgent_earliest
    assert parse_note("No overnight connection.").no_overnight_connection


def test_wheelchair_infant_rows_and_tags():
    assert parse_note("Wheelchair assist at DEN.").wheelchair
    assert parse_note("Lap infant on booking.").lap_infant
    assert parse_note("Party of 5 needs two rows.").needs_two_rows
    assert parse_note("Bags tagged to STL.").bags_tagged_to == "STL"


def test_unknown_text_is_kept_not_dropped():
    s = parse_note("Customer is a pilot for another airline.")
    assert s.unparsed == ["Customer is a pilot for another airline."]


def test_friday_notes_are_informational_only():
    s = parse_note("Cannot travel until Friday.")
    assert s.info and not s.unparsed
