import base64

from cortex.models import StepRecord
from cortex.store import artifacts


def test_write_step_and_replay(tmp_path):
    step = StepRecord(
        n=1,
        url="https://example.com",
        title="Example",
        actions=["go_to_url"],
        next_goal="read the page",
    )
    png = base64.b64encode(b"\x89PNG fake").decode()
    out = artifacts.write_step("task-1", step, png)

    assert out.screenshot == "step_0001.png"
    assert (artifacts.task_dir("task-1") / "step_0001.png").exists()
    assert (artifacts.task_dir("task-1") / "step_0001.json").exists()

    replay = artifacts.get_replay("task-1")
    assert replay is not None
    assert len(replay["steps"]) == 1
    assert replay["steps"][0]["url"] == "https://example.com"


def test_list_steps_ordered():
    for n in (2, 1, 3):
        artifacts.write_step(
            "task-2", StepRecord(n=n, url=f"https://e.com/{n}", title=f"p{n}"), None
        )
    steps = artifacts.list_steps("task-2")
    assert [s["n"] for s in steps] == [1, 2, 3]


def test_screenshot_path_rejects_traversal():
    assert artifacts.get_screenshot_path("task-1", "../evil.png") is None
    assert artifacts.get_screenshot_path("task-1", "a/b.png") is None


def test_get_replay_missing_returns_none():
    assert artifacts.get_replay("nonexistent") is None
