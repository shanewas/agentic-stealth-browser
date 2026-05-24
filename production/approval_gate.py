"""
Approval Gates — v1.4.0

Hooks for sensitive action approval:
- Navigate to unknown domain
- execute_js
- run_workflow / stealth_replay

Approval decisions are logged via AuditLogger and can be deferred for
interactive/callback-based approval flows.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional


class ApprovalDecision(Enum):
    ALLOWED = "allowed"
    DENIED = "denied"
    PENDING = "pending"


@dataclass
class ApprovalRequest:
    request_id: str
    action: str
    details: Dict[str, Any] = field(default_factory=dict)
    session_name: str = ""
    created_at: float = field(default_factory=time.time)


@dataclass
class ApprovalResult:
    request_id: str
    decision: ApprovalDecision
    reason: str = ""
    timestamp: float = field(default_factory=time.time)


SENSITIVE_ACTIONS = {
    "navigate",
    "stealth_navigate",
    "execute_js",
    "stealth_replay",
    "run_workflow",
    "stealth_launch",
}


class ApprovalGate:
    """Blocks or allows sensitive MCP actions.

    Actions can be pre-approved via a callback or always allowed by policy.
    Unapproved actions return ApprovalDecision.PENDING, allowing the caller
    to queue the request for interactive review.
    """

    def __init__(
        self,
        audit_logger: Any = None,
        auto_approve_known_domains: bool = True,
        known_domains: Optional[List[str]] = None,
    ):
        self._audit = audit_logger
        self._auto_approve_known = auto_approve_known_domains
        self._known_domains: List[str] = known_domains or [
            "linkedin.com",
            "upwork.com",
            "github.com",
            "google.com",
        ]
        self._allow_callback: Optional[
            Callable[[ApprovalRequest], ApprovalDecision]
        ] = None
        self._pending: Dict[str, ApprovalRequest] = {}
        self._decisions: List[ApprovalResult] = []

    def set_allow_callback(
        self, callback: Callable[[ApprovalRequest], ApprovalDecision]
    ) -> None:
        self._allow_callback = callback

    def add_known_domain(self, domain: str) -> None:
        if domain not in self._known_domains:
            self._known_domains.append(domain)

    def _domain_from_url(self, url: str) -> str:
        from urllib.parse import urlparse

        try:
            p = urlparse(url)
            return (p.hostname or p.netloc or "").lower()
        except Exception:
            return url.lower()

    def check_sensitive(
        self,
        action: str,
        details: Optional[Dict[str, Any]] = None,
        session_name: str = "",
    ) -> ApprovalResult:
        import uuid

        if action not in SENSITIVE_ACTIONS:
            return ApprovalResult(
                request_id="",
                decision=ApprovalDecision.ALLOWED,
                reason="not a sensitive action",
            )

        request_id = uuid.uuid4().hex[:12]
        req = ApprovalRequest(
            request_id=request_id,
            action=action,
            details=details or {},
            session_name=session_name,
        )

        if action in ("navigate", "stealth_navigate"):
            url = (details or {}).get("url", "")
            domain = self._domain_from_url(url)
            if self._auto_approve_known and domain in self._known_domains:
                result = ApprovalResult(
                    request_id=request_id,
                    decision=ApprovalDecision.ALLOWED,
                    reason=f"known domain: {domain}",
                )
                self._log_decision(req, result)
                self._decisions.append(result)
                return result

        if self._allow_callback:
            decision = self._allow_callback(req)
            result = ApprovalResult(
                request_id=request_id,
                decision=decision,
                reason="callback decision",
            )
            self._log_decision(req, result)
            self._decisions.append(result)
            return result

        self._pending[request_id] = req
        result = ApprovalResult(
            request_id=request_id,
            decision=ApprovalDecision.PENDING,
            reason="awaiting interactive approval",
        )
        self._log_decision(req, result)
        self._decisions.append(result)
        return result

    def resolve_pending(
        self, request_id: str, approved: bool, reason: str = ""
    ) -> Optional[ApprovalResult]:
        req = self._pending.pop(request_id, None)
        if req is None:
            return None
        result = ApprovalResult(
            request_id=request_id,
            decision=ApprovalDecision.ALLOWED if approved else ApprovalDecision.DENIED,
            reason=reason or ("approved" if approved else "denied"),
        )
        self._log_decision(req, result)
        self._decisions.append(result)
        return result

    def get_pending(self) -> List[ApprovalRequest]:
        return list(self._pending.values())

    def recent_decisions(self, limit: int = 20) -> List[ApprovalResult]:
        return self._decisions[-limit:]

    def _log_decision(self, req: ApprovalRequest, result: ApprovalResult) -> None:
        if self._audit and hasattr(self._audit, "log_action"):
            self._audit.log_action(
                "approval_gate",
                {
                    "request_id": req.request_id,
                    "action": req.action,
                    "decision": result.decision.value,
                    "reason": result.reason,
                    "session": req.session_name,
                },
            )


def is_sensitive_action(action: str) -> bool:
    return action in SENSITIVE_ACTIONS


def get_sensitive_actions() -> List[str]:
    return sorted(SENSITIVE_ACTIONS)
