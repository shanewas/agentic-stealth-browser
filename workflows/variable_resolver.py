import copy
import datetime
import random
import re
import string
from typing import Any, Dict, Optional

from workflows.schema import Workflow

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")


class VariableResolver:
    def __init__(self, variables: Optional[Dict[str, Any]] = None):
        self._defaults: Dict[str, Any] = variables or {}

    def resolve(
        self,
        template: str,
        runtime_vars: Optional[Dict[str, Any]] = None,
    ) -> str:
        overrides = runtime_vars or {}

        def replacer(match: re.Match) -> str:
            var_name = match.group(1)

            if var_name in overrides:
                return str(overrides[var_name])

            if var_name in self._defaults:
                return str(self._defaults[var_name])

            builtin = _resolve_builtin(var_name)
            if builtin is not None:
                return str(builtin)

            return match.group(0)

        return _VAR_RE.sub(replacer, template)

    def resolve_workflow(
        self,
        workflow: Workflow,
        runtime_vars: Optional[Dict[str, Any]] = None,
    ) -> Workflow:
        resolved = copy.deepcopy(workflow)

        overrides = runtime_vars or {}

        for step in resolved.steps:
            for key, value in step.params.items():
                if isinstance(value, str):
                    step.params[key] = self.resolve(value, overrides)
                elif isinstance(value, list):
                    step.params[key] = [
                        self.resolve(v, overrides) if isinstance(v, str) else v
                        for v in value
                    ]
                elif isinstance(value, dict):
                    step.params[key] = {
                        k: self.resolve(v, overrides) if isinstance(v, str) else v
                        for k, v in value.items()
                    }

        return resolved


def _resolve_builtin(name: str) -> Optional[str]:
    builtins: Dict[str, Any] = {
        "timestamp": lambda: datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "date": lambda: datetime.date.today().isoformat(),
        "random_name": lambda: "".join(
            random.choices(string.ascii_lowercase + string.digits, k=8)
        ),
        "last_url": lambda: "",
    }
    factory = builtins.get(name)
    if factory is not None:
        return str(factory())
    return None
