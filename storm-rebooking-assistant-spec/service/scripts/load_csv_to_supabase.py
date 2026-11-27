"""Load the two CSVs into Supabase (upsert, so it is safe to re-run with a fresh seat snapshot).

    python -m scripts.load_csv_to_supabase --dry-run          # parse and report, touch nothing
    python -m scripts.load_csv_to_supabase                    # needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY

Rows that fail validation go to the ingest_rejects table and are reported, never guessed at.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from app.config import get_settings
from app.ingest import load_bookings_csv, load_flights_csv


def _row(model) -> dict:
    d = model.model_dump(mode="json")
    return d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bookings", default=None)
    ap.add_argument("--flights", default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--batch", type=int, default=500)
    args = ap.parse_args(argv)

    s = get_settings()
    bookings, brej = load_bookings_csv(args.bookings or s.bookings_csv)
    flights, frej = load_flights_csv(args.flights or s.flights_csv)
    rejects = brej + frej
    print(f"bookings parsed: {len(bookings)}   flights parsed: {len(flights)}   rejected rows: {len(rejects)}")
    for r in rejects:
        print(f"  reject {r['source']} line {r['line']}: {r['reason']}")
    if args.dry_run:
        return 0

    if not s.supabase_url or not s.supabase_service_role_key:
        print("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set (see .env.example)", file=sys.stderr)
        return 2
    from supabase import create_client

    sb = create_client(s.supabase_url, s.supabase_service_role_key)
    now = datetime.now(timezone.utc).isoformat()

    def upsert(table: str, rows: list[dict], key: str) -> None:
        for i in range(0, len(rows), args.batch):
            sb.table(table).upsert(rows[i : i + args.batch], on_conflict=key).execute()
        print(f"  {table}: {len(rows)} rows upserted")

    upsert("cancelled_bookings", [_row(b) for b in bookings], "booking_id")
    upsert("open_seats", [{**_row(f), "snapshot_at": now} for f in flights], "flight_no")
    # Replace earlier rejects from the same sources so re-running does not pile up duplicates.
    sb.table("ingest_rejects").delete().in_("source", ["cancelled_bookings", "open_seats"]).execute()
    if rejects:
        sb.table("ingest_rejects").insert(
            [{"source": r["source"], "line_no": r["line"], "row_data": json.loads(json.dumps(r["row"])), "reason": r["reason"]} for r in rejects]
        ).execute()
        print(f"  ingest_rejects: {len(rejects)} rows stored")
    # Read back the counts so a silent failure cannot pass for success.
    nb = sb.table("cancelled_bookings").select("booking_id", count="exact").limit(1).execute().count
    nf = sb.table("open_seats").select("flight_no", count="exact").limit(1).execute().count
    print(f"verified in Supabase: cancelled_bookings={nb} (expected >= {len(bookings)}), open_seats={nf} (expected >= {len(flights)})")
    return 0 if nb >= len(bookings) and nf >= len(flights) else 1


if __name__ == "__main__":
    raise SystemExit(main())
