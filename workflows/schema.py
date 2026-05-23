from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

STEP_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "navigate": {
        "required": ["url"],
        "optional": ["timeout", "wait_until", "platform"],
    },
    "click": {
        "required": ["selector"],
        "optional": ["timeout", "wait_after", "index", "selector_fallbacks"],
    },
    "fill": {
        "required": ["selector", "value"],
        "optional": ["timeout", "submit"],
    },
    "type": {
        "required": ["selector", "value"],
        "optional": ["timeout", "delay_ms", "submit"],
    },
    "select": {
        "required": ["selector", "value"],
        "optional": ["timeout"],
    },
    "verify": {
        "required": ["selector"],
        "optional": ["timeout", "text", "visible", "wait_for_text"],
    },
    "wait": {
        "required": [],
        "optional": ["ms", "selector", "text", "url"],
    },
    "wait_for_element": {
        "required": ["selector"],
        "optional": ["timeout", "state"],
    },
    "scroll": {
        "required": [],
        "optional": ["direction", "amount", "selector"],
    },
    "screenshot": {
        "required": [],
        "optional": ["path", "full_page"],
    },
    "execute_js": {
        "required": ["code"],
        "optional": [],
    },
    "conditional": {
        "required": ["condition", "steps"],
        "optional": ["else_steps"],
    },
    "run_workflow": {
        "required": ["path"],
        "optional": ["variables"],
    },
}


@dataclass
class VariableDef:
    type: str
    default: Optional[Any] = None
    required: bool = True
    description: str = ""


@dataclass
class WorkflowStep:
    type: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Workflow:
    name: str
    steps: List[WorkflowStep]
    variables: Optional[Dict[str, VariableDef]] = None
    description: Optional[str] = None


@dataclass
class ValidationResult:
    valid: bool
    errors: List[str] = field(default_factory=list)


def _dict_to_workflow(data: dict) -> Workflow:
    steps = []
    for raw in data.get("steps", []):
        step_type = raw.pop("type")
        steps.append(WorkflowStep(type=step_type, params=raw))

    variables = None
    if "variables" in data:
        variables = {
            name: VariableDef(
                type=vdef.get("type", "string"),
                default=vdef.get("default"),
                required=vdef.get("required", True),
                description=vdef.get("description", ""),
            )
            for name, vdef in data["variables"].items()
        }

    return Workflow(
        name=data["name"],
        steps=steps,
        variables=variables,
        description=data.get("description"),
    )


def load_workflow(path_or_dict) -> Workflow:
    if isinstance(path_or_dict, dict):
        return _dict_to_workflow(path_or_dict)
    with open(path_or_dict, "r") as f:
        data = yaml.safe_load(f)
    return _dict_to_workflow(data)


def validate_workflow(workflow: Workflow) -> ValidationResult:
    errors = []

    if not workflow.name:
        errors.append("Workflow name is required")

    if not workflow.steps:
        errors.append("Workflow must have at least one step")

    for i, step in enumerate(workflow.steps):
        step_type = step.type
        schema = STEP_SCHEMAS.get(step_type)

        if schema is None:
            errors.append(f"Step {i}: unknown step type '{step_type}'")
            continue

        for req in schema["required"]:
            if req not in step.params:
                errors.append(
                    f"Step {i} ({step_type}): missing required field '{req}'"
                )

        allowed = set(schema["required"] + schema["optional"])
        for key in step.params:
            if key not in allowed and key not in ("type",):
                errors.append(
                    f"Step {i} ({step_type}): unknown field '{key}'"
                )

    if workflow.variables:
        for name, vdef in workflow.variables.items():
            if not vdef.required and vdef.default is None:
                pass

    return ValidationResult(valid=len(errors) == 0, errors=errors)


def workflow_to_dict(workflow: Workflow) -> dict:
    result: dict = {"name": workflow.name}
    if workflow.description:
        result["description"] = workflow.description

    result["steps"] = []
    for step in workflow.steps:
        step_dict = {"type": step.type, **step.params}
        result["steps"].append(step_dict)

    if workflow.variables:
        result["variables"] = {}
        for name, vdef in workflow.variables.items():
            result["variables"][name] = {
                "type": vdef.type,
                "default": vdef.default,
                "required": vdef.required,
                "description": vdef.description,
            }

    return result


def workflow_to_yaml_str(workflow: Workflow) -> str:
    return yaml.dump(workflow_to_dict(workflow), default_flow_style=False, sort_keys=False)
