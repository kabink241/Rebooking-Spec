"""The real OpenRouter client against a mock HTTP server: request shape, retries, and failure fallback."""
import asyncio
import json

import httpx

from app.candidates import build_candidates
from app.config import Settings
from app.picker import OpenRouterClient, Picker
from tests.helpers import AS_OF, RULES, SETTINGS, booking, flight

S = Settings(_env_file=None, as_of_default=AS_OF, openrouter_api_key="sk-or-test", openrouter_model="vendor/model:free",
             openrouter_referer="https://example.test")


def case():
    b = booking(party_size=2, agent_note="")
    c = build_candidates(b, [flight("F1", "2026-11-18T10:00", 3, 3), flight("F2", "2026-11-18T14:00", 3, 3)], RULES, AS_OF, SETTINGS)
    return b, c


def picker(handler):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return Picker(S, OpenRouterClient(S, http=http))


def ok(text):
    return httpx.Response(200, json={"id": "gen-1", "choices": [{"message": {"role": "assistant", "content": text}}],
                                      "usage": {"prompt_tokens": 200, "completion_tokens": 30, "total_tokens": 230}})


def test_request_goes_to_chat_completions_with_the_key_and_the_free_model():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["auth"], seen["ref"], seen["body"] = str(req.url), req.headers["authorization"], req.headers["http-referer"], json.loads(req.content)
        return ok('{"flights": ["F1"], "reason": "earliest"}')

    b, c = case()
    r = asyncio.run(picker(handler).pick(b, c, True))
    assert seen["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-or-test" and seen["ref"] == "https://example.test"
    assert seen["body"]["model"] == "vendor/model:free" and [m["role"] for m in seen["body"]["messages"]] == ["system", "user"]
    assert r.picked_by == "model" and r.candidate.key == "F1" and r.usage["total_tokens"] == 230 and r.model == "vendor/model:free"


def test_rate_limit_is_retried_then_succeeds(monkeypatch):
    async def no_sleep(_): return None
    monkeypatch.setattr("app.picker.asyncio.sleep", no_sleep)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(429, json={"error": {"message": "rate limited"}}) if len(calls) < 3 else ok('{"flights": ["F2"], "reason": "r"}')

    b, c = case()
    r = asyncio.run(picker(handler).pick(b, c, True))
    assert len(calls) == 3 and r.picked_by == "model" and r.candidate.key == "F2"


def test_persistent_server_errors_fall_back_to_rules(monkeypatch):
    async def no_sleep(_): return None
    monkeypatch.setattr("app.picker.asyncio.sleep", no_sleep)
    b, c = case()
    r = asyncio.run(picker(lambda req: httpx.Response(503, text="down")).pick(b, c, True))
    assert r.picked_by == "rules_fallback" and r.candidate is not None and "503" in r.error


def test_an_error_body_with_status_200_falls_back_to_rules(monkeypatch):
    async def no_sleep(_): return None
    monkeypatch.setattr("app.picker.asyncio.sleep", no_sleep)
    b, c = case()
    r = asyncio.run(picker(lambda req: httpx.Response(200, json={"error": {"code": 402, "message": "no credits"}})).pick(b, c, True))
    assert r.picked_by == "rules_fallback" and "no credits" in r.error


def test_the_api_key_never_appears_in_the_prompt_or_the_stored_error(monkeypatch):
    async def no_sleep(_): return None
    monkeypatch.setattr("app.picker.asyncio.sleep", no_sleep)
    sent = []

    def handler(req):
        sent.append(req.content.decode())
        return httpx.Response(401, json={"error": "bad key"})

    b, c = case()
    r = asyncio.run(picker(handler).pick(b, c, True))
    assert all("sk-or-test" not in body for body in sent) and "sk-or-test" not in (r.error or "")
