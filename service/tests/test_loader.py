"""The Supabase loader, run end to end against a fake client (no network, no keys)."""
import csv
from pathlib import Path

import pytest

from app.config import get_settings
from scripts import load_csv_to_supabase as loader
from tests.test_data_layer import FLIGHT_HEADER, write

B_HEADER = ["booking_id", "party_size", "lead_passenger_name", "cancelled_flight_no", "origin_airport", "destination_airport",
            "scheduled_departure", "cancellation_time", "fare_class", "fare_paid_usd", "waiver_eligible", "onward_connection_flight_no",
            "has_checked_bags", "needs_wheelchair_assist", "travels_with_infant", "loyalty_tier", "hotel_voucher_issued",
            "earliest_acceptable_departure", "agent_note"]


class Q:
    def __init__(self, db, table): self.db, self.table, self.op, self.rows = db, table, None, None
    def upsert(self, rows, on_conflict=None): self.op, self.rows = "upsert", rows; self.db.log.append(("upsert", self.table, len(rows), on_conflict)); return self
    def insert(self, rows): self.op, self.rows = "insert", rows; self.db.log.append(("insert", self.table, len(rows))); return self
    def delete(self): self.op = "delete"; return self
    def in_(self, col, vals): self.db.log.append(("delete", self.table, col, tuple(vals))); return self
    def select(self, *_a, count=None, **_k): self.op = "count"; return self
    def limit(self, _n): return self

    def execute(self):
        if self.op in ("upsert", "insert"):
            self.db.rows.setdefault(self.table, []).extend(self.rows)
        return type("R", (), {"count": len(self.db.rows.get(self.table, [])), "data": []})()


class FakeDB:
    def __init__(self): self.log, self.rows = [], {}
    def table(self, name): return Q(self, name)


@pytest.fixture
def files(tmp_path):
    good_b = ["B1", "2", "A. B", "WN1", "DEN", "PHX", "2026-11-16T07:40:00", "2026-11-16T04:12:00", "Anytime", "100", "true", "",
              "true", "false", "false", "None", "false", "2026-11-18T12:00:00", ""]
    good_f = ["WN1", "DEN", "PHX", "2026-11-18T06:00", "2026-11-18T08:00", "737-800", "2", "2", "Anytime", "100", "scheduled", "false"]
    trunc = ["WN1154", "LAS", "DEN", "2026", "", "", "", "", "", "", "", ""]
    return write(tmp_path, "b.csv", B_HEADER, [good_b]), write(tmp_path, "f.csv", FLIGHT_HEADER, [good_f, trunc])


def run(monkeypatch, files, argv=()):
    db = FakeDB()
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-role-secret")
    get_settings.cache_clear()
    import supabase
    monkeypatch.setattr(supabase, "create_client", lambda url, key: db)
    code = loader.main(["--bookings", files[0], "--flights", files[1], *argv])
    get_settings.cache_clear()
    return code, db


def test_loader_upserts_both_tables_quarantines_the_bad_row_and_verifies(monkeypatch, files, capsys):
    code, db = run(monkeypatch, files)
    out = capsys.readouterr().out
    assert code == 0
    assert ("upsert", "cancelled_bookings", 1, "booking_id") in db.log and ("upsert", "open_seats", 1, "flight_no") in db.log
    assert any(e[:2] == ("insert", "ingest_rejects") for e in db.log)
    assert db.rows["ingest_rejects"][0]["row_data"]["flight_no"] == "WN1154"
    assert "verified in Supabase" in out and "service-role-secret" not in out


def test_loader_clears_old_rejects_so_a_rerun_does_not_duplicate_them(monkeypatch, files):
    _, db = run(monkeypatch, files)
    assert ("delete", "ingest_rejects", "source", ("cancelled_bookings", "open_seats")) in db.log


def test_dry_run_touches_nothing(monkeypatch, files, capsys):
    code, db = run(monkeypatch, files, ["--dry-run"])
    assert code == 0 and db.log == [] and "rejected rows: 1" in capsys.readouterr().out


def test_loader_refuses_to_run_without_keys(monkeypatch, files):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    get_settings.cache_clear()
    monkeypatch.setattr(loader, "get_settings", lambda: type("S", (), {"supabase_url": "", "supabase_service_role_key": "", "bookings_csv": files[0], "flights_csv": files[1]})())
    assert loader.main(["--bookings", files[0], "--flights", files[1]]) == 2
