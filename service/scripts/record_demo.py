"""Run one booking live (Supabase + the free OpenRouter model) and record the real result in README.md.

    python -m scripts.record_demo BKG-10023

It reads the booking and seats from Supabase, asks the model, stores the suggestion, reads it back,
and only then rewrites the block between the demo markers in README.md. If the model did not make the
pick (rate limit, bad JSON, wrong model id) or the row was not stored, it says so and leaves README.md alone.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import REPO_ROOT, get_settings
from app.models import SuggestRequest

START, END = "<!-- demo:start -->", "<!-- demo:end -->"


def render_block(result: dict, stored_id: str, ts: str) -> str:
    shown = {k: result[k] for k in ("booking_id", "status", "flights", "split", "reason", "picked_by", "model", "warnings")}
    lines = "\n".join(
        f"- {g['seats']} on {g['flight_no']}: departs {g['departure'].replace('T', ' ')}, arrives {g['arrival'].replace('T', ' ')}"
        for g in result["groups"]
    )
    return (
        f"**Live run, {ts} UTC.** Booking and seats read from Supabase, pick made by `{result['model']}` through OpenRouter, "
        f"result stored in `rebooking_suggestions` as `{stored_id}`.\n\n"
        f"```json\n{json.dumps(shown, indent=2)}\n```\n\n{lines}\n\n"
        f"{len(result['alternatives'])} other candidates were offered to the model (see `alternatives` in the API response)."
    )


def replace_block(text: str, block: str) -> str:
    if text.count(START) != 1 or text.count(END) != 1 or text.index(START) > text.index(END):
        raise ValueError(f"README needs exactly one {START} ... {END} pair")
    head, rest = text.split(START)
    _, tail = rest.split(END)
    return f"{head}{START}\n\n{block}\n\n{END}{tail}"


def run(booking_id: str, service, repo, readme: Path, write: bool = True, now: datetime | None = None) -> int:
    booking = repo.get_booking(booking_id)
    if booking is None:
        print(f"[FAIL] {booking_id} is not in the database. Run: python -m scripts.load_csv_to_supabase")
        return 1
    result = asyncio.run(service.suggest(booking, SuggestRequest(persist=True, use_model=True)))
    stored = repo.latest_suggestion(booking_id)
    stored_ok = bool(stored) and stored.get("id") == result.get("suggestion_id")

    print(f"status      {result['status']}")
    print(f"flights     {result['flights']}  (split: {result['split']})")
    print(f"picked_by   {result['picked_by']}  model: {result['model']}")
    print(f"reason      {result['reason']}")
    print(f"stored      {'yes, id ' + str(result.get('suggestion_id')) if stored_ok else 'NO: could not read the row back'}")
    if result["picked_by"] != "model":
        print(f"[FAIL] the model did not make this pick ({result['picked_by']}). Error: {result.get('model_error')}")
        print("       README.md was not changed. Try: python -m scripts.check_env --ping-model")
        return 1
    if not stored_ok:
        print("[FAIL] the suggestion was not stored in Supabase. README.md was not changed.")
        return 1
    if write:
        ts = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M")
        readme.write_text(replace_block(readme.read_text(encoding="utf-8"), render_block(result, result["suggestion_id"], ts)), encoding="utf-8")
        print(f"[ok] README.md updated: {readme}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("booking_id")
    ap.add_argument("--readme", default=str(REPO_ROOT / "README.md"))
    ap.add_argument("--no-readme", action="store_true")
    args = ap.parse_args(argv)

    s = get_settings()
    missing = [n for n, v in [("SUPABASE_URL", s.supabase_url), ("SUPABASE_SERVICE_ROLE_KEY", s.supabase_service_role_key),
                              ("OPENROUTER_API_KEY", s.openrouter_api_key), ("OPENROUTER_MODEL", s.openrouter_model)] if not v]
    if s.data_backend != "supabase":
        missing.append("DATA_BACKEND=supabase")
    if missing:
        print("[FAIL] this needs the real services. Missing in .env:", ", ".join(missing))
        return 2

    from app.picker import Picker
    from app.repo import SupabaseRepo
    from app.rules import RuleSet
    from app.service import RebookingService

    repo = SupabaseRepo(s.supabase_url, s.supabase_service_role_key)
    service = RebookingService(s, repo, RuleSet.load(s.rules_path), Picker(s))
    return run(args.booking_id, service, repo, Path(args.readme), write=not args.no_readme)


if __name__ == "__main__":
    sys.exit(main())
