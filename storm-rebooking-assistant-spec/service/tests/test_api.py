from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.picker import Picker
from app.repo import MemoryRepo
from app.service import RebookingService
from tests.helpers import AS_OF, RULES, SETTINGS, booking, flight, family_flights, three_together_flights
from tests.test_picker import FakeClient

S_MODEL = Settings(_env_file=None, as_of_default=AS_OF, use_model=True, openrouter_model="vendor/model:free")


def client(settings=SETTINGS, fake=None, bookings=None):
    bookings = bookings or [
        booking(booking_id="B1", party_size=4, agent_note="Party of 4 must sit together."),
        booking(booking_id="B2", party_size=1, agent_note=""),
        booking(booking_id="B3", party_size=2, destination_airport="LAS", agent_note=""),
    ]
    flights = three_together_flights() + [flight("G1", "2026-11-18T10:00", 3, 3), flight("G2", "2026-11-18T12:00", 3, 3)]
    svc = RebookingService(settings, MemoryRepo(bookings, flights), RULES, Picker(settings, fake))
    return TestClient(create_app(service=svc))


def test_health_reports_backend_rules_date_and_that_the_model_is_off():
    with client() as c:
        h = c.get("/health").json()
    assert h["status"] == "ok" and h["rule_set"]["requests_accepted_through"] == "2026-11-23" and h["as_of_default"] == "2026-11-17"
    assert h["model_enabled"] is False


def test_unknown_booking_is_404():
    with client() as c:
        assert c.post("/bookings/NOPE/suggest", json={}).status_code == 404


def test_candidates_endpoint_is_rules_only_and_stores_nothing():
    with client() as c:
        r = c.get("/bookings/B2/candidates").json()
        assert r["flights"] == [] and r["candidates"] and r["picked_by"] == "none"
        assert c.get("/bookings/B2/suggestions/latest").status_code == 404


def test_suggest_returns_flight_numbers_and_a_reason_and_stores_it():
    with client() as c:
        r = c.post("/bookings/B2/suggest", json={}).json()
        assert r["status"] == "SUGGESTED" and r["flights"] and r["split"] is False and r["reason"] and r["suggestion_id"]
        assert c.get("/bookings/B2/suggestions/latest").json()["booking_id"] == "B2"


def test_party_of_four_without_four_adjacent_returns_both_flight_numbers():
    with client() as c:
        r = c.post("/bookings/B1/suggest", json={"persist": False}).json()
    assert r["split"] is True and len(r["flights"]) == 2 and [g["seats"] for g in r["groups"]] == [3, 1]
    assert r["reason"] and any("must agree" in w for w in r["warnings"])


def test_the_model_pick_reaches_the_response():
    fake = FakeClient('{"flights": ["G2"], "reason": "afternoon suits them"}')
    with client(S_MODEL, fake) as c:
        r = c.post("/bookings/B2/suggest", json={"persist": False}).json()
    assert r["picked_by"] == "model" and r["flights"] == ["G2"] and r["reason"] == "afternoon suits them" and r["model"] == "vendor/model:free"


def test_a_bad_model_answer_still_returns_a_valid_flight():
    with client(S_MODEL, FakeClient("no idea")) as c:
        r = c.post("/bookings/B2/suggest", json={"persist": False}).json()
    assert r["picked_by"] == "rules_fallback" and r["flights"] and r["model_error"]


def test_batch_covers_every_booking_and_summarises():
    with client() as c:
        r = c.post("/suggest/batch", json={"persist": False}).json()
    assert r["summary"]["bookings"] == 3 and len(r["results"]) == 3
    assert sum(r["summary"]["by_status"].values()) == 3 and r["summary"]["splits"] == 1


def test_batch_reports_unknown_ids():
    with client() as c:
        r = c.post("/suggest/batch", json={"booking_ids": ["B1", "NOPE"], "persist": False}).json()
    assert r["summary"]["bookings"] == 1 and r["summary"]["missing_booking_ids"] == ["NOPE"]


def test_after_the_waiver_ends_everything_routes_to_revenue_management():
    with client() as c:
        r = c.post("/suggest/batch", json={"as_of": "2026-11-26", "persist": False}).json()
    assert r["summary"]["by_status"] == {"ROUTE_TO_REVENUE_MANAGEMENT": 3}


def test_api_key_is_enforced_when_set():
    s = Settings(_env_file=None, as_of_default=AS_OF, use_model=False, service_api_key="secret")
    with client(s) as c:
        assert c.get("/bookings").status_code == 401
        assert c.get("/bookings", headers={"X-API-Key": "wrong"}).status_code == 401
        assert c.get("/bookings", headers={"X-API-Key": "secret"}).status_code == 200
        assert c.get("/health").status_code == 200


def test_split_warnings_appear_only_when_the_pick_is_a_split():
    with client() as c:
        split = c.post("/bookings/B1/suggest", json={"persist": False}).json()
        single = c.post("/bookings/B2/suggest", json={"persist": False}).json()
    assert split["split"] and any("must agree" in w for w in split["warnings"])
    assert not single["split"] and not any("must agree" in w for w in single["warnings"])


def test_scattered_seats_are_called_out_in_the_warnings():
    bookings = [booking(booking_id="B9", party_size=3, agent_note="")]
    svc = RebookingService(SETTINGS, MemoryRepo(bookings, [flight("S1", "2026-11-18T10:00", 4, 1)]), RULES, Picker(SETTINGS))
    with TestClient(create_app(service=svc)) as c:
        r = c.post("/bookings/B9/suggest", json={"persist": False}).json()
    assert r["flights"] == ["S1"] and any("not all together" in w for w in r["warnings"])


def test_party_of_four_with_no_split_possible_returns_no_flight_and_a_reason():
    bookings = [booking(booking_id="B9", party_size=4)]
    svc = RebookingService(SETTINGS, MemoryRepo(bookings, [flight("ONLY", "2026-11-18T10:00", 4, 2)]), RULES, Picker(SETTINGS))
    with TestClient(create_app(service=svc)) as c:
        r = c.post("/bookings/B9/suggest", json={"persist": False}).json()
    assert r["status"] == "NO_OPTION" and r["flights"] == [] and "no split is possible" in r["status_reason"]
