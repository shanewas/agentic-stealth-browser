"""
Audit Enrichment — v1.4.0

Extends AuditLogger with:
- actor/session/workflow correlation
- audit export endpoint helpers
- structured audit event enrichment
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class AuditEnricher:
    def __init__(self, audit_logger: Any = None):
        self._audit = audit_logger
        self._actor: Optional[str] = None
        self._workflow_id: Optional[str] = None

    def set_context(
        self,
        actor: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ) -> None:
        if actor is not None:
            self._actor = actor
        if workflow_id is not None:
            self._workflow_id = workflow_id

    def enrich(
        self,
        action: str,
        details: Optional[Dict[str, Any]] = None,
        level: str = "info",
    ) -> Dict[str, Any]:
        enriched = dict(details or {})
        enriched["actor"] = self._actor or "unknown"
        enriched["workflow_id"] = self._workflow_id or ""
        enriched["event_id"] = uuid.uuid4().hex[:12]

        if self._audit and hasattr(self._audit, "log_action"):
            self._audit.log_action(action, enriched, level=level)

        return enriched

    def log_workflow_step(
        self,
        step_type: str,
        step_index: int,
        success: bool,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.enrich(
            f"workflow_step_{step_type}",
            {
                "step_type": step_type,
                "step_index": step_index,
                "success": success,
                **(details or {}),
            },
            level="info" if success else "error",
        )


class AuditExporter:
    @staticmethod
    def export_jsonl(
        audit_file: str,
        output_file: Optional[str] = None,
        since_ts: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        path = Path(audit_file)
        if not path.exists():
            return []

        entries: List[Dict[str, Any]] = []
        with open(path) as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    if since_ts and entry.get("timestamp", "") < since_ts:
                        continue
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue

        if output_file:
            with open(output_file, "w") as f:
                json.dump(entries, f, indent=2, default=str)

        return entries

    @staticmethod
    def get_audit_summary(
        audit_file: str,
        since_ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        entries = AuditExporter.export_jsonl(audit_file, since_ts=since_ts)
        actions: Dict[str, int] = {}
        sessions: Dict[str, int] = {}
        errors = 0

        for entry in entries:
            action = entry.get("action", "unknown")
            actions[action] = actions.get(action, 0) + 1
            session = entry.get("session", "unknown")
            sessions[session] = sessions.get(session, 0) + 1
            if entry.get("level") == "error":
                errors += 1

        return {
            "total_entries": len(entries),
            "actions": dict(sorted(actions.items(), key=lambda x: -x[1])),
            "sessions": dict(sorted(sessions.items(), key=lambda x: -x[1])),
            "errors": errors,
            "since_ts": since_ts,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
