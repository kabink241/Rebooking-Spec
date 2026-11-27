import os
from pathlib import Path

import pytest

from app.config import Settings
from app.picker import Picker
from app.repo import CsvRepo
from app.rules import RuleSet
from app.service import RebookingService
from app.models import BatchRequest
import asyncio

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT.parent / "supabase" / "setup.sql").read_text()


def test_migration_parses_with_the_postgres_parser():
    pglast = pytest.importorskip("pglast")
    assert len(pglast.parse_sql(SQL)) >= 10


def test_migration_enables_row_level_security_on_every_table():
    tables = [l.split("public.")[1].split()[0] for l in SQL.splitlines() if l.lower().startswith("create table")]
    for t in tables:
        assert f"alter table public.{t}" in " ".join(SQL.lower().split()).replace("  ", " ") or f"public.{t} " in SQL
    assert SQL.lower().count("enable row level security") == len(tables)


B = ROOT / "data" / "cancelled_bookings_denver_storm.csv"
F = ROOT / "data" / "flight_seat_availability.csv"


@pytest.mark.skipif(not (B.exists() and F.exists()), reason="real CSVs not present (they are not committed)")
def test_every_booking_is_answered_and_every_rule_holds_on_the_real_queue():
    s = Settings(_env_file=None, as_of_default="2026-11-17", use_model=False, bookings_csv=str(B), flights_csv=str(F))
    repo = CsvRepo(s.bookings_csv, s.flights_csv)
    assert len(repo.bookings) == 140 and len(repo.flights) == 153 and len(repo.rejects) == 1
    assert repo.rejects[0]["row"]["flight_no"] == "WN1154"  # the truncated row is quarantined, not used
    svc = RebookingService(s, repo, RuleSet.load(s.rules_path), Picker(s))
    out = asyncio.run(svc.batch(BatchRequest(persist=False)))
    assert out["summary"]["bookings"] == 140 and sum(out["summary"]["by_status"].values()) == 140
    flights = {f.flight_no: f for f in repo.flights}
    splits = 0
    for r in out["results"]:
        b = repo.get_booking(r["booking_id"])
        if not r["flights"]:
            assert r["status"] == "NO_OPTION" and r["status_reason"]
            continue
        groups = r["groups"]
        assert [g["flight_no"] for g in groups] == r["flights"] and r["reason"]
        for g in groups:
            f = flights[g["flight_no"]]
            assert f.flight_status != "cancelled"                                    # rule 1
            assert f.departure_datetime >= b.earliest_acceptable_departure           # rule 4
            assert (f.origin_airport, f.destination_airport) == (b.origin_airport, b.destination_airport)
            assert (g["documentation_line"] is None) == (not b.waiver_eligible)
        if r["split"]:                                                                # rule 5
            splits += 1
            a, z = (flights[g["flight_no"]] for g in groups)
            assert b.party_size == 4 and [g["seats"] for g in groups] == [3, 1] and a.flight_no != z.flight_no
            assert a.open_seats_adjacent_max >= 3 and z.open_seats_total >= 1
            eligible, _ = svc.rules.filter_flights(b, repo.flights_for_route(b.origin_airport, b.destination_airport))
            assert not any(f.open_seats_adjacent_max >= 4 for f in eligible)       # a split only when no 4 adjacent exists
        else:
            f = flights[groups[0]["flight_no"]]
            assert f.open_seats_total >= b.party_size                                 # rule 3
            if b.party_size == 4:
                assert f.open_seats_adjacent_max >= 4                                 # a party of 4 is never scattered
    assert splits == out["summary"]["splits"]
    assert "WN1154" not in {f for r in out["results"] for f in r["flights"]}
