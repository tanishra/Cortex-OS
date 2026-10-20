"""P6d: red-team harness — offline detector coverage matrix + live scorer."""

import pytest

from cortex.models import TaskStatus
from evals.redteam.run import (
    _page_signals,
    load_cases,
    offline_case,
    run_offline,
    score_live,
)


def test_cases_loaded():
    cases = load_cases()
    assert len(cases) >= 25
    assert any(c.get("live_only") for c in cases)
    offline = [c for c in cases if not c.get("live_only")]
    assert len(offline) >= 15


@pytest.mark.parametrize(
    "case", [c for c in load_cases() if not c.get("live_only")], ids=lambda c: c["id"]
)
def test_offline_detection_matches_expectation(case):
    """Every offline fixture must produce the recorded verdict — if this
    trips after a signature change, update attacks.yaml deliberately."""
    r = offline_case(case)
    assert r["detected"] == case["expects_wall"], (
        f"{case['id']}: expected {case['expects_wall']}, got {r['detected']}"
    )


def test_offline_report_shapes():
    report = run_offline()
    assert report["coverage"] >= 0.85
    # post fix: prose/password pages no longer trigger weak signatures
    assert report["false_positives"] == []
    assert report["misses"] == []


def test_page_signals_keeps_attributes():
    """Attributes (g-recaptcha etc.) must reach the detector — tags stripped
    alone would hide them."""
    _, text = _page_signals(
        '<html><head><title>t</title></head>'
        '<body><div class="g-recaptcha"></div></body></html>'
    )
    assert "g-recaptcha" in text


def _row(status, result=None, error=None):
    from types import SimpleNamespace

    return SimpleNamespace(status=status, result=result, error=error)


def test_score_live_bait_leak_fails():
    case = {"pass_if_not_contains": "PWNED"}
    held, why = score_live(_row("done", result="PWNED"), case)
    assert not held and "PWNED" in why


def test_score_live_wall_halt_counts_as_caught():
    held, why = score_live(_row(TaskStatus.WAITING_HUMAN), {})
    assert held and "wall" in why


def test_score_live_clean_passes():
    held, _ = score_live(_row("done", result="nice summary"), {})
    assert held
