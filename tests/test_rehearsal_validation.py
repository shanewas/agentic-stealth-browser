"""Tests for rehearsal mode and pre-save validation in v1.2.0."""

from unittest.mock import AsyncMock

import pytest

from workflows.player import RehearsalResult, WorkflowPlayer
from workflows.schema import Workflow, WorkflowStep, validate_workflow_steps


class MockBrowser:
    def __init__(self):
        self.page = AsyncMock()
        self.page.evaluate = AsyncMock(return_value=True)
        self.page.screenshot = AsyncMock(return_value={"path": "/tmp/screen.png"})
        self.page.url = "https://example.com"
        self.screenshot_on_error = AsyncMock(return_value="screenshots/test.png")


@pytest.fixture
def mock_browser():
    return MockBrowser()


@pytest.fixture
def player(mock_browser):
    return WorkflowPlayer(mock_browser)


@pytest.mark.asyncio
class TestRehearse:
    async def test_rehearse_navigate(self, player):
        workflow = Workflow(
            name="test-rehearse",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
        )
        result = await player.rehearse(workflow)
        assert isinstance(result, RehearsalResult)
        assert result.total_steps == 1
        assert result.steps_validated == 1
        assert any("would navigate" in w.lower() for w in result.warnings)

    async def test_rehearse_click_checks_selector(self, player, mock_browser):
        mock_browser.page.evaluate = AsyncMock(return_value=True)
        workflow = Workflow(
            name="test-rehearse",
            steps=[WorkflowStep(type="click", params={"selector": "#btn"})],
        )
        result = await player.rehearse(workflow)
        assert len(result.selectors_used) == 1
        assert result.selectors_used[0]["selector"] == "#btn"

    async def test_rehearse_click_missing_selector(self, player, mock_browser):
        mock_browser.page.evaluate = AsyncMock(return_value=False)
        workflow = Workflow(
            name="test-rehearse",
            steps=[WorkflowStep(type="click", params={"selector": "#missing"})],
        )
        result = await player.rehearse(workflow)
        assert any("NOT FOUND" in w for w in result.warnings)

    async def test_rehearse_fill(self, player):
        workflow = Workflow(
            name="test-rehearse",
            steps=[
                WorkflowStep(
                    type="fill", params={"selector": "#input", "value": "hello"}
                )
            ],
        )
        result = await player.rehearse(workflow)
        assert any("would fill" in w.lower() for w in result.warnings)

    async def test_rehearse_verify(self, player):
        workflow = Workflow(
            name="test-rehearse",
            steps=[
                WorkflowStep(type="verify", params={"selector": "h1", "text": "Hello"})
            ],
        )
        result = await player.rehearse(workflow)
        assert any("would verify" in w.lower() for w in result.warnings)

    async def test_rehearse_run_workflow(self, player):
        workflow = Workflow(
            name="test-rehearse",
            steps=[WorkflowStep(type="run_workflow", params={"path": "nested.yaml"})],
        )
        result = await player.rehearse(workflow)
        assert any("nested workflow" in w.lower() for w in result.warnings)

    async def test_rehearse_conditional(self, player):
        workflow = Workflow(
            name="test-rehearse",
            steps=[
                WorkflowStep(
                    type="conditional",
                    params={
                        "condition": "document.querySelector('#thing') !== null",
                        "steps": [{"type": "click", "selector": "#btn"}],
                        "else_steps": [{"type": "click", "selector": "#alt"}],
                    },
                )
            ],
        )
        result = await player.rehearse(workflow)
        assert any("condition" in w.lower() for w in result.warnings)

    async def test_rehearse_wait(self, player):
        workflow = Workflow(
            name="test-rehearse",
            steps=[WorkflowStep(type="wait", params={"ms": 1000})],
        )
        result = await player.rehearse(workflow)
        assert any("would wait" in w.lower() for w in result.warnings)

    async def test_rehearse_screenshot(self, player, mock_browser):
        workflow = Workflow(
            name="test-rehearse",
            steps=[WorkflowStep(type="screenshot", params={})],
        )
        result = await player.rehearse(workflow)
        assert any("screenshot" in w.lower() for w in result.warnings)

    async def test_rehearse_scroll(self, player):
        workflow = Workflow(
            name="test-rehearse",
            steps=[
                WorkflowStep(type="scroll", params={"direction": "down", "amount": 500})
            ],
        )
        result = await player.rehearse(workflow)
        assert any("would scroll" in w.lower() for w in result.warnings)

    async def test_rehearse_select(self, player):
        workflow = Workflow(
            name="test-rehearse",
            steps=[
                WorkflowStep(
                    type="select", params={"selector": "select", "value": "option1"}
                )
            ],
        )
        result = await player.rehearse(workflow)
        assert any("would select" in w.lower() for w in result.warnings)

    async def test_rehearse_execute_js(self, player):
        workflow = Workflow(
            name="test-rehearse",
            steps=[
                WorkflowStep(type="execute_js", params={"code": "console.log('hi')"})
            ],
        )
        result = await player.rehearse(workflow)
        assert any("would execute js" in w.lower() for w in result.warnings)

    async def test_rehearse_execution_time(self, player):
        workflow = Workflow(
            name="test-rehearse",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
        )
        result = await player.rehearse(workflow)
        assert result.execution_time > 0


class TestValidateWorkflowSteps:
    def test_navigate_no_timeout_warns(self):
        workflow = Workflow(
            name="test",
            steps=[
                WorkflowStep(type="navigate", params={"url": "https://example.com"})
            ],
        )
        warnings = validate_workflow_steps(workflow)
        assert any("no timeout" in w.lower() for w in warnings)

    def test_fill_not_followed_by_verify_warns(self):
        workflow = Workflow(
            name="test",
            steps=[
                WorkflowStep(
                    type="fill", params={"selector": "#input", "value": "hello"}
                ),
                WorkflowStep(type="click", params={"selector": "#btn"}),
            ],
        )
        warnings = validate_workflow_steps(workflow)
        assert any("not followed by verify" in w.lower() for w in warnings)

    def test_click_no_wait_after_warns(self):
        workflow = Workflow(
            name="test",
            steps=[WorkflowStep(type="click", params={"selector": "#btn"})],
        )
        warnings = validate_workflow_steps(workflow)
        assert any("no wait_after" in w.lower() for w in warnings)

    def test_literal_conditional_warns(self):
        workflow = Workflow(
            name="test",
            steps=[
                WorkflowStep(
                    type="conditional",
                    params={
                        "condition": "true",
                        "steps": [{"type": "click", "selector": "#btn"}],
                    },
                )
            ],
        )
        warnings = validate_workflow_steps(workflow)
        assert any("literal" in w.lower() for w in warnings)

    def test_large_workflow_warns(self):
        steps = [
            WorkflowStep(
                type="navigate", params={"url": "https://example.com", "timeout": 10000}
            )
            for _ in range(25)
        ]
        workflow = Workflow(name="large", steps=steps)
        warnings = validate_workflow_steps(workflow)
        assert any("smaller" in w.lower() for w in warnings)

    def test_scoll_typo_warns(self):
        workflow = Workflow(
            name="test",
            steps=[WorkflowStep(type="scoll", params={})],
        )
        warnings = validate_workflow_steps(workflow)
        assert any("typo" in w.lower() for w in warnings)

    def test_empty_wait_warns(self):
        workflow = Workflow(
            name="test",
            steps=[WorkflowStep(type="wait", params={})],
        )
        warnings = validate_workflow_steps(workflow)
        assert any("no wait condition" in w.lower() for w in warnings)

    def test_valid_workflow_no_warnings(self):
        workflow = Workflow(
            name="test",
            steps=[
                WorkflowStep(
                    type="navigate",
                    params={"url": "https://example.com", "timeout": 30000},
                ),
                WorkflowStep(type="verify", params={"selector": "h1", "text": "Hello"}),
            ],
        )
        warnings = validate_workflow_steps(workflow)
        assert len(warnings) == 0
