"""Choose one rebooking. A free OpenRouter model picks among validated candidates; rules are the fallback.

The model's answer is accepted only if its flight numbers match one of the offered candidates.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Protocol

import httpx

from .candidates import Candidate, CandidateResult, rank_key
from .config import Settings
from .models import Booking

log = logging.getLogger("rebooking.picker")
SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "pick_system.md").read_text(encoding="utf-8")


@dataclass
class PickResult:
    candidate: Optional[Candidate]
    reason: str
    picked_by: str  # model | rules | rules_fallback | none
    model: Optional[str] = None
    usage: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    latency_ms: Optional[int] = None


class ModelClient(Protocol):
    async def complete(self, system: str, user: str) -> dict:
        """Return {'text': str, 'usage': {...}}."""


class OpenRouterClient:
    def __init__(self, settings: Settings, http: Optional[httpx.AsyncClient] = None):
        self.s = settings
        self.http = http or httpx.AsyncClient(timeout=settings.model_timeout_s)

    async def complete(self, system: str, user: str) -> dict:
        headers = {"Authorization": f"Bearer {self.s.openrouter_api_key}", "Content-Type": "application/json",
                   "X-Title": self.s.openrouter_title}
        if self.s.openrouter_referer:
            headers["HTTP-Referer"] = self.s.openrouter_referer
        body = {
            "model": self.s.openrouter_model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.2,
            "max_tokens": 400,
        }
        url = self.s.openrouter_base_url.rstrip("/") + "/chat/completions"
        last: Optional[Exception] = None
        for attempt in range(3):  # free models rate limit: back off and retry
            try:
                r = await self.http.post(url, headers=headers, json=body)
                if r.status_code in (429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}", request=r.request, response=r)
                r.raise_for_status()
                data = r.json()
                if data.get("error"):
                    raise ValueError(f"OpenRouter error: {data['error']}")
                text = data["choices"][0]["message"]["content"] or ""
                return {"text": text, "usage": data.get("usage") or {}}
            except (httpx.HTTPError, ValueError, KeyError, IndexError) as exc:
                last = exc
                if attempt < 2:
                    await asyncio.sleep(1.0 * (attempt + 1))
        raise last or RuntimeError("OpenRouter call failed")


def parse_model_json(text: str) -> dict:
    """Free models often wrap JSON in prose or code fences: take the first {...} object."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?|```$", "", t, flags=re.MULTILINE).strip()
    start = t.find("{")
    if start < 0:
        raise ValueError("no JSON object in the model reply")
    obj, _ = json.JSONDecoder().raw_decode(t[start:])
    if not isinstance(obj, dict):
        raise ValueError("model reply is not a JSON object")
    return obj


def _compact(c: Candidate) -> dict:
    return {
        "candidate": c.key,
        "type": c.kind,
        "summary": c.summary,
        "gap_between_arrivals_minutes": c.arrival_gap_minutes,
        "final_arrival": c.final_arrival,
        "flags": c.risk_flags,
        "fare_difference_usd": c.fare_difference_total_usd,
        "flights": [{"flight": g["flight_no"], "seats": g["seats"], "departs": g["departure"], "arrives": g["arrival"],
                     "status": g["flight_status"], "weather_risk": g["weather_risk"], "seats_together": g["seats_adjacent"]}
                    for g in c.groups],
    }


def build_user_message(booking: Booking, res: CandidateResult) -> str:
    case = {
        "party_size": booking.party_size,
        "route": f"{booking.origin_airport} to {booking.destination_airport}",
        "covered_by_waiver": booking.waiver_eligible,
        "earliest_acceptable_departure": booking.earliest_acceptable_departure.isoformat(timespec="minutes"),
        "warnings": res.warnings,
        "candidates": [_compact(c) for c in res.candidates],
    }
    # The note goes in its own tags and is the only free text from outside. Passenger names are never sent.
    return f"<booking_note>{booking.agent_note}</booking_note>\n\n<case_json>\n{json.dumps(case, indent=2)}\n</case_json>"


def rules_pick(res: CandidateResult, why: str = "") -> PickResult:
    best = min(res.candidates, key=rank_key)
    reason = best.summary + f"; last arrival {best.final_arrival.replace('T', ' ')}"
    if best.kind == "SPLIT":
        reason += f"; {best.arrival_gap_minutes // 60}h {best.arrival_gap_minutes % 60}m between arrivals"
    reason += "; no fare difference" if best.fare_difference_total_usd == 0 else f"; fare difference ${best.fare_difference_total_usd:.2f}"
    return PickResult(best, reason + (f" ({why})" if why else ""), "rules")


class Picker:
    def __init__(self, settings: Settings, client: Optional[ModelClient] = None):
        self.settings = settings
        self.client = client
        if self.client is None and settings.openrouter_api_key and settings.openrouter_model:
            self.client = OpenRouterClient(settings)

    @property
    def model_available(self) -> bool:
        return self.client is not None

    async def pick(self, booking: Booking, res: CandidateResult, use_model: bool) -> PickResult:
        if not res.candidates:
            return PickResult(None, "", "none")
        if len(res.candidates) == 1:
            return rules_pick(res, "only one valid option, no model call")
        if not (use_model and self.model_available):
            return rules_pick(res, "model not used")

        by_key = {c.key: c for c in res.candidates}
        t0 = time.perf_counter()
        try:
            out = await self.client.complete(SYSTEM_PROMPT, build_user_message(booking, res))
            data = parse_model_json(out["text"])
            flights = data.get("flights")
            if isinstance(flights, str):
                flights = [flights]
            if not isinstance(flights, list) or not all(isinstance(x, str) for x in flights):
                raise ValueError(f"'flights' must be a list of flight numbers, got {flights!r}")
            flights = [x.strip().upper() for x in flights]
            chosen = by_key.get("+".join(flights))
            if chosen is None and len(flights) == 2:  # accept the two flights in either order
                chosen = by_key.get("+".join(reversed(flights)))
            if chosen is None:
                raise ValueError(f"model chose flights outside the offered set: {flights}")
            reason = " ".join(str(data.get("reason", "")).split())[:400] or rules_pick(res).reason
            return PickResult(chosen, reason, "model", model=self.settings.openrouter_model,
                              usage=out.get("usage", {}), latency_ms=int((time.perf_counter() - t0) * 1000))
        except Exception as exc:  # any failure: fall back to rules, keep the reason for the audit log
            log.warning("model pick failed for %s: %s", booking.booking_id, exc)
            r = rules_pick(res, "model unavailable, rules used")
            r.picked_by = "rules_fallback"
            r.error = f"{type(exc).__name__}: {exc}"[:300]
            r.model = self.settings.openrouter_model
            r.latency_ms = int((time.perf_counter() - t0) * 1000)
            return r
