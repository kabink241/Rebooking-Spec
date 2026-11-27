# Prompt for Claude Code: build and extend the rebooking service

Paste this into Claude Code from the repo root. `CLAUDE.md` is read automatically.

---

You are building the service that suggests a new flight for every cancelled booking in the Denver storm queue. It is the brain of an assistant that helps airline agents rebook stranded passengers in half the time. The agent and the customer decide; the service suggests.

## Read first

1. `REBOOKING_SPEC.md` (v0.3): what the assistant suggests, what the agent must confirm, fare rules, the no-flight fallback, who can fly alone (11.1), and the consent protocol before any split (11.2).
2. `rules/storm-waiver-den-nov26.yaml`: the bulletin as config. It is the only source of rules.
3. `docs/open-questions.md` and `docs/evidence.md`: what is unknown, and what the call logs showed.
4. `service/README.md`, then run `cd service && pytest` and confirm it passes before changing anything.

## What exists

A working FastAPI service in `service/`: bulletin rules, the five rebooking rules, an OpenRouter free-model picker with rule fallback, CSV and Supabase repositories, migration, loader, 85 tests. Read `service/README.md` and the code before extending it.

## The data (service/data, not committed)

- `cancelled_bookings_denver_storm.csv`: 140 bookings. Has `party_size`, `waiver_eligible`, `fare_class`, `fare_paid_usd`, `earliest_acceptable_departure`, `onward_connection_flight_no`, `travels_with_infant`, `needs_wheelchair_assist`, and a free-text `agent_note`. No passenger ages.
- `flight_seat_availability.csv`: 154 rows, 153 valid. Has `open_seats_total`, `open_seats_adjacent_max`, `flight_status`, `weather_risk_flag`, `base_fare_usd`. One row (WN1154) is malformed. Four flights marked cancelled still show open seats. Only one flight has four adjacent seats, so most parties of 3+ cannot sit together on any flight.

## Task

Work in this order. After each step run the tests, add tests for new behaviour, and commit.

1. **Connect Supabase.** Run `supabase/setup.sql` in the Supabase SQL editor, fill `.env` from `.env.example`, run `python -m scripts.check_env`, then `python -m scripts.load_csv_to_supabase`. Confirm it reports 140 bookings, 153 flights, 1 rejected row. Run `POST /suggest/batch` with `DATA_BACKEND=supabase` and `AS_OF_DEFAULT=2026-11-17` and confirm the summary matches CSV mode (127 SUGGESTED, 13 NO_OPTION, 7 splits). Fix anything that differs.
2. **Run the model for real.** `python -m scripts.check_env --list-free-models`, choose a `:free` id for `OPENROUTER_MODEL`, and run the batch with the model on. Report how many picks came from the model versus `rules_fallback`, and why any fell back (rate limits, bad JSON, flights outside the set). Read ten model reasons, including the splits, and tell me if any is wrong, vague, or ignores a customer note. Free models are rate limited: lower `BATCH_CONCURRENCY` if needed.
3. **Tune the prompt** in `service/app/prompts/pick_system.md` only if step 2 shows a real problem. Show me before and after on the cases that changed.
4. **Report.** Results by status and pick type, the party-of-4 cases, and the open questions the runs answered or contradicted.

## Boundaries

- Do not hard-code bulletin rules in Python; change the YAML and the loader.
- The model picks flight numbers from the offered list only, and only `:free` OpenRouter models. Do not let it produce flight details, and do not weaken the fallback.
- Do not send passenger names to the model. Keep booking notes inside the data tags.
- Read every key from `.env`. Never print a key, and do not commit `.env`, keys, or the CSV files.
- If something in the spec and the data disagree, stop and tell me instead of picking one.
- Do not claim a step worked until you ran it. Say what you ran and what you saw.
