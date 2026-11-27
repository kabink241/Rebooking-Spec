-- Storm rebooking service: schema.
-- Run once: paste this whole file into the Supabase SQL editor and press Run (or: psql "$DATABASE_URL" -f supabase/setup.sql).
-- Times are local wall-clock times with no zone in the source data, so they are stored as `timestamp`.

create table if not exists public.cancelled_bookings (
    booking_id                     text primary key,
    party_size                     integer not null check (party_size between 1 and 20),
    lead_passenger_name            text not null default '',
    cancelled_flight_no            text not null default '',
    origin_airport                 char(3) not null,
    destination_airport            char(3) not null,
    scheduled_departure            timestamp not null,
    cancellation_time              timestamp not null,
    fare_class                     text not null check (fare_class in ('Wanna Get Away', 'Wanna Get Away Plus', 'Anytime', 'Business Select')),
    fare_paid_usd                  numeric(10, 2) not null check (fare_paid_usd >= 0),
    -- Null means "missing": the service blocks the quote instead of guessing (clause 1.4).
    waiver_eligible                boolean,
    onward_connection_flight_no    text,
    has_checked_bags               boolean not null default false,
    needs_wheelchair_assist        boolean not null default false,
    travels_with_infant            boolean not null default false,
    loyalty_tier                   text not null default 'None' check (loyalty_tier in ('None', 'A-List', 'A-List Preferred')),
    hotel_voucher_issued           boolean not null default false,
    earliest_acceptable_departure  timestamp not null,
    agent_note                     text not null default '',
    loaded_at                      timestamptz not null default now(),
    check (origin_airport <> destination_airport)
);
create index if not exists cancelled_bookings_route_idx
    on public.cancelled_bookings (origin_airport, destination_airport);

create table if not exists public.open_seats (
    flight_no                text primary key,
    origin_airport           char(3) not null,
    destination_airport      char(3) not null,
    departure_datetime       timestamp not null,
    arrival_datetime         timestamp not null,
    aircraft_type            text,
    open_seats_total         integer not null check (open_seats_total >= 0),
    open_seats_adjacent_max  integer not null check (open_seats_adjacent_max >= 0),
    fare_class_open          text not null check (fare_class_open in ('Wanna Get Away', 'Wanna Get Away Plus', 'Anytime', 'Business Select')),
    base_fare_usd            numeric(10, 2) not null check (base_fare_usd >= 0),
    flight_status            text not null check (flight_status in ('scheduled', 'delayed', 'cancelled')),
    weather_risk_flag        boolean not null default false,
    snapshot_at              timestamptz not null default now(),
    check (open_seats_adjacent_max <= open_seats_total),
    check (arrival_datetime > departure_datetime)
);
create index if not exists open_seats_route_idx
    on public.open_seats (origin_airport, destination_airport, departure_datetime);

-- Rows that failed validation on load (for example a flight row with no seat counts). Kept for review, never used.
create table if not exists public.ingest_rejects (
    id          bigint generated always as identity primary key,
    source      text not null,
    line_no     integer,
    row_data    jsonb not null,
    reason      text not null,
    created_at  timestamptz not null default now()
);

-- One row per suggestion the service produced (audit trail for the pick and the inputs the agent supplied).
create table if not exists public.rebooking_suggestions (
    id                  uuid primary key default gen_random_uuid(),
    booking_id          text not null references public.cancelled_bookings (booking_id) on delete cascade,
    as_of               date not null,
    rule_set            text not null,
    rule_set_version    integer not null,
    status              text not null check (status in ('SUGGESTED', 'NEEDS_AGENT_INPUT', 'NO_OPTION', 'ROUTE_TO_REVENUE_MANAGEMENT', 'BLOCKED')),
    status_reason       text not null default '',
    pick                jsonb,
    options             jsonb not null default '[]'::jsonb,
    pending_options     jsonb not null default '[]'::jsonb,
    excluded_flights    jsonb not null default '{}'::jsonb,
    warnings            jsonb not null default '[]'::jsonb,
    picked_by           text not null check (picked_by in ('model', 'rules', 'rules_fallback', 'none')),
    model               text,
    model_reason        text,
    model_error         text,
    model_usage         jsonb,
    agent_inputs        jsonb not null default '{}'::jsonb,
    created_at          timestamptz not null default now()
);
create index if not exists rebooking_suggestions_booking_idx
    on public.rebooking_suggestions (booking_id, created_at desc);

create or replace view public.latest_suggestions as
    select distinct on (booking_id) *
    from public.rebooking_suggestions
    order by booking_id, created_at desc;

-- Row level security: on, with no policies. Only the service role (used server-side by the API) can read or write.
-- The agent front end must go through this API, never straight to the tables: they hold passenger names.
alter table public.cancelled_bookings      enable row level security;
alter table public.open_seats              enable row level security;
alter table public.ingest_rejects          enable row level security;
alter table public.rebooking_suggestions   enable row level security;
alter view  public.latest_suggestions      set (security_invoker = true);

comment on table public.rebooking_suggestions is
    'Service output. pick.lead_with_only is true when the pick needs the customer to agree (split or seats apart).';
