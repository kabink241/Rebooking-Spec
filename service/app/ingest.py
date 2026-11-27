"""CSV parsing shared by the CSV backend and the Supabase loader.

Rows that fail validation are quarantined with a reason, never silently dropped or guessed.
Datetimes are parsed here (not by pydantic) because pydantic reads a bare "2026" as a unix timestamp.
"""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import Booking, Flight

BOOKING_REQUIRED = [
    "booking_id", "party_size", "origin_airport", "destination_airport", "scheduled_departure",
    "cancellation_time", "fare_class", "fare_paid_usd", "earliest_acceptable_departure",
]
FLIGHT_REQUIRED = [
    "flight_no", "origin_airport", "destination_airport", "departure_datetime", "arrival_datetime",
    "open_seats_total", "open_seats_adjacent_max", "fare_class_open", "base_fare_usd", "flight_status",
]
VALID_STATUS = {"scheduled", "delayed", "cancelled"}
FARE_CLASSES = {"Wanna Get Away", "Wanna Get Away Plus", "Anytime", "Business Select"}


def _bool(v: str, field: str) -> bool:
    t = (v or "").strip().lower()
    if t in {"true", "1", "yes"}:
        return True
    if t in {"false", "0", "no"}:
        return False
    raise ValueError(f"{field}: not a boolean: {v!r}")


def _dt(v: str, field: str) -> datetime:
    try:
        d = datetime.fromisoformat(v.strip())
    except ValueError as exc:
        raise ValueError(f"{field}: not an ISO datetime: {v!r}") from exc
    if "T" not in v and " " not in v.strip():
        raise ValueError(f"{field}: date without a time: {v!r}")
    return d


def _missing(row: dict, required: list[str]) -> list[str]:
    return [k for k in required if (row.get(k) is None or str(row.get(k)).strip() == "")]


def parse_booking_row(row: dict) -> Booking:
    miss = _missing(row, BOOKING_REQUIRED)
    if miss:
        raise ValueError(f"missing required fields: {', '.join(miss)}")
    if row["fare_class"] not in FARE_CLASSES:
        raise ValueError(f"unknown fare_class: {row['fare_class']!r}")
    waiver: Optional[bool] = None
    if (row.get("waiver_eligible") or "").strip() != "":
        waiver = _bool(row["waiver_eligible"], "waiver_eligible")
    return Booking(
        booking_id=row["booking_id"].strip(),
        party_size=int(row["party_size"]),
        lead_passenger_name=row.get("lead_passenger_name", ""),
        cancelled_flight_no=row.get("cancelled_flight_no", ""),
        origin_airport=row["origin_airport"].strip(),
        destination_airport=row["destination_airport"].strip(),
        scheduled_departure=_dt(row["scheduled_departure"], "scheduled_departure"),
        cancellation_time=_dt(row["cancellation_time"], "cancellation_time"),
        fare_class=row["fare_class"],
        fare_paid_usd=float(row["fare_paid_usd"]),
        waiver_eligible=waiver,
        onward_connection_flight_no=(row.get("onward_connection_flight_no") or "").strip() or None,
        has_checked_bags=_bool(row.get("has_checked_bags", "false"), "has_checked_bags"),
        needs_wheelchair_assist=_bool(row.get("needs_wheelchair_assist", "false"), "needs_wheelchair_assist"),
        travels_with_infant=_bool(row.get("travels_with_infant", "false"), "travels_with_infant"),
        loyalty_tier=(row.get("loyalty_tier") or "None").strip() or "None",
        hotel_voucher_issued=_bool(row.get("hotel_voucher_issued", "false"), "hotel_voucher_issued"),
        earliest_acceptable_departure=_dt(row["earliest_acceptable_departure"], "earliest_acceptable_departure"),
        agent_note=(row.get("agent_note") or "").strip(),
    )


def parse_flight_row(row: dict) -> Flight:
    miss = _missing(row, FLIGHT_REQUIRED)
    if miss:
        raise ValueError(f"missing required fields: {', '.join(miss)}")
    if row["flight_status"] not in VALID_STATUS:
        raise ValueError(f"unknown flight_status: {row['flight_status']!r}")
    return Flight(
        flight_no=row["flight_no"].strip(),
        origin_airport=row["origin_airport"].strip(),
        destination_airport=row["destination_airport"].strip(),
        departure_datetime=_dt(row["departure_datetime"], "departure_datetime"),
        arrival_datetime=_dt(row["arrival_datetime"], "arrival_datetime"),
        aircraft_type=(row.get("aircraft_type") or "").strip() or None,
        open_seats_total=int(float(row["open_seats_total"])),
        open_seats_adjacent_max=int(float(row["open_seats_adjacent_max"])),
        fare_class_open=row["fare_class_open"],
        base_fare_usd=float(row["base_fare_usd"]),
        flight_status=row["flight_status"],
        weather_risk_flag=_bool(row.get("weather_risk_flag", "false"), "weather_risk_flag"),
    )


def _read(path: str | Path, parser, source: str):
    good, rejects = [], []
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for i, row in enumerate(csv.DictReader(fh), start=2):  # header is line 1
            try:
                good.append(parser(row))
            except Exception as exc:  # validation errors of any kind
                rejects.append({"source": source, "line": i, "row": row, "reason": str(exc).split("\n")[0]})
    return good, rejects


def load_bookings_csv(path):
    return _read(path, parse_booking_row, "cancelled_bookings")


def load_flights_csv(path):
    return _read(path, parse_flight_row, "open_seats")
