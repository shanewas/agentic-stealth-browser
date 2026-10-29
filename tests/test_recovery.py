"""Tests for recovery module: FallbackController, checkpoint resume, and player integration."""

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from workflows.player import WorkflowPlayer, workflow_checkpoint_identity
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

        captured_configs = []
        original_handle_step_error = fc.handle_step_error

        async def capturing_handle_step_error(*args, **kwargs):
            captured_configs.append(kwargs.get("recovery_config"))
            return await original_handle_step_error(*args, **kwargs)

        fc.handle_step_error = capturing_handle_step_error

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

        # Healing and recovery are distinct mechanisms: the healed click
        # completes directly, so the recovery controller is never invoked
        # and the step's recovery config is never parsed.
        assert result.success is True
        assert result.steps_executed == 1
        assert result.auto_healed_selectors == [
            {
                "step_index": 0,
                "step_type": "click",
                "original_selector": "#btn",
                "healed_selector": '[id*="btn"]',
            }
        ]
        assert [
            call.args[0] for call in mock_browser.safe_click.call_args_list
        ] == ["#btn", '[id*="btn"]']
        assert result.recovery_used is False
        assert result.recovery_actions == []
        assert captured_configs == []

        # Recovery-config parsing is still covered explicitly: a selector
        # with no healed candidates ("button") falls through to recovery,
        # which must receive the config parsed from the step params.
        mock_browser.safe_click = AsyncMock(
            side_effect=[Exception("element not found"), True]
        )
        unhealed_player = WorkflowPlayer(mock_browser)
        unhealed_fc = FallbackController(mock_browser)
        unhealed_player.set_recovery_controller(unhealed_fc)

        unhealed_configs = []
        original_unhealed_handle = unhealed_fc.handle_step_error

        async def capturing_unhealed_handle(*args, **kwargs):
            unhealed_configs.append(kwargs.get("recovery_config"))
            return await original_unhealed_handle(*args, **kwargs)

        unhealed_fc.handle_step_error = capturing_unhealed_handle

        unhealed_workflow = Workflow(
            name="test-recovery-config-unhealed",
            steps=[
                WorkflowStep(
                    type="click",
                    params={
                        "selector": "button",
                        "recovery": {
                            "max_retries": 5,
                            "backoff": 0.5,
                            "fallback_to_stealth": True,
                        },
                    },
                )
            ],
        )
        unhealed_result = await unhealed_player.execute(unhealed_workflow)

        assert unhealed_result.success is True
        assert unhealed_result.recovery_used is True
        assert len(unhealed_result.recovery_actions) >= 1
        assert len(unhealed_configs) == 1
        parsed_config = unhealed_configs[0]
        assert parsed_config is not None
        assert parsed_config.action_type == "retry"
        assert parsed_config.max_retries == 5
        assert parsed_config.backoff_seconds == 0.5
        assert parsed_config.take_screenshot is True

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


class _BytesPageBrowser:
    """Browser stub without screenshot_on_error; page returns raw bytes."""

    def __init__(self, screenshot_result):
        self.page = AsyncMock()
        self.page.screenshot = AsyncMock(return_value=screenshot_result)
        self.page.url = "https://example.com"


@pytest.mark.asyncio
class TestRecoveryScreenshotBytes:
    async def test_bytes_are_written_to_returned_path(self, tmp_path):
        controller = FallbackController(
            _BytesPageBrowser(b"png"), screenshots_dir=tmp_path / "shots"
        )
        path = await controller._try_screenshot(0, 0)
        assert path is not None
        assert Path(path).read_bytes() == b"png"

    async def test_no_bytes_returns_none(self, tmp_path):
        controller = FallbackController(
            _BytesPageBrowser(None), screenshots_dir=tmp_path / "shots"
        )
        assert await controller._try_screenshot(0, 0) is None

    async def test_screenshot_error_returns_none(self, tmp_path):
        browser = _BytesPageBrowser(b"png")
        browser.page.screenshot = AsyncMock(side_effect=RuntimeError("boom"))
        controller = FallbackController(browser, screenshots_dir=tmp_path / "shots")
        assert await controller._try_screenshot(0, 0) is None


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


@pytest.mark.asyncio
class TestRecoveryRedispatch:
    async def test_fill_recovered_only_after_successful_refill(
        self, fallback_controller, mock_browser
    ):
        mock_browser.safe_type = AsyncMock(return_value=True)

        result = await fallback_controller.handle_step_error(
            step_type="fill",
            params={"selector": "#input", "value": "hello"},
            error=Exception("element not found"),
            step_index=0,
            recovery_config=RecoveryAction(
                action_type="retry", max_retries=1, take_screenshot=False
            ),
        )

        assert result.recovered is True
        mock_browser.safe_type.assert_called_once_with("#input", "hello")
        mock_browser.safe_click.assert_not_called()

    async def test_fill_not_recovered_when_refill_fails(
        self, fallback_controller, mock_browser
    ):
        mock_browser.safe_type = AsyncMock(
            side_effect=Exception("element not found")
        )

        result = await fallback_controller.handle_step_error(
            step_type="fill",
            params={"selector": "#input", "value": "hello"},
            error=Exception("element not found"),
            step_index=0,
            recovery_config=RecoveryAction(
                action_type="retry", max_retries=1, take_screenshot=False
            ),
        )

        assert result.recovered is False
        mock_browser.safe_type.assert_called_once_with("#input", "hello")

    async def test_verify_recovered_only_after_assertion_repasses(
        self, fallback_controller, mock_browser
    ):
        mock_browser.page.evaluate = AsyncMock(
            side_effect=[True, "Expected Text", True]
        )

        result = await fallback_controller.handle_step_error(
            step_type="verify",
            params={"selector": "h1", "text": "Expected"},
            error=Exception("element not found"),
            step_index=0,
            recovery_config=RecoveryAction(
                action_type="retry", max_retries=1, take_screenshot=False
            ),
        )

        assert result.recovered is True
        mock_browser.safe_click.assert_not_called()

    async def test_verify_still_failing_is_not_recovered(
        self, fallback_controller, mock_browser
    ):
        mock_browser.page.evaluate = AsyncMock(return_value=False)

        result = await fallback_controller.handle_step_error(
            step_type="verify",
            params={"selector": "h1", "text": "Expected"},
            error=Exception("element not found"),
            step_index=0,
            recovery_config=RecoveryAction(
                action_type="retry", max_retries=1, take_screenshot=False
            ),
        )

        assert result.recovered is False

    async def test_player_reports_failure_when_verify_still_fails(
        self, mock_browser
    ):
        mock_browser.page.evaluate = AsyncMock(return_value=False)

        player = WorkflowPlayer(mock_browser)
        player.set_recovery_controller(FallbackController(mock_browser))
        workflow = Workflow(
            name="test-verify-recovery-fails",
            steps=[
                WorkflowStep(
                    type="verify",
                    params={
                        "selector": "h1",
                        "text": "Expected",
                        "recovery": {"max_retries": 1, "take_screenshot": False},
                    },
                )
            ],
        )
        result = await player.execute(workflow)

        assert result.success is False
        assert result.failed_step == 0
        assert result.recovery_actions[0]["recovered"] is False


@pytest.mark.asyncio
class TestWorkflowBoundCheckpoints:
    async def test_mismatched_workflow_checkpoint_is_ignored(
        self, mock_browser, tmp_path
    ):
        checkpoint_data = {
            "checkpoint": {
                "completed_steps": [0, 1],
                "last_url": "https://example.com",
                "variables": {},
                "workflow_name": "other-workflow",
                "steps_hash": "0" * 64,
                "workflow_identity": {
                    "workflow_name": "other-workflow",
                    "steps_hash": "0" * 64,
                },
            },
            "backend": "bridge",
            "saved_at": 9999999.0,
        }
        cp_path = tmp_path / "mismatched.json"
        cp_path.write_text(json.dumps(checkpoint_data))

        player = WorkflowPlayer(mock_browser)
        assert player.load_checkpoint(str(cp_path)) is True

        workflow = Workflow(
            name="test-mismatch",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"}),
                WorkflowStep(type="click", params={"selector": "#btn"}),
            ],
        )
        result = await player.execute(workflow)

        assert result.success
        assert result.steps_executed == 2
        assert player.checkpoint_warning is not None
        assert "Ignoring checkpoint" in player.checkpoint_warning
        mock_browser.safe_goto.assert_called_once()
        mock_browser.safe_click.assert_called_once_with("#btn")

    async def test_matching_workflow_checkpoint_resumes(
        self, mock_browser, tmp_path
    ):
        workflow = Workflow(
            name="test-matching-resume",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"}),
                WorkflowStep(type="click", params={"selector": "#btn"}),
            ],
        )
        identity = workflow_checkpoint_identity(workflow)
        checkpoint_data = {
            "checkpoint": {
                "completed_steps": [0],
                "last_url": "https://example.com",
                "variables": {},
                "workflow_name": identity["workflow_name"],
                "steps_hash": identity["steps_hash"],
                "workflow_identity": identity,
            },
            "backend": "bridge",
            "saved_at": 9999999.0,
        }
        cp_path = tmp_path / "matching.json"
        cp_path.write_text(json.dumps(checkpoint_data))

        player = WorkflowPlayer(mock_browser)
        assert player.load_checkpoint(str(cp_path)) is True
        result = await player.execute(workflow)

        assert result.success
        assert result.steps_executed == 2
        mock_browser.safe_goto.assert_not_called()
        mock_browser.safe_click.assert_called_once_with("#btn")

    async def test_nested_workflow_indices_do_not_skip_outer_steps(
        self, mock_browser, tmp_path
    ):
        import yaml

        inner_path = tmp_path / "inner.yaml"
        inner_path.write_text(
            yaml.dump(
                {
                    "name": "inner",
                    "steps": [
                        {"type": "click", "selector": "#inner-1"},
                        {"type": "click", "selector": "#inner-2"},
                    ],
                }
            )
        )
        workflow = Workflow(
            name="outer",
            steps=[
                WorkflowStep(type="click", params={"selector": "#outer-first"}),
                WorkflowStep(
                    type="run_workflow", params={"path": "inner.yaml"}
                ),
                WorkflowStep(type="click", params={"selector": "#outer-last"}),
            ],
        )

        player = WorkflowPlayer(mock_browser, workflows_root=tmp_path)
        result = await player.execute(workflow)

        assert result.success
        assert [
            call.args[0] for call in mock_browser.safe_click.call_args_list
        ] == ["#outer-first", "#inner-1", "#inner-2", "#outer-last"]
        assert player.checkpoint["completed_steps"] == [0, 1, 2]


@pytest.mark.asyncio
class TestCheckpointValidationAndAtomicSave:
    async def test_malformed_checkpoint_load_returns_false_without_crashing(
        self, mock_browser, tmp_path
    ):
        wrong_type_path = tmp_path / "wrong-type.json"
        wrong_type_path.write_text(json.dumps({"checkpoint": "oops"}))
        truncated_path = tmp_path / "truncated.json"
        truncated_path.write_text('{"checkpoint": {"completed_steps": [')
        wrong_field_path = tmp_path / "wrong-field.json"
        wrong_field_path.write_text(
            json.dumps(
                {
                    "checkpoint": {
                        "completed_steps": "0",
                        "last_url": "https://example.com",
                        "variables": {},
                    }
                }
            )
        )

        player = WorkflowPlayer(mock_browser)
        assert player.load_checkpoint(str(wrong_type_path)) is False
        assert player.load_checkpoint(str(truncated_path)) is False
        assert player.load_checkpoint(str(wrong_field_path)) is False
        assert player.checkpoint["completed_steps"] == []

        workflow = Workflow(
            name="test-after-malformed-checkpoint",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
        )
        result = await player.execute(workflow)
        assert result.success

    async def test_saved_checkpoint_round_trips(self, mock_browser, tmp_path):
        workflow = Workflow(
            name="test-round-trip",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"}),
                WorkflowStep(type="click", params={"selector": "#btn"}),
            ],
        )
        player = WorkflowPlayer(mock_browser)
        result = await player.execute(workflow)
        assert result.success

        cp_path = tmp_path / "round-trip.json"
        save_path = player.save_checkpoint(str(cp_path))
        assert Path(save_path).exists()
        assert list(tmp_path.glob(".checkpoint-*.tmp")) == []

        resumed = WorkflowPlayer(mock_browser)
        assert resumed.load_checkpoint(save_path) is True
        identity = workflow_checkpoint_identity(workflow)
        assert resumed.checkpoint["completed_steps"] == [0, 1]
        assert resumed.checkpoint["workflow_name"] == identity["workflow_name"]
        assert resumed.checkpoint["steps_hash"] == identity["steps_hash"]

        mock_browser.safe_goto.reset_mock()
        mock_browser.safe_click.reset_mock()
        resumed_result = await resumed.execute(workflow)
        assert resumed_result.success
        assert resumed_result.steps_executed == 2
        mock_browser.safe_goto.assert_not_called()
        mock_browser.safe_click.assert_not_called()


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
