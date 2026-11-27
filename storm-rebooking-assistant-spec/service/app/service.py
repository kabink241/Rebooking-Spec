"""Orchestration: candidates, then the model's pick, then persistence."""
from __future__ import annotations

import asyncio
import time
from collections import Counter
from typing import Optional

import anyio

from .candidates import Candidate, CandidateResult, build_candidates
from .config import Settings, resolve_as_of
from .models import BatchRequest, Booking, Flight, SuggestRequest
from .picker import Picker, PickResult
from .repo import Repo
from .rules import RuleSet


def _alt(c: Candidate) -> dict:
    return {"flights": c.flights(), "summary": c.summary, "final_arrival": c.final_arrival}


class RebookingService:
    def __init__(self, settings: Settings, repo: Repo, rules: RuleSet, picker: Picker):
        self.settings, self.repo, self.rules, self.picker = settings, repo, rules, picker

    async def suggest(self, booking: Booking, req: SuggestRequest, flights: Optional[list[Flight]] = None, with_pick: bool = True) -> dict:
        t0 = time.perf_counter()
        as_of = resolve_as_of(req.as_of, self.settings)
        if flights is None:
            flights = await anyio.to_thread.run_sync(self.repo.flights_for_route, booking.origin_airport, booking.destination_airport)
        res = build_candidates(booking, flights, self.rules, as_of, self.settings)
        use_model = self.settings.use_model if req.use_model is None else req.use_model
        pick = await self.picker.pick(booking, res, use_model) if with_pick else PickResult(None, "", "none")
        out = self._response(booking, res, pick, as_of, with_pick)
        out["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
        if with_pick and req.persist:
            out["suggestion_id"] = await anyio.to_thread.run_sync(self.repo.save_suggestion, self._record(booking, out, pick, as_of))
        return out

    def _response(self, booking: Booking, res: CandidateResult, pick: PickResult, as_of, with_pick: bool) -> dict:
        c = pick.candidate
        warnings = list(res.warnings)
        if c is not None and c.kind == "SPLIT":
            warnings += res.split_warnings
        elif c is not None and not c.seats_all_adjacent and booking.party_size > 1:
            g = c.groups[0]
            warnings.append(f"Seats on {g['flight_no']} are not all together: the largest block is {g['open_seats_adjacent_max']} "
                            f"of {booking.party_size}. Confirm the customer accepts that.")
        out = {
            "booking_id": booking.booking_id,
            "as_of": as_of.isoformat(),
            "rule_set": {"name": self.rules.name, "version": self.rules.version},
            "status": res.status,
            "status_reason": res.status_reason,
            "next_step": res.next_step,
            "flights": c.flights() if c else [],
            "split": bool(c and c.kind == "SPLIT"),
            "reason": pick.reason,
            "picked_by": pick.picked_by,
            "model": pick.model,
            "model_error": pick.error,
            "groups": c.groups if c else [],
            "warnings": warnings,
            "alternatives": [_alt(x) for x in res.candidates if x is not c],
            "excluded_flights": res.excluded,
        }
        if not with_pick:  # /candidates: every candidate in full, nothing chosen
            out["candidates"] = [{"flights": x.flights(), "kind": x.kind, "summary": x.summary, "groups": x.groups} for x in res.candidates]
        return out

    def _record(self, booking: Booking, out: dict, pick: PickResult, as_of) -> dict:
        return {
            "booking_id": booking.booking_id,
            "as_of": as_of.isoformat(),
            "rule_set": self.rules.name,
            "rule_set_version": self.rules.version,
            "status": out["status"],
            "status_reason": out["status_reason"],
            "pick": {"flights": out["flights"], "split": out["split"], "reason": out["reason"], "groups": out["groups"]} if out["flights"] else None,
            "options": out["alternatives"],
            "pending_options": [],
            "excluded_flights": out["excluded_flights"],
            "warnings": out["warnings"],
            "picked_by": pick.picked_by,
            "model": pick.model,
            "model_reason": pick.reason,
            "model_error": pick.error,
            "model_usage": pick.usage or None,
            "agent_inputs": {},
        }

    async def batch(self, req: BatchRequest) -> dict:
        t0 = time.perf_counter()
        if req.booking_ids:
            found = [await anyio.to_thread.run_sync(self.repo.get_booking, i) for i in req.booking_ids]
            bookings = [b for b in found if b]
            missing = sorted(set(req.booking_ids) - {b.booking_id for b in bookings})
        else:
            total = await anyio.to_thread.run_sync(self.repo.count_bookings)
            bookings, missing = [], []
            for off in range(0, total, 500):
                bookings += await anyio.to_thread.run_sync(self.repo.list_bookings, 500, off)

        cache: dict[tuple[str, str], list[Flight]] = {}
        for route in {(b.origin_airport, b.destination_airport) for b in bookings}:
            cache[route] = await anyio.to_thread.run_sync(self.repo.flights_for_route, *route)

        sem = asyncio.Semaphore(self.settings.batch_concurrency)
        sub = SuggestRequest(as_of=req.as_of, use_model=req.use_model, persist=req.persist)

        async def one(b: Booking) -> dict:
            async with sem:
                return await self.suggest(b, sub, cache[(b.origin_airport, b.destination_airport)])

        results = await asyncio.gather(*(one(b) for b in bookings))
        summary = {
            "bookings": len(results),
            "missing_booking_ids": missing,
            "by_status": dict(Counter(r["status"] for r in results)),
            "picked_by": dict(Counter(r["picked_by"] for r in results if r["flights"])),
            "singles": sum(1 for r in results if r["flights"] and not r["split"]),
            "splits": sum(1 for r in results if r["split"]),
            "model_errors": sum(1 for r in results if r["model_error"]),
            "elapsed_ms": int((time.perf_counter() - t0) * 1000),
        }
        out = {"summary": summary}
        if req.include_results:
            out["results"] = results
        return out
