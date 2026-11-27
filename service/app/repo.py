"""Data access. CsvRepo for local runs and tests; SupabaseRepo for the real database."""
from __future__ import annotations

import uuid
from typing import Any, Optional, Protocol

from .ingest import load_bookings_csv, load_flights_csv
from .models import Booking, Flight


class Repo(Protocol):
    name: str

    def list_bookings(self, limit: int = 200, offset: int = 0) -> list[Booking]: ...
    def count_bookings(self) -> int: ...
    def get_booking(self, booking_id: str) -> Optional[Booking]: ...
    def flights_for_route(self, origin: str, destination: str) -> list[Flight]: ...
    def save_suggestion(self, record: dict) -> str: ...
    def latest_suggestion(self, booking_id: str) -> Optional[dict]: ...


class MemoryRepo:
    """Holds bookings and flights in memory. Used by CsvRepo and by tests."""

    name = "memory"

    def __init__(self, bookings: list[Booking], flights: list[Flight]):
        self.bookings, self.flights = list(bookings), list(flights)
        self._by_id = {b.booking_id: b for b in self.bookings}
        self._suggestions: list[dict] = []  # in memory only: passenger data is not written to disk

    def list_bookings(self, limit: int = 200, offset: int = 0) -> list[Booking]:
        return self.bookings[offset : offset + limit]

    def count_bookings(self) -> int:
        return len(self.bookings)

    def get_booking(self, booking_id: str) -> Optional[Booking]:
        return self._by_id.get(booking_id)

    def flights_for_route(self, origin: str, destination: str) -> list[Flight]:
        return [f for f in self.flights if f.origin_airport == origin and f.destination_airport == destination]

    def save_suggestion(self, record: dict) -> str:
        rid = str(uuid.uuid4())
        self._suggestions.append({**record, "id": rid})
        return rid

    def latest_suggestion(self, booking_id: str) -> Optional[dict]:
        rows = [r for r in self._suggestions if r["booking_id"] == booking_id]
        return rows[-1] if rows else None


class CsvRepo(MemoryRepo):
    name = "csv"

    def __init__(self, bookings_csv: str, flights_csv: str):
        bookings, self.booking_rejects = load_bookings_csv(bookings_csv)
        flights, self.flight_rejects = load_flights_csv(flights_csv)
        super().__init__(bookings, flights)

    @property
    def rejects(self) -> list[dict]:
        return self.booking_rejects + self.flight_rejects


class SupabaseRepo:
    """Reads bookings and seats from Supabase and writes suggestions back.

    Uses the service role key, which bypasses row level security: run it server-side only.
    """

    name = "supabase"

    def __init__(self, url: str, key: str, client: Any = None):
        if client is None:
            if not url or not key:
                raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required for DATA_BACKEND=supabase")
            from supabase import create_client

            client = create_client(url, key)
        self.sb = client

    @staticmethod
    def _clean_booking(row: dict) -> dict:
        row = dict(row)
        for k in ("loyalty_tier",):
            if row.get(k) is None:
                row[k] = "None"
        for k in ("agent_note", "lead_passenger_name", "cancelled_flight_no"):
            if row.get(k) is None:
                row[k] = ""
        return row

    def list_bookings(self, limit: int = 200, offset: int = 0) -> list[Booking]:
        rows = (
            self.sb.table("cancelled_bookings").select("*").order("booking_id")
            .range(offset, offset + limit - 1).execute().data
        )
        return [Booking.model_validate(self._clean_booking(r)) for r in rows]

    def count_bookings(self) -> int:
        res = self.sb.table("cancelled_bookings").select("booking_id", count="exact").limit(1).execute()
        return int(res.count or 0)

    def get_booking(self, booking_id: str) -> Optional[Booking]:
        rows = self.sb.table("cancelled_bookings").select("*").eq("booking_id", booking_id).limit(1).execute().data
        return Booking.model_validate(self._clean_booking(rows[0])) if rows else None

    def flights_for_route(self, origin: str, destination: str) -> list[Flight]:
        rows = (
            self.sb.table("open_seats").select("*")
            .eq("origin_airport", origin).eq("destination_airport", destination).execute().data
        )
        flights = []
        for r in rows:
            try:
                flights.append(Flight.model_validate(r))
            except Exception:  # incomplete or inconsistent row (blank seat counts, bad times): skip it
                continue
        return flights

    def save_suggestion(self, record: dict) -> str:
        res = self.sb.table("rebooking_suggestions").insert(record).execute()
        return res.data[0]["id"]

    def latest_suggestion(self, booking_id: str) -> Optional[dict]:
        rows = (
            self.sb.table("rebooking_suggestions").select("*").eq("booking_id", booking_id)
            .order("created_at", desc=True).limit(1).execute().data
        )
        return rows[0] if rows else None


def build_repo(settings) -> Repo:
    if settings.data_backend == "supabase":
        return SupabaseRepo(settings.supabase_url, settings.supabase_service_role_key)
    return CsvRepo(settings.bookings_csv, settings.flights_csv)
