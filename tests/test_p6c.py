"""P6c: failure classifier + stay-on-site prompt — dry tests."""

import json
from types import SimpleNamespace

from evals.bench import classify_failure, summarize


def _ev(kind, url=None, payload=None):
    return SimpleNamespace(
        kind=kind, url=url, payload_json=payload, tokens_in=None,
        tokens_out=None, cost_usd=None, duration_ms=None,
        actions_json="[]",
    )


def _row(status="failed", error="bench_timeout"):
    return SimpleNamespace(status=status, error=error)


def test_success():
    assert classify_failure(_row(status="done", error=None), []) == "success"


def test_bot_blocked_wall_beats_flee():
    """Wall event wins over search-fleeing — block is the cause."""
    events = [
        _ev("step", url="https://www.adoptapet.com/"),
        _ev("step", url="https://duckduckgo.com/?q=x"),
        _ev("status", payload=json.dumps({"to": "waiting_human"})),
    ]
    assert classify_failure(_row(error="bench_timeout"), events) == "bot_blocked"


def test_wandered_offsite():
    events = [
        _ev("step", url="https://new.mta.info/"),
        _ev("step", url="https://www.bing.com/search?q=site%3Amta.info"),
    ]
    assert classify_failure(_row(), events) == "wandered_offsite"


def test_timeout_on_site():
    events = [_ev("step", url="https://www.apple.com/macbook-air/specs/")]
    assert classify_failure(_row(), events) == "timeout_on_site"


def test_failed_other():
    assert classify_failure(_row(error="crash: nope"), []) == "failed_other"


def test_summarize_has_categories():
    recs = [
        {"status": "done", "verdict": "pass", "steps": 1, "duration_s": 1,
         "failure_category": "success"},
        {"status": "failed", "verdict": "fail", "steps": 2, "duration_s": 2,
         "failure_category": "bot_blocked"},
        {"status": "failed", "verdict": "fail", "steps": 3, "duration_s": 3,
         "failure_category": "bot_blocked"},
    ]
    s = summarize(recs)
    assert s["failure_categories"] == {"success": 1, "bot_blocked": 2}


def test_prompt_has_stay_on_site_rule():
    from cortex.engine.prompts import SAFETY_EXTENSION

    assert "search engines or alternative providers" in SAFETY_EXTENSION
    assert "do not wander to other sites" in SAFETY_EXTENSION
