"""
Workflow Policy Engine — v1.4.0

Path/action/destination access controls for workflow execution.
Defines which sites, step types, and actions are allowed per policy.
Policy files load from ~/.agentic-browser/policies/ (YAML).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml


POLICY_DIR = Path.home() / ".agentic-browser" / "policies"
ALLOWED_STEP_TYPES = {"navigate", "click", "fill", "type", "select", "verify",
                      "wait", "wait_for_element", "scroll", "screenshot",
                      "execute_js", "conditional", "run_workflow"}


@dataclass
class DomainRule:
    domain: str
    allow: bool = True
    # Note: path-level filtering is not yet implemented — only domain name is checked.


@dataclass
class Policy:
    name: str
    version: str = "1.0"
    description: str = ""
    enabled: bool = True
    default_allow: bool = True
    allowed_step_types: Set[str] = field(default_factory=lambda: ALLOWED_STEP_TYPES.copy())
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
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
            host = parsed.hostname or parsed.netloc
        except Exception:
            host = url

        host_lower = (host or "").lower()
        for rule in self.domain_rules:
            if rule.domain.lower() == host_lower:
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
                domain_rules = [
                    DomainRule(**r) for r in data.get("domain_rules", [])
                ]
                policy = Policy(
                    name=data["name"],
                    version=data.get("version", "1.0"),
                    description=data.get("description", ""),
                    enabled=data.get("enabled", True),
                    default_allow=data.get("default_allow", True),
                    allowed_step_types=set(data.get("allowed_step_types", ALLOWED_STEP_TYPES)),
                    blocked_step_types=set(data.get("blocked_step_types", [])),
                    domain_rules=domain_rules,
                    require_approval_for=data.get("require_approval_for", []),
                )
                self.policies[policy.name] = policy
                count += 1
            except Exception as exc:
                _logger = logging.getLogger("stealth.policy")
                _logger.warning("Failed to load policy from %s: %s", yaml_file.name, exc)
                continue
        return count

    def get_policy(self, name: Optional[str] = None) -> Optional[Policy]:
        key = name or self.active_policy
        if key:
            return self.policies.get(key)
        return Policy(name="default")

    def set_active(self, policy_name: str) -> bool:
        if policy_name in self.policies:
            self.active_policy = policy_name
            return True
        return False

    def check_step(
        self, step_type: str, url: str, policy_name: Optional[str] = None
    ) -> Dict[str, Any]:
        policy = self.get_policy(policy_name)
        if policy is None:
            return {"allowed": True, "reason": "no policy", "approval_required": False}

        if not policy.is_step_type_allowed(step_type):
            return {
                "allowed": False,
                "reason": f"step type '{step_type}' is blocked",
                "approval_required": False,
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
