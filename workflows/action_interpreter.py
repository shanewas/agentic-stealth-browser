from typing import Dict, List

from workflows.schema import STEP_SCHEMAS

STEP_DEFAULTS: Dict[str, Dict[str, object]] = {
    "navigate": {"timeout": 30000, "wait_until": "domcontentloaded"},
    "click": {"timeout": 30000, "wait_after": 500, "index": 0, "selector_fallbacks": []},
    "fill": {"timeout": 30000, "submit": False},
    "type": {"timeout": 30000, "delay_ms": 50, "submit": False},
    "select": {"timeout": 30000},
    "verify": {"timeout": 30000, "visible": True},
    "wait": {"ms": 1000},
    "wait_for_element": {"timeout": 30000, "state": "visible"},
    "scroll": {"direction": "down", "amount": 300},
    "screenshot": {"path": "", "full_page": False},
    "execute_js": {},
    "conditional": {},
    "run_workflow": {"variables": {}},
}

_TYPE_COERCIONS: Dict[str, Dict[str, type]] = {
    "navigate": {"timeout": int},
    "click": {"timeout": int, "wait_after": int, "index": int},
    "fill": {"timeout": int},
    "type": {"timeout": int, "delay_ms": int},
    "select": {"timeout": int},
    "verify": {"timeout": int},
    "wait": {"ms": int},
    "wait_for_element": {"timeout": int},
    "scroll": {"amount": int},
    "screenshot": {},
    "execute_js": {},
    "conditional": {},
    "run_workflow": {},
}


def get_required_fields(step_type: str) -> List[str]:
    schema = STEP_SCHEMAS.get(step_type)
    if schema is None:
        return []
    return list(schema["required"])


def get_optional_fields(step_type: str) -> List[str]:
    schema = STEP_SCHEMAS.get(step_type)
    if schema is None:
        return []
    return list(schema["optional"])


def normalize_step_params(step_type: str, params: Dict) -> Dict:
    schema = STEP_SCHEMAS.get(step_type)
    if schema is None:
        return dict(params)

    normalized = dict(params)

    defaults = STEP_DEFAULTS.get(step_type, {})
    for key, default_val in defaults.items():
        if key not in normalized:
            normalized[key] = default_val

    coercions = _TYPE_COERCIONS.get(step_type, {})
    for key, coerce_type in coercions.items():
        if key in normalized and not isinstance(normalized[key], coerce_type):
            try:
                normalized[key] = coerce_type(normalized[key])
            except (ValueError, TypeError):
                pass

    return normalized


def validate_step_params(step_type: str, params: Dict) -> List[str]:
    errors: List[str] = []
    schema = STEP_SCHEMAS.get(step_type)

    if schema is None:
        errors.append(f"Unknown step type '{step_type}'")
        return errors

    for req in schema["required"]:
        if req not in params or params[req] in (None, ""):
            errors.append(f"Missing required field '{req}' for step type '{step_type}'")

    return errors
