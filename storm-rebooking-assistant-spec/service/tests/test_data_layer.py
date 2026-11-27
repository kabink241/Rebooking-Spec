import csv
from pathlib import Path

import pytest

from app.ingest import load_bookings_csv, load_flights_csv, parse_flight_row
from app.repo import SupabaseRepo
from tests.helpers import booking, flight

FLIGHT_HEADER = ["flight_no", "origin_airport", "destination_airport", "departure_datetime", "arrival_datetime", "aircraft_type",
                 "open_seats_total", "open_seats_adjacent_max", "fare_class_open", "base_fare_usd", "flight_status", "weather_risk_flag"]


def write(tmp_path: Path, name: str, header, rows) -> str:
    p = tmp_path / name
    with open(p, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return str(p)


def test_malformed_flight_rows_are_quarantined_not_loaded(tmp_path):
    good = ["WN1", "DEN", "PHX", "2026-11-18T06:00", "2026-11-18T08:00", "737-800", "2", "2", "Anytime", "100", "scheduled", "false"]
    trunc = ["WN1154", "LAS", "DEN", "2026", "", "", "", "", "", "", "", ""]
    bad_status = ["WN2", "DEN", "PHX", "2026-11-18T06:00", "2026-11-18T08:00", "737-800", "2", "2", "Anytime", "100", "boarding", "false"]
    adj_gt = ["WN3", "DEN", "PHX", "2026-11-18T06:00", "2026-11-18T08:00", "737-800", "2", "3", "Anytime", "100", "scheduled", "false"]
    path = write(tmp_path, "f.csv", FLIGHT_HEADER, [good, trunc, bad_status, adj_gt])
    flights, rejects = load_flights_csv(path)
    assert [f.flight_no for f in flights] == ["WN1"]
    assert {r["row"]["flight_no"] for r in rejects} == {"WN1154", "WN2", "WN3"}


def test_a_bare_year_is_not_read_as_a_timestamp():
    row = dict(zip(FLIGHT_HEADER, ["W", "DEN", "PHX", "2026", "2026-11-18T08:00", "", "1", "1", "Anytime", "1", "scheduled", "false"]))
    with pytest.raises(ValueError):
        parse_flight_row(row)


def test_loyalty_none_is_a_value_not_a_missing_cell(tmp_path):
    header = ["booking_id", "party_size", "lead_passenger_name", "cancelled_flight_no", "origin_airport", "destination_airport",
              "scheduled_departure", "cancellation_time", "fare_class", "fare_paid_usd", "waiver_eligible", "onward_connection_flight_no",
              "has_checked_bags", "needs_wheelchair_assist", "travels_with_infant", "loyalty_tier", "hotel_voucher_issued",
              "earliest_acceptable_departure", "agent_note"]
    row = ["B1", "2", "A. B", "WN1", "DEN", "PHX", "2026-11-16T07:40:00", "2026-11-16T04:12:00", "Anytime", "100", "true", "",
           "true", "false", "false", "None", "false", "2026-11-18T12:00:00", ""]
    b, rej = load_bookings_csv(write(tmp_path, "b.csv", header, [row]))
    assert not rej and b[0].loyalty_tier == "None" and b[0].onward_connection_flight_no is None


def test_missing_waiver_flag_loads_as_none_so_the_quote_blocks(tmp_path):
    header = ["booking_id", "party_size", "origin_airport", "destination_airport", "scheduled_departure", "cancellation_time",
              "fare_class", "fare_paid_usd", "waiver_eligible", "earliest_acceptable_departure"]
    row = ["B1", "1", "DEN", "PHX", "2026-11-16T07:40:00", "2026-11-16T04:12:00", "Anytime", "100", "", "2026-11-18T12:00:00"]
    b, _ = load_bookings_csv(write(tmp_path, "b.csv", header, [row]))
    assert b[0].waiver_eligible is None


# ---------------------------------------------------------------- Supabase repo against a fake client
class FakeQuery:
    def __init__(self, rows, table):
        self.rows, self.table = rows, table
        self._filters, self._order, self._range, self._limit, self._insert, self._count = [], None, None, None, None, False

    def select(self, *_a, count=None, **_k): self._count = bool(count); return self
    def eq(self, k, v): self._filters.append((k, v)); return self
    def order(self, k, desc=False): self._order = (k, desc); return self
    def range(self, a, b): self._range = (a, b); return self
    def limit(self, n): self._limit = n; return self
    def insert(self, row): self._insert = row; return self

    def execute(self):
        if self._insert is not None:
            row = {**self._insert, "id": "uuid-1", "created_at": "2026-11-17T00:00:00"}
            self.rows.append(row)
            return type("R", (), {"data": [row], "count": None})()
        data = [r for r in self.rows if all(r.get(k) == v for k, v in self._filters)]
        if self._order:
            data.sort(key=lambda r: r[self._order[0]], reverse=self._order[1])
        total = len(data)
        if self._range:
            data = data[self._range[0]: self._range[1] + 1]
        if self._limit:
            data = data[: self._limit]
        return type("R", (), {"data": data, "count": total if self._count else None})()


class FakeSupabase:
    def __init__(self, tables): self.tables = tables
    def table(self, name): return FakeQuery(self.tables.setdefault(name, []), name)


def test_supabase_repo_reads_bookings_flights_and_stores_suggestions():
    b = booking(booking_id="B9").model_dump(mode="json")
    b["loyalty_tier"], b["agent_note"], b["loaded_at"] = None, None, "2026-11-17T00:00:00Z"  # nulls and extras as the database returns them
    f = flight("F1", "2026-11-18T10:00", 3, 3).model_dump(mode="json")
    repo = SupabaseRepo("", "", client=FakeSupabase({"cancelled_bookings": [b], "open_seats": [f], "rebooking_suggestions": []}))
    assert repo.count_bookings() == 1
    got = repo.get_booking("B9")
    assert got.loyalty_tier == "None" and got.agent_note == ""
    assert [x.flight_no for x in repo.flights_for_route("DEN", "PHX")] == ["F1"]
    sid = repo.save_suggestion({"booking_id": "B9", "status": "SUGGESTED"})
    assert sid == "uuid-1" and repo.latest_suggestion("B9")["status"] == "SUGGESTED"


def test_supabase_repo_refuses_to_start_without_keys():
    with pytest.raises(RuntimeError):
        SupabaseRepo("", "")


def test_supabase_repo_skips_incomplete_flight_rows_instead_of_failing_the_booking():
    good = flight("F1", "2026-11-18T10:00", 3, 3).model_dump(mode="json")
    blank = {**good, "flight_no": "F2", "open_seats_total": None}
    bad_time = {**good, "flight_no": "F3", "departure_datetime": "2026"}
    repo = SupabaseRepo("", "", client=FakeSupabase({"open_seats": [good, blank, bad_time]}))
    assert [f.flight_no for f in repo.flights_for_route("DEN", "PHX")] == ["F1"]
