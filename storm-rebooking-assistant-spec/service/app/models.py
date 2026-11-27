"""Typed records for bookings, flights, and the request body."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


def _strict_datetime(v):
    """Pydantic reads the string "2026" (or any bare number) as a unix timestamp. Refuse that: a flight
    time must be a full ISO date and time, otherwise the row is incomplete."""
    if isinstance(v, datetime):
        return v
    if isinstance(v, str) and "T" in v.strip().upper().replace(" ", "T") and "-" in v:
        return v
    raise ValueError(f"not a full ISO date and time: {v!r}")


class Booking(BaseModel):
    booking_id: str
    party_size: int = Field(ge=1)
    lead_passenger_name: str = ""
    cancelled_flight_no: str = ""
    origin_airport: str
    destination_airport: str
    scheduled_departure: datetime
    cancellation_time: datetime
    fare_class: str
    fare_paid_usd: float = Field(ge=0)
    waiver_eligible: Optional[bool] = None  # None means missing: the quote is blocked
    onward_connection_flight_no: Optional[str] = None
    has_checked_bags: bool = False
    needs_wheelchair_assist: bool = False
    travels_with_infant: bool = False
    loyalty_tier: str = "None"  # never affects fare (clause 4.2)
    hotel_voucher_issued: bool = False
    earliest_acceptable_departure: datetime
    agent_note: str = ""

    _dt = field_validator("scheduled_departure", "cancellation_time", "earliest_acceptable_departure", mode="before")(_strict_datetime)


class Flight(BaseModel):
    flight_no: str
    origin_airport: str
    destination_airport: str
    departure_datetime: datetime
    arrival_datetime: datetime
    aircraft_type: Optional[str] = None
    open_seats_total: int = Field(ge=0)
    open_seats_adjacent_max: int = Field(ge=0)
    fare_class_open: str
    base_fare_usd: float = Field(ge=0)
    flight_status: str  # scheduled | delayed | cancelled
    weather_risk_flag: bool = False

    _dt = field_validator("departure_datetime", "arrival_datetime", mode="before")(_strict_datetime)

    @model_validator(mode="after")
    def _adjacent_not_above_total(self) -> "Flight":
        if self.open_seats_adjacent_max > self.open_seats_total:
            raise ValueError("open_seats_adjacent_max exceeds open_seats_total")
        return self


class SuggestRequest(BaseModel):
    as_of: Optional[date] = None
    use_model: Optional[bool] = None
    persist: bool = True


class BatchRequest(BaseModel):
    as_of: Optional[date] = None
    booking_ids: Optional[list[str]] = None  # default: every booking in the queue
    use_model: Optional[bool] = None
    persist: bool = True
    include_results: bool = True
