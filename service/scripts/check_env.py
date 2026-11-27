"""Check keys and tables before you start the service. Prints whether each key is set, never its value.

    python -m scripts.check_env
    python -m scripts.check_env --list-free-models     # asks OpenRouter which ':free' models exist right now
"""
from __future__ import annotations

import argparse
import os
import sys

from app.config import get_settings


def list_free_models(s) -> int:
    import httpx

    r = httpx.get(s.openrouter_base_url.rstrip("/") + "/models", timeout=30)
    r.raise_for_status()
    ids = sorted(m["id"] for m in r.json().get("data", []) if m.get("id", "").endswith(":free"))
    print(f"{len(ids)} free models listed by OpenRouter right now:")
    for i in ids:
        print("  ", i)
    print("Set OPENROUTER_MODEL in .env to one of these (free model ids change, so re-check if calls start failing).")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list-free-models", action="store_true")
    args = ap.parse_args(argv)
    try:
        s = get_settings()
    except Exception as exc:  # e.g. a model id that does not end in :free
        print(f"[BAD] settings: {exc}")
        return 1
    if args.list_free_models:
        return list_free_models(s)

    ok = True

    def line(name: str, good: bool, detail: str = "") -> None:
        nonlocal ok
        ok &= good
        print(f"[{'ok' if good else 'MISSING'}] {name} {detail}")

    line("rules file", os.path.exists(s.rules_path), s.rules_path)
    line("OPENROUTER_API_KEY", bool(s.openrouter_api_key))
    line("OPENROUTER_MODEL", bool(s.openrouter_model), f"({s.openrouter_model or 'unset'}; must end in :free)")
    if s.data_backend == "supabase":
        line("SUPABASE_URL", s.supabase_url.startswith("https://"))
        line("SUPABASE_SERVICE_ROLE_KEY", bool(s.supabase_service_role_key))
        if s.supabase_url and s.supabase_service_role_key:
            from supabase import create_client

            sb = create_client(s.supabase_url, s.supabase_service_role_key)
            for t in ("cancelled_bookings", "open_seats", "rebooking_suggestions", "ingest_rejects"):
                try:
                    n = sb.table(t).select("*", count="exact").limit(1).execute().count
                    line(f"table {t}", True, f"({n} rows)")
                except Exception as exc:  # table missing, or the key is wrong
                    line(f"table {t}", False, str(exc)[:120])
    else:
        line("bookings csv", os.path.exists(s.bookings_csv), s.bookings_csv)
        line("flights csv", os.path.exists(s.flights_csv), s.flights_csv)
    line("SERVICE_API_KEY (auth on)", bool(s.service_api_key), "- leave empty only for local use")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
