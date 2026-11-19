"""#446 slice A2: WorkflowPlayer cooperative pause via ControlGate.

The player checks the gate at step boundaries only: when the gate
blocks (pause, human mode, open intervention) it persists the
checkpoint, fires ``on_gate_blocked`` once per block episode, and
waits. On resume it continues at the blocked step — completed steps
are never replayed.
"""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from production.control_gate import ControlGate, ControlModeError
from production.hermes_dashboard import BrowserRuntimeManager
from workflows.player import WorkflowPlayer
from workflows.schema import Workflow, WorkflowStep

try:
    from tests.test_hermes_dashboard import _FakeBrowser
except ImportError:  # pragma: no cover - direct-file test runs
    from test_hermes_dashboard import _FakeBrowser


class CountingBrowser:
    """Fake browser in the style of tests/test_player.py's MockBrowser,
    recording every executed step and offering a sync per-step hook."""

    def __init__(self):
        self.page = AsyncMock()
        self.page.evaluate = AsyncMock(return_value="")
        self.page.screenshot = AsyncMock(return_value={"path": "/tmp/screen.png"})
        self.page.url = "https://example.com"
        self.executed = []  # [(kind, arg)] in execution order
        self.on_step = None  # callable(kind, arg, total_executed)

    def _record(self, kind, arg):
        self.executed.append((kind, arg))
        if self.on_step is not None:
            self.on_step(kind, arg, len(self.executed))

    async def safe_goto(self, url, platform="unknown"):
        self._record("navigate", url)
        return True

    async def safe_click(self, selector):
        self._record("click", selector)
        return True

    async def safe_type(self, selector, value):
        self._record("fill", (selector, value))
        return True

    async def screenshot_on_error(self, name):
        return "screenshots/error.png"


def _click_workflow(count, name="gate-test"):
    # wait_after=0: the normalized click default is 500 ms per step,
    # which would make the timing assertions below slow and flaky.
    return Workflow(
        name=name,
        steps=[
            WorkflowStep(type="click", params={"selector": f"#s{i}", "wait_after": 0})
            for i in range(count)
        ],
    )


def _clicked(browser):
    return [arg for kind, arg in browser.executed if kind == "click"]


async def _wait_until_blocked(task, browser, expected_steps):
    """Give the player a moment to reach the gate and confirm it stopped."""
    await asyncio.sleep(0.25)
    assert not task.done()
    assert len(browser.executed) == expected_steps


@pytest.mark.asyncio
class TestPauseResume:
    async def test_pause_blocks_at_boundary_and_resume_is_checkpoint_exact(
        self, tmp_path
    ):
        browser = CountingBrowser()
        gate = ControlGate()
        blocked = []
        player = WorkflowPlayer(
            browser, control_gate=gate, on_gate_blocked=blocked.append
        )

        # Arm a checkpoint path so the block-time persist is observable.
        checkpoint_path = tmp_path / "checkpoint.json"
        player.save_checkpoint(str(checkpoint_path))
        assert player.load_checkpoint(str(checkpoint_path))

        def pause_after_two(kind, arg, total):
            if total == 2:
                gate.pause()

        browser.on_step = pause_after_two
        task = asyncio.create_task(player.execute(_click_workflow(5)))
        await _wait_until_blocked(task, browser, 2)

        assert _clicked(browser) == ["#s0", "#s1"]
        assert blocked == [gate]  # exactly once for this block episode
        on_disk = json.loads(checkpoint_path.read_text())
        assert on_disk["checkpoint"]["completed_steps"] == [0, 1]

        gate.resume()
        result = await asyncio.wait_for(task, timeout=5)
        assert result.success
        assert result.steps_executed == 5
        # Checkpoint-exact resume: every step ran exactly once, in order.
        assert _clicked(browser) == ["#s0", "#s1", "#s2", "#s3", "#s4"]
        assert player.checkpoint["completed_steps"] == [0, 1, 2, 3, 4]

    async def test_second_block_episode_notifies_again(self):
        browser = CountingBrowser()
        gate = ControlGate()
        blocked = []
        player = WorkflowPlayer(
            browser, control_gate=gate, on_gate_blocked=blocked.append
        )

        def pause_at_two_and_four(kind, arg, total):
            if total in (2, 4):
                gate.pause()

        browser.on_step = pause_at_two_and_four
        task = asyncio.create_task(player.execute(_click_workflow(5)))
        await _wait_until_blocked(task, browser, 2)
        gate.resume()
        await _wait_until_blocked(task, browser, 4)
        assert blocked == [gate, gate]
        gate.resume()
        result = await asyncio.wait_for(task, timeout=5)
        assert result.success
        assert _clicked(browser) == ["#s0", "#s1", "#s2", "#s3", "#s4"]


@pytest.mark.asyncio
class TestHumanModeMidRun:
    async def test_human_mode_blocks_until_shared_returns(self):
        browser = CountingBrowser()
        gate = ControlGate()
        player = WorkflowPlayer(browser, control_gate=gate)

        def flip_to_human(kind, arg, total):
            if total == 2:
                gate.set_mode("human")

        browser.on_step = flip_to_human
        task = asyncio.create_task(player.execute(_click_workflow(4)))
        await _wait_until_blocked(task, browser, 2)
        assert _clicked(browser) == ["#s0", "#s1"]

        gate.set_mode("shared")
        result = await asyncio.wait_for(task, timeout=5)
        assert result.success
        assert _clicked(browser) == ["#s0", "#s1", "#s2", "#s3"]


@pytest.mark.asyncio
class TestInterventionFlow:
    async def test_request_then_resolve_completes_without_replay(self):
        browser = CountingBrowser()
        gate = ControlGate()
        events = []

        def request_captcha(kind, arg, total):
            events.append(("step", arg))
            if total == 2:
                gate.request_intervention(
                    "captcha", "Solve challenge", checkpoint_id="ckpt-1"
                )

        def on_blocked(blocked_gate):
            events.append(("blocked", blocked_gate.intervention["reason"]))

        browser.on_step = request_captcha
        player = WorkflowPlayer(browser, control_gate=gate, on_gate_blocked=on_blocked)
        task = asyncio.create_task(player.execute(_click_workflow(5)))
        await _wait_until_blocked(task, browser, 2)
        assert gate.intervention["checkpoint_id"] == "ckpt-1"

        gate.resolve_intervention()
        events.append(("resolved", None))
        result = await asyncio.wait_for(task, timeout=5)

        assert result.success
        assert result.steps_executed == 5
        assert _clicked(browser) == ["#s0", "#s1", "#s2", "#s3", "#s4"]
        assert events == [
            ("step", "#s0"),
            ("step", "#s1"),
            ("blocked", "captcha"),
            ("resolved", None),
            ("step", "#s2"),
            ("step", "#s3"),
            ("step", "#s4"),
        ]


@pytest.mark.asyncio
class TestNoGateRegression:
    async def test_player_without_gate_runs_as_before(self):
        browser = CountingBrowser()
        player = WorkflowPlayer(browser)
        assert player.control_gate is None
        result = await player.execute(_click_workflow(3))
        assert result.success
        assert result.steps_executed == 3
        assert _clicked(browser) == ["#s0", "#s1", "#s2"]


class _PausingBrowser(_FakeBrowser):
    """Dashboard fake that pauses the manager's gate mid-replay."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.clicks = []
        self.gate = None
        self.pause_after = None

    async def safe_click(self, selector, **kwargs):
        self.clicks.append(selector)
        await super().safe_click(selector, **kwargs)
        if (
            self.gate is not None
            and self.pause_after is not None
            and len(self.clicks) == self.pause_after
        ):
            self.gate.pause()


@pytest.mark.asyncio
class TestDashboardWiring:
    async def _recorded_manager(self, tmp_path, browser_cls=_FakeBrowser):
        manager = BrowserRuntimeManager(
            agent_browser_cls=browser_cls, storage_root=tmp_path
        )
        await manager.start(profile="demo", backend="playwright-mcp")
        manager.start_recording("gate-replay")
        await manager.navigate("https://example.com")
        for selector in ("#a", "#b", "#c", "#d"):
            await manager.click(selector)
        saved = manager.save_recording()
        return manager, saved

    async def test_replay_refused_in_human_mode(self, tmp_path):
        manager, saved = await self._recorded_manager(tmp_path)
        manager.set_control_mode("human")
        with pytest.raises(ControlModeError):
            await manager.replay_workflow(saved["path"])

    async def test_paused_replay_resumes_and_completes(self, tmp_path):
        manager, saved = await self._recorded_manager(
            tmp_path, browser_cls=_PausingBrowser
        )
        browser = manager.browser
        browser.clicks.clear()
        browser.gate = manager.control_gate
        browser.pause_after = 2

        task = asyncio.create_task(manager.replay_workflow(saved["path"]))
        # Recorded clicks keep the 500 ms wait_after default, so poll
        # until the gate block surfaces instead of sleeping a fixed span.
        for _ in range(100):
            if manager.execution_state == "paused":
                break
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.6)  # one step's wait_after: nothing may advance
        assert not task.done()
        assert browser.clicks == ["#a", "#b"]
        assert manager.execution_state == "paused"
        events = manager.activity.export()["events"]
        assert any(e["event"] == "execution_paused_by_gate" for e in events)

        manager.resume()
        result = await asyncio.wait_for(task, timeout=5)
        assert result["success"] is True
        assert result["steps_executed"] == 5
        assert browser.clicks == ["#a", "#b", "#c", "#d"]
        assert manager.execution_state == "completed"
