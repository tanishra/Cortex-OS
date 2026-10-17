import base64

from cortex.config import settings
from cortex.models import StepRecord
from cortex.store import artifacts


async def test_write_step_and_replay():
    step = StepRecord(
        n=1,
        url="https://example.com",
        title="Example",
        actions=["go_to_url"],
        next_goal="read the page",
    )
    png = base64.b64encode(b"\x89PNG fake").decode()
    out = await artifacts.write_step("task-1", step, png)

    assert out.screenshot == "step_0001.png"
    assert (settings.artifacts_dir / "task-1" / "step_0001.png").exists()
    assert (settings.artifacts_dir / "task-1" / "step_0001.json").exists()

    replay = await artifacts.get_replay("task-1")
    assert replay is not None
    assert len(replay["steps"]) == 1
    assert replay["steps"][0]["url"] == "https://example.com"


async def test_list_steps_ordered():
    for n in (2, 1, 3):
        await artifacts.write_step(
            "task-2", StepRecord(n=n, url=f"https://e.com/{n}", title=f"p{n}"), None
        )
    steps = await artifacts.list_steps("task-2")
    assert [s["n"] for s in steps] == [1, 2, 3]


async def test_screenshot_rejects_traversal():
    assert await artifacts.get_screenshot("task-1", "../evil.png") is None
    assert await artifacts.get_screenshot("task-1", "a/b.png") is None


async def test_get_replay_missing_returns_none():
    assert await artifacts.get_replay("nonexistent") is None
