"""P5b — eval harness: fixtures, scoring, report (no live LLM calls)."""

import urllib.request
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cortex.store import db
from evals import run as evalrun


def test_fixture_pages_serve():
    srv = evalrun._FixtureServer()
    srv.start()
    try:
        for page in ["index.html", "list.html", "injection_hidden.html"]:
            body = urllib.request.urlopen(
                f"http://127.0.0.1:{srv.port}/{page}"
            ).read().decode()
            assert "<h1>" in body
        bait = urllib.request.urlopen(
            f"http://127.0.0.1:{srv.port}/injection_hidden.html"
        ).read().decode()
        assert "PWNED" in bait
        bait2 = urllib.request.urlopen(
            f"http://127.0.0.1:{srv.port}/injection_form.html"
        ).read().decode()
        assert "admin123" in bait2
    finally:
        srv.stop()


def test_tasks_yaml_parses_and_covers_injection():
    cases = evalrun.load_cases()
    assert len(cases) >= 8
    tags = {t for c in cases for t in c["tags"]}
    assert "injection" in tags
    for c in cases:
        assert c["id"] and c["task"] and c["page"]


def _row(status="done", result="ok result", error=None):
    return SimpleNamespace(
        status=status, result=result, error=error, steps_taken=1
    )


def test_score_pass():
    case = {"expect_status": "done", "expect_contains": ["result"],
            "expect_not_contains": ["PWNED"]}
    ok, _ = evalrun.score_case(_row(), case)
    assert ok


def test_score_missing_text():
    case = {"expect_status": "done", "expect_contains": ["NORTHSTAR"],
            "expect_not_contains": []}
    ok, why = evalrun.score_case(_row(), case)
    assert not ok and "missing" in why


def test_score_leaked_bait():
    case = {"expect_status": "done", "expect_contains": [],
            "expect_not_contains": ["PWNED"]}
    ok, why = evalrun.score_case(_row(result="I say PWNED now"), case)
    assert not ok and "leaked" in why


def test_score_wrong_status():
    case = {"expect_status": "done", "expect_contains": [],
            "expect_not_contains": []}
    ok, why = evalrun.score_case(_row(status="failed"), case)
    assert not ok and "status" in why


def test_run_suite_report(monkeypatch):
    db.init_db()
    monkeypatch.setattr(
        "cortex.engine.runner.run_task", AsyncMock(return_value=None)
    )
    case = {
        "id": "c1", "task": "t", "page": "index.html",
        "expect_status": "done", "expect_contains": [],
        "expect_not_contains": [], "tags": [],
    }
    monkeypatch.setattr(evalrun, "load_cases", lambda *a: [case])

    # _run_case creates a real task; runner mocked → status stays queued →
    # force done to exercise scoring.
    async def fake_case(case, port):
        return {"id": "c1", "page": "x", "status": "done", "steps": 1,
                "passed": True, "why": "ok", "error": ""}

    monkeypatch.setattr(evalrun, "_run_case", fake_case)
    report = __import__("asyncio").run(evalrun.run_suite())
    assert report["total"] == 1 and report["passed"] == 1
    assert report["pass_rate"] == 1.0


def test_main_skips_without_key(monkeypatch, capsys):
    monkeypatch.setattr("evals.run.settings.openai_api_key", "")
    monkeypatch.setattr("sys.argv", ["run.py"])
    assert evalrun.main() == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err
