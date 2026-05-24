"""Tests for WorkflowPlayer execution engine."""

from unittest.mock import AsyncMock

import pytest

from workflows.player import WorkflowPlayer
from workflows.schema import Workflow, WorkflowStep


class MockBrowser:
    def __init__(self):
        self.page = AsyncMock()
        self.page.evaluate = AsyncMock(return_value="")
        self.page.screenshot = AsyncMock(return_value={"path": "/tmp/screen.png"})
        self.page.url = "https://example.com"
        self.page.title = "Example"

        self.goto = AsyncMock(return_value=True)
        self.safe_goto = AsyncMock(return_value=True)
        self.safe_click = AsyncMock(return_value=True)
        self.safe_type = AsyncMock(return_value=True)
        self.screenshot_on_error = AsyncMock(
            return_value="screenshots/error_step_0_navigate_1234567890.png"
        )


@pytest.fixture
def mock_browser():
    return MockBrowser()


@pytest.fixture
def player(mock_browser):
    return WorkflowPlayer(mock_browser)


@pytest.mark.asyncio
class TestNavigate:
    async def test_execute_navigate_step(self, player, mock_browser):
        workflow = Workflow(
            name="test-nav",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
        )
        result = await player.execute(workflow)
        assert result.success
        assert result.steps_executed == 1
        mock_browser.safe_goto.assert_called_once_with(
            "https://example.com", platform="unknown"
        )

    async def test_execute_navigate_fallback_to_goto(self, player, mock_browser):
        del mock_browser.safe_goto
        mock_browser.goto = AsyncMock(return_value=True)
        workflow = Workflow(
            name="test-nav",
            steps=[
                WorkflowStep(
                    type="navigate",
                    params={"url": "https://example.com", "platform": "test"},
                )
            ],
        )
        result = await player.execute(workflow)
        assert result.success
        mock_browser.goto.assert_called_once_with("https://example.com")


@pytest.mark.asyncio
class TestClick:
    async def test_execute_click_step(self, player, mock_browser):
        workflow = Workflow(
            name="test-click",
            steps=[WorkflowStep(type="click", params={"selector": "#btn"})],
        )
        result = await player.execute(workflow)
        assert result.success
        mock_browser.safe_click.assert_called_once_with("#btn")

    async def test_click_with_fallback(self, player, mock_browser):
        mock_browser.safe_click.side_effect = [Exception("not found"), True]
        workflow = Workflow(
            name="test-click",
            steps=[
                WorkflowStep(
                    type="click",
                    params={"selector": "#missing", "selector_fallbacks": ["#present"]},
                )
            ],
        )
        result = await player.execute(workflow)
        assert result.success
        assert mock_browser.safe_click.call_count == 2


@pytest.mark.asyncio
class TestFill:
    async def test_execute_fill_step(self, player, mock_browser):
        workflow = Workflow(
            name="test-fill",
            steps=[
                WorkflowStep(
                    type="fill", params={"selector": "#input", "value": "hello"}
                )
            ],
        )
        result = await player.execute(workflow)
        assert result.success
        mock_browser.safe_type.assert_called_once_with("#input", "hello")


@pytest.mark.asyncio
class TestVerify:
    async def test_execute_verify_step_success(self, player, mock_browser):
        mock_browser.page.evaluate = AsyncMock(
            side_effect=[True, "Expected Text", True]
        )
        workflow = Workflow(
            name="test-verify",
            steps=[
                WorkflowStep(
                    type="verify",
                    params={"selector": "h1", "text": "Expected"},
                )
            ],
        )
        result = await player.execute(workflow)
        assert result.success

    async def test_execute_verify_step_fail(self, player, mock_browser):
        mock_browser.page.evaluate = AsyncMock(side_effect=[True, "Wrong Text", True])
        workflow = Workflow(
            name="test-verify",
            steps=[
                WorkflowStep(
                    type="verify",
                    params={"selector": "h1", "text": "Expected"},
                )
            ],
        )
        result = await player.execute(workflow)
        assert not result.success
        assert result.failed_step == 0
        assert result.failed_step_type == "verify"


@pytest.mark.asyncio
class TestEndToEnd:
    async def test_execute_workflow_end_to_end(self, player, mock_browser):
        workflow = Workflow(
            name="test-e2e",
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
        mock_browser.safe_goto.assert_called_once()
        mock_browser.safe_click.assert_called_once()
        mock_browser.safe_type.assert_called_once()


@pytest.mark.asyncio
class TestExecutionResult:
    async def test_execution_result_on_success(self, player):
        workflow = Workflow(
            name="test",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
        )
        result = await player.execute(workflow)
        assert result.success is True
        assert result.steps_executed == result.total_steps
        assert result.failed_step is None
        assert result.failed_step_type is None
        assert result.error_message is None

    async def test_execution_result_on_fail(self, player, mock_browser):
        mock_browser.page.evaluate = AsyncMock(side_effect=[True, "Wrong Text", True])
        workflow = Workflow(
            name="test",
            steps=[
                WorkflowStep(
                    type="verify",
                    params={"selector": "h1", "text": "Expected"},
                )
            ],
        )
        result = await player.execute(workflow)
        assert result.success is False
        assert result.failed_step is not None
        assert result.failed_step_type == "verify"
        assert result.error_message is not None


@pytest.mark.asyncio
class TestStepTimeout:
    async def test_step_timeout(self, player, mock_browser):
        import asyncio

        async def slow_goto(*args, **kwargs):
            await asyncio.sleep(1.0)
            return True

        mock_browser.safe_goto = slow_goto

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
        assert not result.success
        assert result.failed_step == 0
        assert result.failed_step_type == "navigate"


@pytest.mark.asyncio
class TestVariableResolution:
    async def test_variable_resolution_in_steps(self, player, mock_browser):
        from workflows.variable_resolver import VariableResolver

        player.resolver = VariableResolver({"base_url": "https://example.com"})
        workflow = Workflow(
            name="test-vars",
            steps=[
                WorkflowStep(type="navigate", params={"url": "{{base_url}}"}),
            ],
        )
        result = await player.execute(workflow)
        assert result.success
        mock_browser.safe_goto.assert_called_once_with(
            "https://example.com", platform="unknown"
        )


@pytest.mark.asyncio
class TestCheckpoint:
    async def test_checkpoint_updates_after_step(self, player):
        workflow = Workflow(
            name="test",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"}),
                WorkflowStep(type="click", params={"selector": "#btn"}),
            ],
        )
        result = await player.execute(workflow)
        assert result.success
        assert len(player.checkpoint["completed_steps"]) == 2
        assert player.checkpoint["completed_steps"] == [0, 1]


@pytest.mark.asyncio
class TestConditional:
    async def test_conditional_step_true(self, player, mock_browser):
        mock_browser.page.evaluate = AsyncMock(side_effect=[True, None])
        workflow = Workflow(
            name="test-cond",
            steps=[
                WorkflowStep(
                    type="conditional",
                    params={
                        "condition": "true",
                        "steps": [
                            {"type": "click", "selector": "#btn"},
                        ],
                        "else_steps": [
                            {"type": "click", "selector": "#alt"},
                        ],
                    },
                )
            ],
        )
        result = await player.execute(workflow)
        assert result.success
        mock_browser.safe_click.assert_called_once_with("#btn")

    async def test_conditional_step_false(self, player, mock_browser):
        mock_browser.page.evaluate = AsyncMock(side_effect=[False, None])
        workflow = Workflow(
            name="test-cond",
            steps=[
                WorkflowStep(
                    type="conditional",
                    params={
                        "condition": "false",
                        "steps": [
                            {"type": "click", "selector": "#btn"},
                        ],
                        "else_steps": [
                            {"type": "click", "selector": "#alt"},
                        ],
                    },
                )
            ],
        )
        result = await player.execute(workflow)
        assert result.success
        mock_browser.safe_click.assert_called_once_with("#alt")


@pytest.mark.asyncio
class TestRunWorkflow:
    async def test_run_workflow_nested(self, player, mock_browser):
        import tempfile
        import yaml
        from pathlib import Path

        inner = {
            "name": "inner",
            "steps": [
                {"type": "click", "selector": "#nested_btn"},
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            inner_path = Path(td) / "inner.yaml"
            with open(inner_path, "w") as f:
                yaml.dump(inner, f)

            workflow = Workflow(
                name="outer",
                steps=[
                    WorkflowStep(
                        type="run_workflow",
                        params={"path": str(inner_path)},
                    )
                ],
            )
            result = await player.execute(workflow)
            assert result.success
            mock_browser.safe_click.assert_called_once_with("#nested_btn")


@pytest.mark.asyncio
class TestScreenshot:
    async def test_screenshot_step(self, player, mock_browser):
        mock_browser.screenshot_on_error = AsyncMock(
            return_value="screenshots/test.png"
        )
        workflow = Workflow(
            name="test-screenshot",
            steps=[WorkflowStep(type="screenshot", params={"path": "test.png"})],
        )
        result = await player.execute(workflow)
        assert result.success


@pytest.mark.asyncio
class TestScroll:
    async def test_scroll_step(self, player):
        workflow = Workflow(
            name="test-scroll",
            steps=[WorkflowStep(type="scroll", params={"amount": 500})],
        )
        result = await player.execute(workflow)
        assert result.success


@pytest.mark.asyncio
class TestWait:
    async def test_wait_step_simple(self, player):
        workflow = Workflow(
            name="test-wait",
            steps=[WorkflowStep(type="wait", params={"ms": 50})],
        )
        result = await player.execute(workflow)
        assert result.success


@pytest.mark.asyncio
class TestWaitForElement:
    async def test_wait_for_element_step(self, player, mock_browser):
        mock_browser.page.evaluate = AsyncMock(return_value=True)
        workflow = Workflow(
            name="test-wait-el",
            steps=[
                WorkflowStep(type="wait_for_element", params={"selector": "#thing"})
            ],
        )
        result = await player.execute(workflow)
        assert result.success


@pytest.mark.asyncio
class TestExecuteJs:
    async def test_execute_js_step(self, player, mock_browser):
        mock_browser.page.evaluate = AsyncMock(return_value="ok")
        workflow = Workflow(
            name="test-js",
            steps=[
                WorkflowStep(type="execute_js", params={"code": "console.log('hello')"})
            ],
        )
        result = await player.execute(workflow)
        assert result.success
        mock_browser.page.evaluate.assert_called_with("console.log('hello')")


@pytest.mark.asyncio
class TestInvalidStep:
    async def test_unknown_step_type_raises_error(self, player):
        workflow = Workflow(
            name="test-unknown",
            steps=[WorkflowStep(type="bogus_action", params={})],
        )
        result = await player.execute(workflow)
        assert not result.success
        assert result.failed_step == 0
        assert result.failed_step_type == "bogus_action"


@pytest.mark.asyncio
class TestMissingRequiredParam:
    async def test_missing_required_param_fails_early(self, player):
        workflow = Workflow(
            name="test-missing",
            steps=[WorkflowStep(type="navigate", params={})],
        )
        result = await player.execute(workflow)
        assert not result.success
        assert result.failed_step == 0
        assert result.failed_step_type == "navigate"
        assert "url" in result.error_message.lower()


@pytest.mark.asyncio
class TestExecutionTime:
    async def test_execution_time_is_recorded(self, player):
        workflow = Workflow(
            name="test-time",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
        )
        result = await player.execute(workflow)
        assert result.execution_time > 0
