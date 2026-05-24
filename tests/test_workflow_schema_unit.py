"""
Unit tests for Workflow schema validation: missing fields, unknown types, edge cases.

Covers:
- validate_workflow() for all step types
- Missing required fields for all step types
- Unknown step type
- Unknown fields in steps
- Empty workflow errors
- load_workflow from dict/YAML
- workflow_to_dict / workflow_to_yaml_str roundtrips
"""
from copy import deepcopy

import pytest

from workflows.schema import (
    load_workflow,
    validate_workflow,
    workflow_to_dict,
    workflow_to_yaml_str,
    STEP_SCHEMAS,
)


class TestWorkflowValidation:
    def test_empty_name(self):
        wf = load_workflow({"name": "", "steps": [{"type": "navigate", "url": "https://example.com"}]})
        result = validate_workflow(wf)
        assert result.valid is False
        assert any("name" in e for e in result.errors)

    def test_no_steps(self):
        wf = load_workflow({"name": "test", "steps": []})
        result = validate_workflow(wf)
        assert result.valid is False
        assert any("at least one step" in e for e in result.errors)

    def test_unknown_step_type(self):
        wf = load_workflow({"name": "test", "steps": [{"type": "teleport", "x": 1}]})
        result = validate_workflow(wf)
        assert result.valid is False
        assert any("unknown step type" in e for e in result.errors)

    def test_unknown_field_in_step(self):
        wf = load_workflow({"name": "test", "steps": [{"type": "navigate", "url": "https://example.com", "bogus": 123}]})
        result = validate_workflow(wf)
        assert result.valid is False
        assert any("unknown field" in e.lower() for e in result.errors)


class TestMissingRequiredFields:
    def test_navigate_missing_url(self):
        wf = load_workflow({"name": "t", "steps": [{"type": "navigate"}]})
        result = validate_workflow(wf)
        assert result.valid is False
        assert any("url" in e for e in result.errors)

    def test_click_missing_selector(self):
        wf = load_workflow({"name": "t", "steps": [{"type": "click"}]})
        result = validate_workflow(wf)
        assert result.valid is False
        assert any("selector" in e for e in result.errors)

    def test_fill_missing_selector_and_value(self):
        wf = load_workflow({"name": "t", "steps": [{"type": "fill"}]})
        result = validate_workflow(wf)
        assert result.valid is False
        assert any("selector" in e for e in result.errors)
        assert any("value" in e for e in result.errors)

    def test_type_missing_params(self):
        wf = load_workflow({"name": "t", "steps": [{"type": "type", "selector": "#x"}]})
        result = validate_workflow(wf)
        assert result.valid is False
        assert any("value" in e for e in result.errors)

    def test_select_missing_params(self):
        wf = load_workflow({"name": "t", "steps": [{"type": "select", "value": "opt1"}]})
        result = validate_workflow(wf)
        assert result.valid is False
        assert any("selector" in e for e in result.errors)

    def test_execute_js_missing_code(self):
        wf = load_workflow({"name": "t", "steps": [{"type": "execute_js"}]})
        result = validate_workflow(wf)
        assert result.valid is False
        assert any("code" in e for e in result.errors)

    def test_conditional_missing_condition_and_steps(self):
        wf = load_workflow({"name": "t", "steps": [{"type": "conditional"}]})
        result = validate_workflow(wf)
        assert result.valid is False
        assert any("condition" in e for e in result.errors)
        assert any("steps" in e for e in result.errors)

    def test_run_workflow_missing_path(self):
        wf = load_workflow({"name": "t", "steps": [{"type": "run_workflow"}]})
        result = validate_workflow(wf)
        assert result.valid is False
        assert any("path" in e for e in result.errors)


class TestAllStepTypesValid:
    STEP_FIXTURES = [
        ("navigate", {"url": "https://example.com"}),
        ("click", {"selector": "#btn"}),
        ("fill", {"selector": "input", "value": "hello"}),
        ("type", {"selector": "input", "value": "hello"}),
        ("select", {"selector": "select", "value": "option1"}),
        ("verify", {"selector": "h1"}),
        ("wait", {}),
        ("wait_for_element", {"selector": ".loading"}),
        ("scroll", {}),
        ("screenshot", {}),
        ("execute_js", {"code": "console.log('hi')"}),
        ("conditional", {"condition": "true", "steps": [{"type": "navigate", "url": "https://example.com"}]}),
        ("run_workflow", {"path": "some/path.yaml"}),
    ]

    @pytest.mark.parametrize("step_type,params", STEP_FIXTURES)
    def test_step_validates(self, step_type, params):
        wf = load_workflow({"name": "test", "steps": [{"type": step_type, **params}]})
        result = validate_workflow(wf)
        assert result.valid is True, f"Failed for {step_type}: {result.errors}"


class TestWorkflowRoundtrip:
    def test_dict_to_workflow_to_yaml(self):
        data = {
            "name": "my-workflow",
            "description": "A test",
            "steps": [
                {"type": "navigate", "url": "https://example.com"},
                {"type": "click", "selector": "#btn", "timeout": 5000},
            ],
        }
        wf = load_workflow(deepcopy(data))
        yaml_str = workflow_to_yaml_str(wf)
        assert "name: my-workflow" in yaml_str
        assert "url: https://example.com" in yaml_str

    def test_workflow_to_dict_preserves_variables(self):
        data = {
            "name": "test",
            "steps": [{"type": "navigate", "url": "{{base}}"}],
            "variables": {
                "base": {"type": "string", "default": "https://example.com", "required": True, "description": "base url"},
            },
        }
        wf = load_workflow(deepcopy(data))
        d = workflow_to_dict(wf)
        assert "variables" in d
        assert d["variables"]["base"]["default"] == "https://example.com"
        assert d["variables"]["base"]["type"] == "string"


class TestLoadWorkflow:
    def test_load_from_dict(self):
        wf = load_workflow({"name": "t", "steps": [{"type": "navigate", "url": "https://x.com"}]})
        assert wf.name == "t"
        assert len(wf.steps) == 1

    def test_load_preserves_optional_params(self):
        data = {
            "name": "t",
            "steps": [{"type": "navigate", "url": "https://x.com", "timeout": 30000, "wait_until": "load"}],
        }
        wf = load_workflow(data)
        assert wf.steps[0].params["timeout"] == 30000
        assert wf.steps[0].params["wait_until"] == "load"

    def test_load_with_description_and_variables(self):
        data = {
            "name": "t",
            "description": "desc",
            "steps": [{"type": "navigate", "url": "https://x.com"}],
            "variables": {"v": {"type": "string", "required": False, "description": ""}},
        }
        wf = load_workflow(data)
        assert wf.description == "desc"
        assert "v" in wf.variables
