from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

SCHEMA_VERSION = "1.0.0"

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
    version: str = SCHEMA_VERSION
    metadata: Optional[Dict[str, Any]] = None


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
        version=data.get("version", SCHEMA_VERSION),
        metadata=data.get("metadata"),
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


def validate_workflow_steps(workflow: Workflow) -> List[str]:
    warnings: List[str] = []

    for i, step in enumerate(workflow.steps):
        step_type = step.type
        params = step.params

        if step_type == "navigate":
            if "timeout" not in params:
                warnings.append(
                    f"Step {i} (navigate): no timeout set; navigation may hang indefinitely"
                )
            if not params.get("url"):
                warnings.append(f"Step {i} (navigate): empty or missing URL")

        elif step_type == "fill":
            if i < len(workflow.steps) - 1:
                next_step = workflow.steps[i + 1]
                if next_step.type == "click" and not params.get("submit"):
                    warnings.append(
                        f"Step {i} (fill): fill step is not followed by verify — consider adding a verify "
                        f"step after fill to confirm the input was accepted"
                    )

        elif step_type == "type":
            if i < len(workflow.steps) - 1:
                next_step = workflow.steps[i + 1]
                if next_step.type == "click" and not params.get("submit"):
                    warnings.append(
                        f"Step {i} (type): type step is not followed by verify — consider adding a verify step"
                    )

        elif step_type == "click":
            if "wait_after" not in params or params.get("wait_after", 0) == 0:
                warnings.append(
                    f"Step {i} (click): no wait_after set; the page may not have time to react"
                )

        elif step_type == "verify":
            visible = params.get("visible", True)
            if "text" not in params and visible is True and "wait_for_text" not in params:
                if not params.get("text"):
                    warnings.append(
                        f"Step {i} (verify): verifying element exists but not checking text content"
                    )

        elif step_type == "wait":
            if not any(k in params for k in ("ms", "selector", "text", "url")):
                warnings.append(
                    f"Step {i} (wait): no wait condition specified; step will sleep for default 1000ms"
                )

        elif step_type == "conditional":
            condition = params.get("condition", "")
            if condition in ("true", "false", "1", "0"):
                warnings.append(
                    f"Step {i} (conditional): condition '{condition}' appears to be a literal — "
                    f"is this intentional?"
                )

        elif step_type == "scoll":
            warnings.append(
                f"Step {i} (scoll): typo detected — did you mean 'scroll'?"
            )

    if len(workflow.steps) > 20:
        warnings.append(
            f"Workflow has {len(workflow.steps)} steps — consider breaking into smaller composable workflows"
        )

    return warnings


def workflow_diff(old: Workflow, new: Workflow) -> Dict[str, Any]:
    diff: Dict[str, Any] = {
        "name_changed": old.name != new.name,
        "description_changed": old.description != new.description,
        "version_old": old.version,
        "version_new": new.version,
        "step_count_old": len(old.steps),
        "step_count_new": len(new.steps),
        "steps_added": 0,
        "steps_removed": 0,
        "steps_modified": 0,
        "added_step_indices": [],
        "removed_step_indices": [],
        "modified_step_indices": [],
        "details": [],
    }

    max_steps = max(len(old.steps), len(new.steps))
    for i in range(max_steps):
        old_step = old.steps[i] if i < len(old.steps) else None
        new_step = new.steps[i] if i < len(new.steps) else None

        if old_step is None and new_step is not None:
            diff["steps_added"] += 1
            diff["added_step_indices"].append(i)
            diff["details"].append({
                "index": i,
                "change": "added",
                "new_type": new_step.type,
                "new_params": new_step.params,
            })
        elif old_step is not None and new_step is None:
            diff["steps_removed"] += 1
            diff["removed_step_indices"].append(i)
            diff["details"].append({
                "index": i,
                "change": "removed",
                "old_type": old_step.type,
                "old_params": old_step.params,
            })
        elif old_step and new_step:
            if old_step.type != new_step.type:
                diff["steps_modified"] += 1
                diff["modified_step_indices"].append(i)
                diff["details"].append({
                    "index": i,
                    "change": "type_changed",
                    "old_type": old_step.type,
                    "new_type": new_step.type,
                })
            elif old_step.params != new_step.params:
                diff["steps_modified"] += 1
                diff["modified_step_indices"].append(i)
                param_diff = {}
                all_keys = set(list(old_step.params.keys()) + list(new_step.params.keys()))
                for key in all_keys:
                    old_val = old_step.params.get(key)
                    new_val = new_step.params.get(key)
                    if old_val != new_val:
                        param_diff[key] = {"old": old_val, "new": new_val}
                diff["details"].append({
                    "index": i,
                    "change": "params_modified",
                    "step_type": old_step.type,
                    "param_diff": param_diff,
                })

    return diff


def workflow_to_dict(workflow: Workflow) -> dict:
    result: dict = {"name": workflow.name}
    if workflow.description:
        result["description"] = workflow.description

    result["version"] = workflow.version

    if workflow.metadata:
        result["metadata"] = workflow.metadata

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
