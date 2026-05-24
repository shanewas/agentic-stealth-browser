"""Tests for recovery module: FallbackController, checkpoint resume, and player integration."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from workflows.player import WorkflowPlayer
from workflows.recovery import FallbackController, RecoveryAction, RecoveryResult
from workflows.schema import Workflow, WorkflowStep


class MockBrowser:
    def __init__(self):
        self.page = AsyncMock()
        self.page.evaluate = AsyncMock(return_value="")
        self.page.screenshot = AsyncMock(return_value={"path": "/tmp/screen.png"})
        self.page.url = "https://example.com"
        self.page.title = "Example"
        self.page.content = AsyncMock(
            return_value="<html><body>Normal page</body></html>"
        )

        self.goto = AsyncMock(return_value=True)
        self.safe_goto = AsyncMock(return_value=True)
        self.safe_click = AsyncMock(return_value=True)
        self.safe_type = AsyncMock(return_value=True)
        self.screenshot_on_error = AsyncMock(
            return_value="screenshots/error_step_0_navigate.png"
        )


@pytest.fixture
def mock_browser():
    return MockBrowser()


@pytest.fixture
def player(mock_browser):
    return WorkflowPlayer(mock_browser)


@pytest.fixture
def fallback_controller(mock_browser):
    return FallbackController(mock_browser)


@pytest.mark.asyncio
class TestFallbackController:
    async def test_retries_element_not_found(self, fallback_controller, mock_browser):
        mock_browser.safe_click = AsyncMock(
            side_effect=[Exception("element not found"), Exception("not found"), True]
        )

        result = await fallback_controller.handle_step_error(
            step_type="click",
            params={"selector": "#btn"},
            error=Exception("element not found"),
            step_index=0,
        )

        assert result.recovered is True
        assert result.action_taken == "retry"
        assert result.retries_used >= 1

    async def test_retries_element_not_found_static_method(
        self, fallback_controller, mock_browser
    ):
        mock_browser.safe_click = AsyncMock(side_effect=[Exception("not found"), True])

        result = await fallback_controller.handle_element_not_found(
            selector="#btn", params={"selector": "#btn"}
        )

        assert result.recovered is True

    async def test_aborts_on_unknown_error(self, fallback_controller, mock_browser):
        mock_browser.page.content = AsyncMock(
            return_value="<html><body>OK</body></html>"
        )
        mock_browser.page.url = "https://example.com"

        result = await fallback_controller.handle_step_error(
            step_type="click",
            params={"selector": "#btn"},
            error=Exception("unknown fatal database error"),
            step_index=0,
        )

        assert result.recovered is False
        assert result.action_taken == "abort"
        assert result.retries_used == 0

    async def test_element_not_found_exhausts_retries_then_fails(
        self, fallback_controller, mock_browser
    ):
        mock_browser.safe_click = AsyncMock(side_effect=Exception("element not found"))

        result = await fallback_controller.handle_step_error(
            step_type="click",
            params={"selector": "#btn"},
            error=Exception("element not found"),
            step_index=0,
            recovery_config=RecoveryAction(
                action_type="retry",
                max_retries=3,
                backoff_seconds=0.01,
                take_screenshot=False,
            ),
        )

        assert result.recovered is False
        assert result.action_taken == "abort"
        assert result.retries_used == 3

    async def test_is_blocked_detects_captcha_url(
        self, fallback_controller, mock_browser
    ):
        mock_browser.page.url = "https://example.com/captcha?verify=true"

        result = await fallback_controller.is_blocked()

        assert result is True

    async def test_is_blocked_returns_false_for_normal_page(
        self, fallback_controller, mock_browser
    ):
        mock_browser.page.url = "https://example.com"
        mock_browser.page.content = AsyncMock(
            return_value="<html><body>Hello</body></html>"
        )

        result = await fallback_controller.is_blocked()

        assert result is False


@pytest.mark.asyncio
class TestPlayerRecovery:
    async def test_player_recovers_from_timeout(self, mock_browser):

        call_count = 0

        async def flaky_goto(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise TimeoutError("Navigation timed out")
            return True

        mock_browser.safe_goto = flaky_goto
        mock_browser.goto = flaky_goto

        player = WorkflowPlayer(mock_browser)
        fc = FallbackController(mock_browser)
        player.set_recovery_controller(fc)

        workflow = Workflow(
            name="test-timeout",
            steps=[
                WorkflowStep(
                    type="navigate",
                    params={"url": "https://example.com", "timeout": 100},
                )
            ],
        )
        result = await player.execute(workflow)

        assert result.recovery_used is True
        assert len(result.recovery_actions) >= 1
        assert result.recovery_actions[0]["recovered"] is True

    async def test_player_saves_checkpoint_after_each_step(self, player, tmp_path):
        checkpoint_path = tmp_path / "cp.json"

        workflow = Workflow(
            name="test-cp",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"}),
                WorkflowStep(type="click", params={"selector": "#btn"}),
            ],
        )
        result = await player.execute(workflow)

        assert result.success
        assert len(player.checkpoint["completed_steps"]) == 2

        save_path = player.save_checkpoint(str(checkpoint_path))
        assert Path(save_path).exists()

        with open(save_path) as f:
            data = json.load(f)
        assert len(data["checkpoint"]["completed_steps"]) == 2

    async def test_player_resumes_from_checkpoint(self, mock_browser, tmp_path):
        checkpoint_data = {
            "checkpoint": {
                "completed_steps": [0, 1],
                "last_url": "https://example.com",
                "variables": {},
            },
            "backend": "bridge",
            "saved_at": 9999999.0,
        }
        cp_path = tmp_path / "resume.json"
        with open(cp_path, "w") as f:
            json.dump(checkpoint_data, f)

        player = WorkflowPlayer(mock_browser)
        assert player.load_checkpoint(str(cp_path)) is True

        workflow = Workflow(
            name="test-resume",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"}),
                WorkflowStep(type="click", params={"selector": "#btn"}),
                WorkflowStep(
                    type="fill", params={"selector": "#input", "value": "test"}
                ),
            ],
        )
        result = await player.execute(workflow)
        assert result.success
        assert result.steps_executed == 3
        mock_browser.safe_goto.assert_not_called()
        mock_browser.safe_click.assert_not_called()
        mock_browser.safe_type.assert_called_once()

    async def test_player_resumes_from_checkpoint_after_failure(self, mock_browser):
        player = WorkflowPlayer(mock_browser)
        player.checkpoint["completed_steps"] = [0]

        workflow = Workflow(
            name="test-resume2",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"}),
                WorkflowStep(type="click", params={"selector": "#btn"}),
            ],
        )
        result = await player.execute(workflow)
        assert result.success
        assert result.steps_executed == 2
        mock_browser.safe_goto.assert_not_called()
        mock_browser.safe_click.assert_called_once_with("#btn")

    async def test_challenge_detected_falls_back(self, mock_browser):
        mock_browser.page.url = "https://example.com/captcha?verify=true"
        mock_browser.safe_goto = AsyncMock(
            side_effect=Exception("Something went wrong")
        )

        mock_orch = AsyncMock()
        mock_orch.recover = AsyncMock(return_value=True)

        player = WorkflowPlayer(mock_browser)
        fc = FallbackController(mock_browser, anti_block_orchestrator=mock_orch)
        player.set_recovery_controller(fc)

        workflow = Workflow(
            name="test-block",
            steps=[
                WorkflowStep(
                    type="navigate",
                    params={"url": "https://example.com/captcha?verify=true"},
                )
            ],
        )
        result = await player.execute(workflow)

        assert result.recovery_used is True
        assert len(result.recovery_actions) >= 1
        assert result.recovery_actions[0]["action_taken"] == "fallback_to_stealth"

    async def test_recovery_config_from_step(self, mock_browser):
        mock_browser.safe_click = AsyncMock(
            side_effect=[Exception("element not found"), True]
        )

        player = WorkflowPlayer(mock_browser)
        fc = FallbackController(mock_browser)
        player.set_recovery_controller(fc)

        workflow = Workflow(
            name="test-recovery-config",
            steps=[
                WorkflowStep(
                    type="click",
                    params={
                        "selector": "#btn",
                        "recovery": {
                            "max_retries": 5,
                            "backoff": 0.5,
                            "fallback_to_stealth": True,
                        },
                    },
                )
            ],
        )
        result = await player.execute(workflow)

        assert result.recovery_used is True
        assert len(result.recovery_actions) >= 1

    async def test_no_infinite_recovery_loop(self, mock_browser):
        mock_browser.safe_click = AsyncMock(side_effect=Exception("element not found"))

        player = WorkflowPlayer(mock_browser)
        fc = FallbackController(mock_browser)
        player.set_recovery_controller(fc)

        workflow = Workflow(
            name="test-no-loop",
            steps=[
                WorkflowStep(
                    type="click",
                    params={
                        "selector": "#btn",
                        "recovery": {
                            "max_retries": 3,
                            "backoff": 0.01,
                            "fallback_to_stealth": False,
                        },
                    },
                )
            ],
        )
        result = await player.execute(workflow)

        assert result.success is False
        assert result.recovery_used is True

    async def test_recovery_logs_actions(self, mock_browser):
        mock_browser.page.url = "https://example.com/captcha?verify=true"
        mock_browser.safe_goto = AsyncMock(side_effect=Exception("block detected"))

        player = WorkflowPlayer(mock_browser)
        fc = FallbackController(mock_browser)
        player.set_recovery_controller(fc)

        workflow = Workflow(
            name="test-log",
            steps=[
                WorkflowStep(
                    type="navigate",
                    params={"url": "https://example.com/captcha?verify=true"},
                )
            ],
        )
        result = await player.execute(workflow)

        assert isinstance(result.recovery_actions, list)
        assert len(result.recovery_actions) >= 1
        action = result.recovery_actions[0]
        assert "step_index" in action
        assert "step_type" in action
        assert "recovered" in action
        assert "action_taken" in action
        assert "retries_used" in action
        assert "error" in action

    async def test_save_checkpoint_default_path(self, player, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)

        workflow = Workflow(
            name="test-cp",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
        )
        await player.execute(workflow)

        save_path = player.save_checkpoint()
        assert save_path.endswith(".json")
        assert Path(save_path).exists()

    async def test_load_checkpoint_nonexistent(self, player):
        result = player.load_checkpoint("/nonexistent/path/checkpoint.json")
        assert result is False

    async def test_load_checkpoint_invalid_json(self, player, tmp_path):
        bad_path = tmp_path / "bad.json"
        bad_path.write_text("not json {{{")
        result = player.load_checkpoint(str(bad_path))
        assert result is False


@pytest.mark.asyncio
class TestFallbackControllerTimeout:
    async def test_handle_timeout_retries_with_doubled_timeout(
        self, fallback_controller, mock_browser
    ):
        mock_browser.goto = AsyncMock(return_value=True)
        mock_browser.safe_goto = AsyncMock(return_value=True)

        result = await fallback_controller.handle_timeout(
            step_type="navigate",
            params={"url": "https://example.com", "timeout": 100, "platform": "test"},
        )

        assert result.recovered is True
        assert result.action_taken == "retry"
        assert result.retries_used == 1

    async def test_handle_timeout_fails_on_double_failure(
        self, fallback_controller, mock_browser
    ):
        import asyncio

        async def slow_forever(*args, **kwargs):
            await asyncio.sleep(10.0)
            return True

        mock_browser.safe_goto = slow_forever
        mock_browser.goto = slow_forever

        result = await fallback_controller.handle_timeout(
            step_type="navigate",
            params={"url": "https://example.com", "timeout": 50},
        )

        assert result.recovered is False
        assert result.action_taken == "abort"


class TestRecoveryActionDataclass:
    def test_defaults(self):
        ra = RecoveryAction(action_type="retry")
        assert ra.action_type == "retry"
        assert ra.max_retries == 3
        assert ra.backoff_seconds == 2.0
        assert ra.take_screenshot is True


class TestRecoveryResultDataclass:
    def test_fields(self):
        rr = RecoveryResult(
            recovered=True,
            action_taken="retry",
            retries_used=1,
            screenshot_paths=["/tmp/a.png"],
            backend_used="bridge",
        )
        assert rr.recovered is True
        assert rr.action_taken == "retry"
        assert rr.error_message is None

    def test_with_error(self):
        rr = RecoveryResult(
            recovered=False,
            action_taken="abort",
            retries_used=0,
            screenshot_paths=[],
            backend_used="bridge",
            error_message="test error",
        )
        assert rr.error_message == "test error"


class TestExecutionResultRecoveryActions:
    async def test_execution_result_has_recovery_actions_list(self):
        from workflows.player import ExecutionResult

        result = ExecutionResult(
            success=True,
            steps_executed=1,
            total_steps=1,
        )
        assert isinstance(result.recovery_actions, list)
        assert len(result.recovery_actions) == 0
