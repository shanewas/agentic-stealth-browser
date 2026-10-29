"""Regression tests for the workflows/sessions audit fixes (H1-H3, M2, M7, L3)."""

from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml

from workflows.player import WorkflowPlayer
from workflows.schema import (
    VariableDef,
    Workflow,
    WorkflowStep,
    load_workflow,
    validate_workflow,
)


class MockBrowser:
    def __init__(self):
        self.page = AsyncMock()
        self.page.evaluate = AsyncMock(return_value=True)
        self.page.screenshot = AsyncMock(return_value=None)
        self.page.url = "https://example.com"
        self.goto = AsyncMock(return_value=True)
        self.safe_goto = AsyncMock(return_value=True)
        self.safe_click = AsyncMock(return_value=True)
        self.safe_type = AsyncMock(return_value=True)
        self.screenshot_on_error = AsyncMock(return_value="screenshots/error.png")


@pytest.fixture
def mock_browser():
    return MockBrowser()


@pytest.fixture
def player(mock_browser):
    return WorkflowPlayer(mock_browser)


def _write_workflow(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data))
    return path


class TestScrollAmountInjection:
    async def test_hostile_amount_never_reaches_evaluate(self, player, mock_browser):
        workflow = Workflow(
            name="test-scroll-hostile",
            steps=[
                WorkflowStep(
                    type="scroll",
                    params={"amount": "0); globalThis.pwned = 1; //"},
                )
            ],
        )
        result = await player.execute(workflow)
        assert not result.success
        assert result.failed_step == 0
        assert "amount" in (result.error_message or "")
        for call in mock_browser.page.evaluate.call_args_list:
            assert "pwned" not in str(call)

    async def test_numeric_string_amount_still_scrolls(self, player, mock_browser):
        workflow = Workflow(
            name="test-scroll-ok",
            steps=[WorkflowStep(type="scroll", params={"amount": "500"})],
        )
        result = await player.execute(workflow)
        assert result.success
        mock_browser.page.evaluate.assert_called_once_with("window.scrollBy(0, 500)")


class TestConditionalBranchValidation:
    async def test_malformed_branch_step_errors_not_dispatches(
        self, player, mock_browser
    ):
        workflow = Workflow(
            name="test-cond-bad-branch",
            steps=[
                WorkflowStep(
                    type="conditional",
                    params={
                        "condition": "true",
                        "steps": [{"type": "click"}],  # missing selector
                        "else_steps": [],
                    },
                )
            ],
        )
        result = await player.execute(workflow)
        assert not result.success
        assert "selector" in (result.error_message or "")
        mock_browser.safe_click.assert_not_called()

    async def test_branch_step_missing_type_errors(self, player, mock_browser):
        workflow = Workflow(
            name="test-cond-no-type",
            steps=[
                WorkflowStep(
                    type="conditional",
                    params={
                        "condition": "true",
                        "steps": [{"selector": "#btn"}],
                        "else_steps": [],
                    },
                )
            ],
        )
        result = await player.execute(workflow)
        assert not result.success
        mock_browser.safe_click.assert_not_called()


class TestRunWorkflowContainment:
    async def test_parent_escape_rejected(self, player, mock_browser, tmp_path):
        root = tmp_path / "root"
        _write_workflow(
            tmp_path / "escape.yaml",
            {"name": "escape", "steps": [{"type": "click", "selector": "#evil"}]},
        )
        outer = _write_workflow(
            root / "outer.yaml",
            {
                "name": "outer",
                "steps": [{"type": "run_workflow", "path": "../escape.yaml"}],
            },
        )
        result = await player.execute(load_workflow(str(outer)))
        assert not result.success
        mock_browser.safe_click.assert_not_called()

    async def test_absolute_path_rejected(self, player, mock_browser, tmp_path):
        root = tmp_path / "root"
        inner = _write_workflow(
            tmp_path / "inner.yaml",
            {"name": "inner", "steps": [{"type": "click", "selector": "#x"}]},
        )
        outer = _write_workflow(
            root / "outer.yaml",
            {
                "name": "outer",
                "steps": [{"type": "run_workflow", "path": str(inner)}],
            },
        )
        result = await player.execute(load_workflow(str(outer)))
        assert not result.success
        mock_browser.safe_click.assert_not_called()

    async def test_same_file_two_spellings_is_cycle(
        self, player, mock_browser, tmp_path
    ):
        root = tmp_path / "root"
        _write_workflow(
            root / "a.yaml",
            {
                "name": "a",
                "steps": [{"type": "run_workflow", "path": "./a.yaml"}],
            },
        )
        outer = _write_workflow(
            root / "outer.yaml",
            {
                "name": "outer",
                "steps": [{"type": "run_workflow", "path": "a.yaml"}],
            },
        )
        result = await player.execute(load_workflow(str(outer)))
        assert not result.success
        assert "Cycle detected" in (result.error_message or "")

    async def test_legitimate_nested_sibling_succeeds(
        self, player, mock_browser, tmp_path
    ):
        root = tmp_path / "root"
        _write_workflow(
            root / "sub" / "inner.yaml",
            {"name": "inner", "steps": [{"type": "click", "selector": "#nested"}]},
        )
        outer = _write_workflow(
            root / "outer.yaml",
            {
                "name": "outer",
                "steps": [{"type": "run_workflow", "path": "sub/inner.yaml"}],
            },
        )
        result = await player.execute(load_workflow(str(outer)))
        assert result.success
        mock_browser.safe_click.assert_called_once_with("#nested")

    async def test_configured_workflows_root_for_in_memory_workflow(
        self, mock_browser, tmp_path
    ):
        _write_workflow(
            tmp_path / "inner.yaml",
            {"name": "inner", "steps": [{"type": "click", "selector": "#cfg"}]},
        )
        configured = WorkflowPlayer(mock_browser, workflows_root=tmp_path)
        workflow = Workflow(
            name="outer",
            steps=[WorkflowStep(type="run_workflow", params={"path": "inner.yaml"})],
        )
        result = await configured.execute(workflow)
        assert result.success
        mock_browser.safe_click.assert_called_once_with("#cfg")


class TestScreenshotContainment:
    async def test_escaping_path_rejected(self, mock_browser, tmp_path):
        shots = tmp_path / "shots"
        player = WorkflowPlayer(mock_browser, screenshots_dir=shots)
        workflow = Workflow(
            name="test-shot-escape",
            steps=[WorkflowStep(type="screenshot", params={"path": "../evil.png"})],
        )
        result = await player.execute(workflow)
        assert not result.success
        mock_browser.page.screenshot.assert_not_called()

    async def test_normal_name_lands_under_screenshots_dir(
        self, mock_browser, tmp_path
    ):
        shots = tmp_path / "shots"
        player = WorkflowPlayer(mock_browser, screenshots_dir=shots)
        workflow = Workflow(
            name="test-shot-ok",
            steps=[WorkflowStep(type="screenshot", params={"path": "shot.png"})],
        )
        result = await player.execute(workflow)
        assert result.success
        called_path = Path(mock_browser.page.screenshot.call_args.kwargs["path"])
        assert called_path == (shots / "shot.png").resolve()
        assert called_path.is_relative_to(shots.resolve())

    async def test_non_png_rejected(self, mock_browser, tmp_path):
        player = WorkflowPlayer(mock_browser, screenshots_dir=tmp_path / "shots")
        workflow = Workflow(
            name="test-shot-jpg",
            steps=[WorkflowStep(type="screenshot", params={"path": "shot.jpg"})],
        )
        result = await player.execute(workflow)
        assert not result.success
        mock_browser.page.screenshot.assert_not_called()


class TestDeclaredVariables:
    async def test_declared_default_used(self, player, mock_browser):
        workflow = Workflow(
            name="test-var-default",
            steps=[WorkflowStep(type="navigate", params={"url": "{{base_url}}/x"})],
            variables={
                "base_url": VariableDef(
                    type="string", default="https://example.com", required=False
                )
            },
        )
        result = await player.execute(workflow)
        assert result.success
        mock_browser.safe_goto.assert_called_once_with(
            "https://example.com/x", platform="unknown"
        )

    async def test_runtime_var_overrides_default(self, player, mock_browser):
        workflow = Workflow(
            name="test-var-override",
            steps=[WorkflowStep(type="navigate", params={"url": "{{base_url}}/x"})],
            variables={
                "base_url": VariableDef(
                    type="string", default="https://example.com", required=False
                )
            },
        )
        result = await player.execute(
            workflow, runtime_vars={"base_url": "https://prod.example.com"}
        )
        assert result.success
        mock_browser.safe_goto.assert_called_once_with(
            "https://prod.example.com/x", platform="unknown"
        )

    async def test_missing_required_fails_before_any_step(
        self, player, mock_browser
    ):
        workflow = Workflow(
            name="test-var-missing",
            steps=[WorkflowStep(type="navigate", params={"url": "{{api_key}}/x"})],
            variables={"api_key": VariableDef(type="string", required=True)},
        )
        result = await player.execute(workflow)
        assert not result.success
        assert result.steps_executed == 0
        assert "api_key" in (result.error_message or "")
        mock_browser.safe_goto.assert_not_called()


class TestLoadWorkflowMalformed:
    def test_same_dict_loads_twice_and_is_unmodified(self):
        data = {
            "name": "test",
            "steps": [{"type": "navigate", "url": "https://example.com"}],
        }
        snapshot = deepcopy(data)
        first = load_workflow(data)
        second = load_workflow(data)
        assert data == snapshot
        assert first.steps[0].type == second.steps[0].type == "navigate"
        assert first.steps[0].params == second.steps[0].params

    @pytest.mark.parametrize(
        "data,match",
        [
            (["not", "a", "dict"], "mapping"),
            ({"name": "t", "steps": "nope"}, "steps.*list"),
            ({"name": "t", "steps": ["nope"]}, "step 0.*mapping"),
            ({"name": "t", "steps": [{"url": "https://x.com"}]}, "step 0.*type"),
        ],
    )
    def test_malformed_inputs_raise_value_error(self, data, match):
        with pytest.raises(ValueError, match=match):
            load_workflow(data)

    @pytest.mark.parametrize(
        "data",
        [
            {"steps": [{"type": "navigate", "url": "https://x.com"}]},
            {"name": "", "steps": [{"type": "navigate", "url": "https://x.com"}]},
        ],
    )
    def test_missing_or_empty_name_loads_for_validate_workflow(self, data):
        workflow = load_workflow(data)
        assert workflow.name == ""
        result = validate_workflow(workflow)
        assert not result.valid
        assert any("name" in e for e in result.errors)

    def test_unknown_type_still_loads_for_validate_workflow(self):
        workflow = load_workflow(
            {"name": "t", "steps": [{"type": "teleport", "x": 1}]}
        )
        result = validate_workflow(workflow)
        assert not result.valid
        assert any("unknown step type" in e for e in result.errors)
