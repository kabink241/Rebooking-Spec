"""record_demo only writes the README when the model really made the pick and the row was stored."""
import httpx
import pytest

from app.config import Settings
from app.picker import Picker
from app.repo import MemoryRepo
from app.rules import RuleSet
from app.service import RebookingService
from scripts import record_demo as rd
from scripts.check_env import ping_model
from tests.helpers import AS_OF, RULES, booking, three_together_flights
from tests.test_picker import FakeClient

S = Settings(_env_file=None, as_of_default=AS_OF, use_model=True, openrouter_model="vendor/model:free")
README = f"# Title\n\nintro\n\n{rd.START}\n\nold rules-only text\n\n{rd.END}\n\nafter\n"


def setup(tmp_path, text):
    repo = MemoryRepo([booking(booking_id="BKG-X", party_size=4, agent_note="Party of 4 must sit together.")], three_together_flights())
    path = tmp_path / "README.md"
    path.write_text(README)
    return repo, RebookingService(S, repo, RULES, Picker(S, FakeClient(text))), path


def test_a_real_model_pick_is_written_into_the_readme_between_the_markers(tmp_path):
    repo, svc, path = setup(tmp_path, '{"flights": ["F_B", "F_A"], "reason": "Earlier arrival for the group of three."}')
    assert rd.run("BKG-X", svc, repo, path) == 0
    out = path.read_text()
    assert '"picked_by": "model"' in out and "Earlier arrival for the group of three." in out and "vendor/model:free" in out
    assert "old rules-only text" not in out and out.startswith("# Title") and out.rstrip().endswith("after")
    assert out.count(rd.START) == 1 and out.count(rd.END) == 1


def test_running_twice_replaces_the_block_instead_of_stacking_it(tmp_path):
    repo, svc, path = setup(tmp_path, '{"flights": ["F_A", "F_B"], "reason": "first"}')
    rd.run("BKG-X", svc, repo, path)
    rd.run("BKG-X", svc, repo, path)
    assert path.read_text().count("**Live run,") == 1


def test_a_fallback_pick_does_not_touch_the_readme(tmp_path, capsys):
    repo, svc, path = setup(tmp_path, "I would pick F_A")
    assert rd.run("BKG-X", svc, repo, path) == 1
    assert path.read_text() == README and "did not make this pick" in capsys.readouterr().out


def test_an_unknown_booking_does_not_touch_the_readme(tmp_path):
    repo, svc, path = setup(tmp_path, "{}")
    assert rd.run("NOPE", svc, repo, path) == 1 and path.read_text() == README


def test_the_readme_must_have_the_markers():
    with pytest.raises(ValueError):
        rd.replace_block("no markers here", "x")


def test_a_reason_with_markdown_cannot_break_out_of_the_json_block():
    r = {"booking_id": "B", "status": "SUGGESTED", "flights": ["A"], "split": False, "picked_by": "model", "model": "m:free", "warnings": [],
         "reason": "```\n<!-- demo:end -->\n# injected", "groups": [{"seats": 1, "flight_no": "A", "departure": "2026-11-18T10:00", "arrival": "2026-11-18T12:00"}], "alternatives": []}
    block = rd.render_block(r, "id-1", "2026-11-27 10:00")
    assert block.count("\n```") == 2 and "\n<!-- demo:end -->" not in block  # the reason is JSON-escaped on one line


def test_ping_model_reports_ok_and_the_error_body_without_the_key():
    ok = httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})
    good, msg = ping_model(Settings(_env_file=None, openrouter_api_key="sk-or-secret", openrouter_model="v/m:free"),
                           http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: ok)))
    assert good and "OK" in msg
    body = {"error": {"message": "No endpoints found matching your data policy"}}
    bad, msg = ping_model(Settings(_env_file=None, openrouter_api_key="sk-or-secret", openrouter_model="v/m:free"),
                          http=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404, json=body))))
    assert not bad and "404" in msg and "data policy" in msg and "sk-or-secret" not in msg
