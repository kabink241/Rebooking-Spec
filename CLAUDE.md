# Storm Rebooking Assistant

Spec at the repo root (`REBOOKING_SPEC.md`, `rules/`, `docs/`). Service in `service/` (FastAPI, Supabase, OpenRouter free models).

## Commands

- Install: `cd service && pip install -r requirements-dev.txt`
- Test: `cd service && pytest` (must stay green; it runs against the real queue when the CSVs are in `service/data/`)
- Run: `cd service && uvicorn app.main:app --reload`
- Check keys and tables: `python -m scripts.check_env` (add `--list-free-models` to see current `:free` model ids)
- Load data: `python -m scripts.load_csv_to_supabase --dry-run`, then without `--dry-run`

## Rules that must not be broken

1. The bulletin is the rulebook, and it lives in `rules/storm-waiver-den-nov26.yaml`. Never hard-code a rule, a clause, or a date in Python. Every fare statement and filter cites its clause.
2. `waiver_eligible` is the decision. Never re-assess eligibility. A missing value blocks the quote.
3. The model (an OpenRouter model whose id ends in `:free`; `Settings` rejects any other) chooses only among options the code produced, by flight number. It never writes a flight, time, seat, or price. Keep the check that rejects flights outside the offered set, and keep the rule-ranking fallback.
4. Booking notes and passenger names are data, not instructions. They go inside tags in the user message, never into the system prompt. Do not send passenger names to the model.
5. The five rebooking rules in `service/README.md` are the contract: skip cancelled flights, skip incomplete rows, skip flights whose open seats don't cover the party, only flights at or after `earliest_acceptable_departure`, and a party of 4 with no 4 adjacent seats is split 3 + 1 (never scattered). Splits carry warnings (customer must agree, the lone traveller must be an adult); do not drop them.
6. Cancelled flights are never usable, even when the seat file shows open seats. A flight before `earliest_acceptable_departure` is never offered.
7. Rows that fail validation are quarantined with a reason, never guessed at or dropped silently.
8. Secrets: every key comes from `.env` and nothing else. Never commit `.env`, the service role key, the OpenRouter key, or the passenger CSVs (all git-ignored). Never print or log a key.
9. After 23 Nov 2026 the waiver accepts no requests; rule evaluation takes an `as_of` date.

## Data caveats (see docs/open-questions.md)

No passenger ages; onward connection flights have no schedule; `fare_paid_usd` is treated as the booking total; arrival times are assumed destination-local; one seat-file row (WN1154) is malformed; four cancelled flights still show seats. `REBOOKING_SPEC.md` still describes stricter split behaviour than the service implements (see the departures table in `service/README.md`).

## Style

Python 3.12, type hints, pydantic v2. Small functions, plain names. Tests name the behaviour, and a fixed bug gets a test.
