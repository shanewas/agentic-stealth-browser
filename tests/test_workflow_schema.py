"""Tests for workflow schema, validation, and variable resolution."""

from copy import deepcopy

import pytest

from workflows.schema import (
    load_workflow,
    validate_workflow,
    workflow_to_dict,
    workflow_to_yaml_str,
)
from workflows.variable_resolver import VariableResolver

VALID_YAML = """
name: test-echo
description: Simple smoke test workflow
steps:
  - type: navigate
    url: https://example.com
  - type: verify
    selector: h1
    text: Example Domain
"""


class TestLoadWorkflow:
    def test_load_from_yaml_string(self):
        workflow = load_workflow(
            {
                "name": "test",
                "steps": [{"type": "navigate", "url": "https://example.com"}],
            }
        )
        assert workflow.name == "test"
        assert len(workflow.steps) == 1
        assert workflow.steps[0].type == "navigate"
        assert workflow.steps[0].params["url"] == "https://example.com"


class TestValidation:
    def test_valid_workflow_passes(self):
        data = {
            "name": "test",
            "steps": [
                {"type": "navigate", "url": "https://example.com"},
                {"type": "verify", "selector": "h1", "text": "OK"},
            ],
        }
        workflow = load_workflow(data)
        result = validate_workflow(workflow)
        assert result.valid is True
        assert result.errors == []

    def test_missing_required_field(self):
        data = {
            "name": "test",
            "steps": [
                {"type": "navigate"},
            ],
        }
        workflow = load_workflow(data)
        result = validate_workflow(workflow)
        assert result.valid is False
        assert any("missing required field" in e for e in result.errors)

    def test_unknown_step_type(self):
        data = {
            "name": "test",
            "steps": [
                {"type": "bogus_action", "foo": "bar"},
            ],
        }
        workflow = load_workflow(data)
        result = validate_workflow(workflow)
        assert result.valid is False
        assert any("unknown step type" in e for e in result.errors)


class TestRoundtrip:
    def test_dict_to_workflow_to_dict(self):
        original = {
            "name": "example",
            "description": "A test workflow",
            "variables": {
                "my_var": {
                    "type": "string",
                    "default": "hello",
                    "required": True,
                    "description": "a var",
                },
            },
            "steps": [
                {
                    "type": "navigate",
                    "url": "https://example.com",
                    "wait_until": "load",
                },
                {"type": "click", "selector": "#btn", "timeout": 5000},
            ],
        }
        workflow = load_workflow(deepcopy(original))
        result = workflow_to_dict(workflow)

        assert result["name"] == original["name"]
        assert result["description"] == original["description"]
        assert result["steps"][0]["type"] == "navigate"
        assert result["steps"][0]["url"] == "https://example.com"
        assert result["steps"][0]["wait_until"] == "load"
        assert result["steps"][1]["type"] == "click"
        assert result["steps"][1]["selector"] == "#btn"
        assert result["steps"][1]["timeout"] == 5000
        assert "variables" in result
        assert "my_var" in result["variables"]
        assert result["variables"]["my_var"]["default"] == "hello"


class TestAllStepTypes:
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
        ("conditional", {"condition": "true", "steps": []}),
        ("run_workflow", {"path": "some/path.yaml"}),
    ]

    @pytest.mark.parametrize("step_type,params", STEP_FIXTURES)
    def test_step_type_passes_validation(self, step_type, params):
        data = {
            "name": "test",
            "steps": [{"type": step_type, **params}],
        }
        workflow = load_workflow(data)
        result = validate_workflow(workflow)
        assert result.valid is True, f"Failed for {step_type}: {result.errors}"


class TestVariableResolverBasic:
    def test_replaces_variable(self):
        resolver = VariableResolver({"greeting": "hello"})
        result = resolver.resolve("{{greeting}} world")
        assert result == "hello world"

    def test_runtime_override_over_default(self):
        resolver = VariableResolver({"name": "default"})
        result = resolver.resolve("{{name}}", runtime_vars={"name": "override"})
        assert result == "override"

    def test_builtin_timestamp(self):
        resolver = VariableResolver()
        result = resolver.resolve("ts={{timestamp}}")
        assert "ts=" in result
        after_equals = result.split("=", 1)[1]
        assert "T" in after_equals

    def test_builtin_date(self):
        resolver = VariableResolver()
        result = resolver.resolve("date={{date}}")
        assert "date=" in result
        after_equals = result.split("=", 1)[1]
        assert after_equals.count("-") == 2

    def test_builtin_random_name(self):
        resolver = VariableResolver()
        result = resolver.resolve("name={{random_name}}")
        assert "name=" in result
        after_equals = result.split("=", 1)[1]
        assert len(after_equals) == 8

    def test_unresolved_variable_left_as_is(self):
        resolver = VariableResolver()
        result = resolver.resolve("{{nonexistent}}")
        assert result == "{{nonexistent}}"


class TestResolveWorkflow:
    def test_replaces_variables_in_step_values(self):
        workflow = load_workflow(
            {
                "name": "test",
                "steps": [
                    {"type": "navigate", "url": "{{base_url}}/dashboard"},
                    {"type": "fill", "selector": "input", "value": "{{username}}"},
                ],
                "variables": {
                    "base_url": {"type": "string", "default": "https://example.com"},
                    "username": {"type": "string"},
                },
            }
        )
        resolver = VariableResolver({"username": "admin"})
        resolved = resolver.resolve_workflow(
            workflow, runtime_vars={"base_url": "https://prod.example.com"}
        )

        assert resolved.steps[0].params["url"] == "https://prod.example.com/dashboard"
        assert resolved.steps[1].params["value"] == "admin"


class TestWorkflowToYamlStr:
    def test_serialization(self):
        data = {
            "name": "test",
            "steps": [{"type": "navigate", "url": "https://example.com"}],
        }
        workflow = load_workflow(data)
        yaml_str = workflow_to_yaml_str(workflow)
        assert "name: test" in yaml_str
        assert "type: navigate" in yaml_str
        assert "url: https://example.com" in yaml_str
