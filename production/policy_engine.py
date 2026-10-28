"""
Workflow Policy Engine — v1.4.0

Path/action/destination access controls for workflow execution.
Defines which sites, step types, and actions are allowed per policy.
Policy files load from ~/.agentic-browser/policies/ (YAML).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml


POLICY_DIR = Path.home() / ".agentic-browser" / "policies"
ALLOWED_STEP_TYPES = {
    "navigate",
    "click",
    "fill",
    "type",
    "select",
    "verify",
    "wait",
    "wait_for_element",
    "scroll",
    "screenshot",
    "execute_js",
    "conditional",
    "run_workflow",
}


def _normalize_domain(value: str) -> str:
    """Normalize a rule domain or candidate URL/host to a bare host name.

    Lowercases, strips one trailing dot, drops any port, and parses
    scheme-less inputs (``blocked.example/path``) as host-plus-path.
    Exact-host semantics are kept: no suffix/subdomain widening.
    """
    from urllib.parse import urlparse

    raw = (value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw if "://" in raw else f"//{raw}")
        host = parsed.hostname or ""
    except Exception:
        host = raw.split("/", 1)[0].rsplit("@", 1)[-1].split(":", 1)[0]
    host = host.strip().lower()
    if host.endswith("."):
        host = host[:-1]
    return host


@dataclass
class DomainRule:
    domain: str
    allow: bool = True
    # Note: path-level filtering is not yet implemented — only domain name is checked.

    def __post_init__(self) -> None:
        self.domain = _normalize_domain(self.domain)


@dataclass
class Policy:
    name: str
    version: str = "1.0"
    description: str = ""
    enabled: bool = True
    default_allow: bool = True
    allowed_step_types: Set[str] = field(
        default_factory=lambda: ALLOWED_STEP_TYPES.copy()
    )
    blocked_step_types: Set[str] = field(default_factory=set)
    domain_rules: List[DomainRule] = field(default_factory=list)
    require_approval_for: List[str] = field(default_factory=list)

    def is_step_type_allowed(self, step_type: str) -> bool:
        if step_type in self.blocked_step_types:
            return False
        if step_type in ALLOWED_STEP_TYPES:
            return step_type in self.allowed_step_types
        return False

    def is_domain_allowed(self, url: str) -> bool:
        host = _normalize_domain(url or "")
        if not host:
            return self.default_allow
        for rule in self.domain_rules:
            # Normalize again so directly-constructed rules (bypassing
            # __post_init__ mutations or later edits) compare equally.
            if _normalize_domain(rule.domain) == host:
                return rule.allow
        return self.default_allow

    def needs_approval(self, action_type: str) -> bool:
        return action_type in self.require_approval_for


@dataclass
class PolicyEngine:
    policies: Dict[str, Policy] = field(default_factory=dict)
    active_policy: Optional[str] = None

    def load_policies(self, policy_dir: Optional[str] = None) -> int:
        directory = Path(policy_dir) if policy_dir else POLICY_DIR
        directory = directory.expanduser()
        if not directory.exists():
            return 0

        count = 0
        for yaml_file in sorted(directory.glob("*.yaml")):
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f)
                if not data or "name" not in data:
                    continue
                domain_rules = [DomainRule(**r) for r in data.get("domain_rules", [])]
                policy = Policy(
                    name=data["name"],
                    version=data.get("version", "1.0"),
                    description=data.get("description", ""),
                    enabled=data.get("enabled", True),
                    default_allow=data.get("default_allow", True),
                    allowed_step_types=set(
                        data.get("allowed_step_types", ALLOWED_STEP_TYPES)
                    ),
                    blocked_step_types=set(data.get("blocked_step_types", [])),
                    domain_rules=domain_rules,
                    require_approval_for=data.get("require_approval_for", []),
                )
                self.policies[policy.name] = policy
                count += 1
            except Exception as exc:
                _logger = logging.getLogger("stealth.policy")
                _logger.warning(
                    "Failed to load policy from %s: %s", yaml_file.name, exc
                )
                continue
        return count

    def get_policy(self, name: Optional[str] = None) -> Optional[Policy]:
        key = name or self.active_policy
        if key:
            return self.policies.get(key)
        return Policy(name="default")

    def policy_requested(self, policy_name: Optional[str] = None) -> bool:
        """True when a policy was explicitly requested (argument or active)."""
        return bool(policy_name or self.active_policy)

    def set_active(self, policy_name: str) -> bool:
        if policy_name in self.policies:
            self.active_policy = policy_name
            return True
        # Record the request before raising so that, if a caller catches
        # the error and keeps using this engine, check_step still sees an
        # explicitly requested (but missing) policy and fails closed
        # instead of silently falling back to the fail-open default.
        self.active_policy = policy_name
        raise ValueError(f"policy '{policy_name}' is not loaded")

    def check_step(
        self, step_type: str, url: str, policy_name: Optional[str] = None
    ) -> Dict[str, Any]:
        requested = policy_name or self.active_policy
        policy = self.get_policy(policy_name)
        if policy is None:
            # A policy was explicitly requested (by argument or as the
            # active policy) but is not loaded: fail closed. The genuinely
            # unconfigured case is handled by get_policy returning the
            # default policy, and never reaches this branch.
            return {
                "allowed": False,
                "reason": f"policy '{requested}' is not loaded",
                "approval_required": True,
            }

        if not policy.is_step_type_allowed(step_type):
            return {
                "allowed": False,
                "reason": f"step type '{step_type}' is blocked",
                "approval_required": False,
            }

        if requested and url and "{{" in str(url):
            # A template variable survived resolution, so the real
            # destination cannot be checked. Fail closed when a policy
            # was explicitly requested/active; the unconfigured default
            # policy above keeps its documented fail-open behaviour.
            return {
                "allowed": False,
                "reason": f"unresolved template variable in URL '{url}'",
                "approval_required": True,
            }

        if not policy.is_domain_allowed(url):
            return {
                "allowed": False,
                "reason": f"domain in '{url}' is not allowed",
                "approval_required": False,
            }

        needs_approval = policy.needs_approval(step_type)
        return {
            "allowed": True,
            "reason": "ok",
            "approval_required": needs_approval,
        }

    def create_example_policy(self, policy_dir: Optional[str] = None) -> Path:
        directory = Path(policy_dir) if policy_dir else POLICY_DIR
        directory.mkdir(parents=True, exist_ok=True)
        example_path = directory / "example.yaml"

        example = {
            "name": "example",
            "version": "1.0",
            "description": "Example workflow policy - allow common platforms",
            "enabled": True,
            "default_allow": False,
            "allowed_step_types": list(ALLOWED_STEP_TYPES),
            "blocked_step_types": ["execute_js"],
            "domain_rules": [
                {"domain": "example.com", "allow": True},
                {"domain": "linkedin.com", "allow": True},
                {"domain": "upwork.com", "allow": True},
                {"domain": "github.com", "allow": True},
            ],
            "require_approval_for": ["execute_js", "navigate"],
        }

        with open(example_path, "w") as f:
            yaml.safe_dump(example, f, default_flow_style=False, sort_keys=False)
        return example_path
