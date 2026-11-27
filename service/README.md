# Storm Rebooking Service

FastAPI service that suggests one rebooking for each cancelled booking in the Denver storm queue. It reads bookings and open seats from Supabase, applies the rules below, and asks a free OpenRouter model to choose among the valid options. Built from `../REBOOKING_SPEC.md` and `../rules/storm-waiver-den-nov26.yaml`.

## The rules

| Rule | Where | Test |
|---|---|---|
| Skip flights whose `flight_status` is `cancelled` (even if the seat file shows open seats) | `rules.filter_flights` | `test_cancelled_flight_is_skipped_even_with_open_seats` |
| Skip incomplete flight rows (a departure that is only a year, blank seat counts, bad status) | `ingest.parse_flight_row`, strict model datetimes, `SupabaseRepo.flights_for_route` | `test_malformed_flight_rows_are_quarantined_not_loaded` |
| Skip flights whose open seats don't cover the party (`open_seats_total` below `party_size`) | `candidates.build_candidates` | `test_flight_whose_open_seats_do_not_cover_the_party_is_skipped` |
| Only flights at or after the booking's `earliest_acceptable_departure` | `rules.filter_flights` | `test_only_flights_at_or_after_the_earliest_acceptable_departure` |
| A party of 4 with no flight that has 4 adjacent open seats is split: 3 together on one flight, 1 on a different flight with an open seat | `candidates.build_candidates` | `test_party_of_four_without_four_adjacent_seats_is_split_three_and_one` |

On top of those, the bulletin's own filters apply (same airport pair, 18 to 23 Nov window for covered bookings, requests after 23 Nov routed to Revenue Management) and fares follow clauses 3 and 4.

## What it returns

For each booking: the flight number, or both flight numbers for a split (3-seat flight first), and a short reason.

```json
{ "booking_id": "BKG-10011", "status": "SUGGESTED", "flights": ["WN1088", "WN1048"], "split": true,
  "reason": "3 on WN1088 (departs 2026-11-20 07:50) and 1 on WN1048 (departs 2026-11-19 07:50); ...", "picked_by": "model", "model": "vendor/some-model:free",
  "groups": [{"flight_no": "WN1088", "seats": 3, "departure": "..."}, {"flight_no": "WN1048", "seats": 1, "departure": "..."}],
  "warnings": ["Split of a party of 4: the customer must agree ..."], "alternatives": [], "excluded_flights": {} }
```

`status` is `SUGGESTED`, `NO_OPTION` (with `status_reason` and `next_step`), `ROUTE_TO_REVENUE_MANAGEMENT`, or `BLOCKED`. Samples from the real queue: `examples/sample_results.json`.

## How the model is used

Code builds the valid candidates first. The model sees only those (plus the booking note, inside data tags) and answers with JSON naming the flight number(s). The answer is accepted only if it matches a candidate; anything else (an invented flight, bad JSON, a rate limit, an error, no key) falls back to rule ranking and is recorded in `picked_by` and `model_error`. A single candidate needs no model call. Passenger names are never sent. The prompt is `app/prompts/pick_system.md`.

`OPENROUTER_MODEL` must end in `:free`; the service refuses to start otherwise, so it cannot spend money. Free model ids change: run `python -m scripts.check_env --list-free-models` to see what exists now.

## Set up and run

1. `python -m venv .venv && . .venv/bin/activate && pip install -r requirements-dev.txt`
2. `cp .env.example .env` and fill it in. The service reads every key from `.env` (current directory, or the repo root). `.env` is git-ignored.
   - `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` (Project Settings, API). The service role key bypasses row level security: server-side only.
   - `OPENROUTER_API_KEY` (openrouter.ai/keys) and `OPENROUTER_MODEL` (a `:free` id).
   - `SERVICE_API_KEY`: a long random string; sent by callers as `X-API-Key`.
   - `AS_OF_DEFAULT=2026-11-17` to replay the 15 to 17 Nov queue (see "The rule date").
3. Create the tables: paste `../supabase/setup.sql` into the Supabase SQL editor and run it (safe to re-run).
4. Put the two CSVs in `data/` as `cancelled_bookings_denver_storm.csv` and `flight_seat_availability.csv` (git-ignored: they hold passenger names), or pass paths with `--bookings` and `--flights`.
5. `python -m scripts.load_csv_to_supabase --dry-run`, then `python -m scripts.load_csv_to_supabase`. It upserts both tables, quarantines bad rows into `ingest_rejects`, and reads the counts back (expect 140 bookings, 153 flights, 1 rejected row). Safe to re-run.
6. `python -m scripts.check_env`
7. `uvicorn app.main:app --reload` (docs at `/docs`).

CSV mode (`DATA_BACKEND=csv`) skips Supabase for local runs.

## Endpoints

`GET /health` (no auth) · `GET /bookings` · `GET /bookings/{id}/candidates` (rules only, no model, nothing stored) · `POST /bookings/{id}/suggest` · `POST /suggest/batch` (every booking, or `booking_ids`) · `GET /bookings/{id}/suggestions/latest`. Each suggestion is stored in `rebooking_suggestions` with the pick, alternatives, model, and any model error.

## The rule date

The waiver accepts requests through 23 Nov 2026 (clauses 1.5, 2.5). Every request uses an `as_of` date, defaulting to `AS_OF_DEFAULT`, or today. Today is after 23 Nov, so with no pinned date every booking returns `ROUTE_TO_REVENUE_MANAGEMENT`.

## Results on the real queue (rules only, as of 17 Nov)

140 bookings: 127 `SUGGESTED`, 13 `NO_OPTION`. Of the 21 parties of 4: 1 fits together on one flight, 7 are split 3 + 1, and 13 get no automatic option (no flight has 3 adjacent seats plus a second flight with a seat, so the service will not scatter a party of 4). 24 suggestions for other parties seat everyone on one flight but not all together (flagged in `warnings`).

## Read before relying on it

- **All 7 splits are for customers whose note says they must sit together.** The rule you gave splits whenever no flight has 4 adjacent seats. The service does it, and attaches warnings: the customer must agree, whoever flies alone must be an adult, keep children with an adult. The consent steps are not enforced by code.
- **"Cover" means `open_seats_total` at least the party size.** Adjacency only matters for the party-of-4 rule and for ranking, so a party of 3, 5, or 6 can be offered seats that are not all together (warned). A party of 4 is never scattered.
- **The single traveller in a split can leave before or after the group of three.** The rule only asks for another flight with an open seat. The reason shows both departure times; check the order makes sense for the customer.
- **No passenger ages** are in the data, so the service cannot check who flies alone. It warns instead.
- **Onward connections cannot be checked** (their schedules are not in the data). Warned on every booking that has one.
- **`fare_paid_usd` is treated as the booking total** and `base_fare_usd` as per passenger (OQ-01).

## What has not been run

- A live Supabase load, and a live OpenRouter call. The loader runs against a fake client, the OpenRouter client against a mock HTTP server, `supabase/setup.sql` passes the Postgres parser, and the real files dry-run cleanly. Run `check_env` and one `suggest` call after you connect.

## Where this departs from the spec

| Spec | Service | Why |
|---|---|---|
| 11.1, 11.2: age bands, who can fly alone, consent protocol before a split | Warnings only | Your split rule, and no ages in the data |
| 11.3: seats apart on one flight, seat moves, splits only with the customer's agreement | Not generated; a split is suggested whenever the rule fires | Same |
| 7.2: no default between the together and split options | One pick, with alternatives listed | You asked for one rebooking |
| 12: original confirmation number | `booking_id` stands in | No such column (OQ-12) |

`../REBOOKING_SPEC.md` still describes the stricter behaviour. Decide which one is right and update the other.

## Test

`pytest` runs 85 tests: the bulletin rules, the five rebooking rules, notes parsing, the picker (invented flights, bad JSON, injection), the OpenRouter client over a mock server (headers, retries, failures, no key leakage), the API, the Supabase repo and loader against fake clients, CSV quarantine, the migration SQL, and every one of the 140 real results checked against the rules when the CSVs are present.
