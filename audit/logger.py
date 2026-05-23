"""
Audit & Logging System for Agentic Browser
Production-grade logging for reliability and service offering

Production update: container + AGENTIC_DATA_DIR aware paths (pairs with SessionManager).
DX update: includes DebugReporter for #265 fingerprint/header/patch visibility.

Perf: #44 - fully non-blocking via QueueHandler + QueueListener (stdlib) for .log writes
and dedicated background thread + queue for JSONL audit writes. No more sync file I/O
on hot log_action paths from recovery/behavior/etc.

P2 #128: Added correlation_id support for multi-account run tracing.
All log entries now include a correlation_id for cross-session traceability.
"""

import json
import logging
import logging.handlers
import os
import queue
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _resolve_log_dir() -> str:
    """Resolve container- and env-friendly log directory (mirrors session manager logic)."""
    env_dir = os.getenv("AGENTIC_DATA_DIR") or os.getenv("STEALTH_DATA_DIR")
    if env_dir:
        return str(Path(env_dir) / "logs")

    if (
        os.path.exists("/.dockerenv")
        or os.getenv("container")
        or os.getenv("KUBERNETES_SERVICE_HOST")
        or os.getenv("container") == "podman"
    ):
        return "/data/agentic-browser/logs"

    return "~/.agentic-browser/logs"


class AuditLogger:
    """
    Comprehensive logging system for agentic browser operations.
    Supports both file logging and structured JSON audit trails.
    """
    
    def __init__(self, session_name: str, log_dir: Optional[str] = None, correlation_id: Optional[str] = None):
        self.session_name = session_name
        if log_dir is None:
            log_dir = _resolve_log_dir()
        self.log_dir = Path(log_dir).expanduser()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Structured audit log
        self.audit_file = self.log_dir / f"{session_name}_audit.jsonl"
        
        # Human-readable log
        self.log_file = self.log_dir / f"{session_name}.log"
        
        # P2 #128: Correlation ID for multi-account run tracing
        self.correlation_id: str = correlation_id or str(uuid.uuid4())[:8]
        
        # === Non-blocking queued writers for #44 P1 perf ===
        # audit JSONL uses dedicated queue + background drainer thread (single writer, no per-call threads)
        self._audit_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=5000)
        self._shutdown = threading.Event()
        self._writer_thread = threading.Thread(
            target=self._drain_audit_queue,
            daemon=True,
            name=f"audit-writer-{session_name[:16]}"
        )
        self._writer_thread.start()

        # Setup standard logger with QueueHandler + QueueListener (fully non-blocking writes to .log)
        # Callers of log_action / log_error etc. never block on disk I/O.
        self.logger = logging.getLogger(f"agentic.{session_name}")
        self.logger.setLevel(logging.INFO)
        # Clean any pre-existing handlers (defensive for re-instantiation in tests)
        for h in list(self.logger.handlers):
            self.logger.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass

        self._std_log_queue: "queue.Queue[logging.LogRecord]" = queue.Queue(maxsize=2000)
        qhandler = logging.handlers.QueueHandler(self._std_log_queue)
        self.logger.addHandler(qhandler)

        file_handler = logging.FileHandler(self.log_file)
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        self._listener = logging.handlers.QueueListener(
            self._std_log_queue, file_handler, respect_handler_level=True
        )
        self._listener.start()

        self._debug_enabled = False
        self._debug_log_file = self.log_dir / f"{session_name}_debug.jsonl"
    
    def enable_debug_mode(self):
        """Enable verbose debug logging for fingerprint/stealth analysis (DX #265)."""
        self._debug_enabled = True
        # Ensure debug handler exists (idempotent). Note: when debug on, direct FileHandler on logger
        # means its writes are sync (rare, non-hotpath for normal operation; debug is explicit DX).
        if not any(isinstance(h, logging.FileHandler) and getattr(h, 'baseFilename', '').endswith('debug.jsonl') for h in self.logger.handlers):
            debug_handler = logging.FileHandler(self._debug_log_file)
            debug_handler.setFormatter(logging.Formatter('%(message)s'))
            self.logger.addHandler(debug_handler)
    
    @staticmethod
    def _redact_sensitive_values(value: str) -> str:
        """Redact sensitive VALUE patterns from a string (issue #167).

        Applies value-level redaction regardless of key name:
        - Email addresses → [user@REDACTED]
        - Common API key prefixes (ghp_*, sk-*, xai-*, AIza*, AKIA*) → [REDACTED_KEY]
        - URLs with embedded credentials (user:pass@host) → [REDACTED]@host
        - Query-param tokens (?token=xxx&api_key=xxx) → ?token=[REDACTED]&api_key=[REDACTED]
        - Bearer tokens (Bearer xxx) → Bearer [REDACTED]
        """
        if not isinstance(value, str):
            return value

        # Bearer tokens: "Bearer <token>"
        value = re.sub(
            r'\bBearer\s+\S+',
            'Bearer [REDACTED]',
            value,
            flags=re.IGNORECASE,
        )

        # URLs with credentials: scheme://user:pass@host → scheme://user:[REDACTED]@host
        value = re.sub(
            r'(://[^:@/]+:)([^@]+)(@)',
            r'\1[REDACTED]\3',
            value,
        )

        # Sensitive query parameters: ?key=xxx where key is token/api_key/etc.
        _SENSITIVE_QP_KEYS = (
            r'token|api_key|apikey|access_key|secret|password|passwd|'
            r'private_key|auth|session_id|sessionid|credentials'
        )
        value = re.sub(
            rf'([?&](?:{_SENSITIVE_QP_KEYS})=)[^&#\s]+',
            r'\1[REDACTED]',
            value,
            flags=re.IGNORECASE,
        )

        # Common API key prefixes (must come after query-param pass so full URL context is preserved)
        value = re.sub(
            r'\b(ghp_[A-Za-z0-9]{20,})\b',
            '[REDACTED_KEY]',
            value,
        )
        value = re.sub(
            r'\b(sk-[A-Za-z0-9]{20,})\b',
            '[REDACTED_KEY]',
            value,
        )
        value = re.sub(
            r'\b(xai-[A-Za-z0-9]{20,})\b',
            '[REDACTED_KEY]',
            value,
        )
        value = re.sub(
            r'\b(AIza[A-Za-z0-9_-]{20,})\b',
            '[REDACTED_KEY]',
            value,
        )
        value = re.sub(
            r'\b(AKIA[A-Z0-9]{12,})\b',
            '[REDACTED_KEY]',
            value,
        )

        # Email addresses: user@domain → [user@REDACTED]
        value = re.sub(
            r'\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b',
            r'[\1@REDACTED]',
            value,
        )

        return value

    @staticmethod
    def _redact_sensitive(details: Dict) -> Dict:
        """Redact sensitive keys AND values from details before logging.

        Prevents credential leaks in JSONL audit files and log outputs.
        - Keys matching credential patterns are fully redacted.
        - String values on all other keys are scanned for sensitive value patterns
          (emails, API keys, URLs with embedded creds, Bearer tokens).

        Redaction is mandatory by default (opt-in to disable via AGENTIC_STEALTH_NO_REDACT
        env var, intended ONLY for local debugging).
        """
        if os.getenv("AGENTIC_STEALTH_NO_REDACT", "").strip().lower() in ("1", "true", "yes"):
            return details if isinstance(details, dict) else details
        SENSITIVE_KEYS = frozenset([
            "password", "passwd", "secret", "token", "api_key", "apikey",
            "access_key", "private_key", "auth", "credentials", "cookie",
            "session_id", "sessionid", "session_token", "session_secret", "session_key",
        ])
        if not isinstance(details, dict):
            return details
        redacted = {}
        for k, v in details.items():
            k_lower = k.lower() if isinstance(k, str) else str(k).lower()
            if any(s in k_lower for s in SENSITIVE_KEYS):
                redacted[k] = "***REDACTED***"
            elif isinstance(v, dict):
                redacted[k] = AuditLogger._redact_sensitive(v)
            elif isinstance(v, str):
                redacted[k] = AuditLogger._redact_sensitive_values(v)
            else:
                redacted[k] = v
        return redacted

    def log_action(self, action: str, details: Optional[Dict] = None, level: str = "info"):
        """Log a browser action with structured data (non-blocking for #44).

        Automatically redacts sensitive keys (passwords, tokens, etc.) from details
        before writing to audit logs to prevent credential leaks.

        P2 #128: Includes correlation_id for multi-account run tracing.
        """
        # Redact sensitive fields before logging
        safe_details = self._redact_sensitive(details) if details else {}
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session": self.session_name,
            "correlation_id": self.correlation_id,  # P2 #128
            "action": action,
            "details": safe_details,
        }
        
        # Queue the audit JSONL entry (drained by background thread; never blocks caller)
        try:
            self._audit_queue.put_nowait(entry)
        except queue.Full:
            # Extremely high volume: drop (never block hot path or OOM)
            pass
        
        # Stdlib log goes through QueueHandler -> non-blocking (listener drains to FileHandler)
        msg = f"{action}"
        if safe_details:
            msg += f" | {safe_details}"
        
        if level == "error":
            self.logger.error(msg)
        elif level == "warning":
            self.logger.warning(msg)
        else:
            self.logger.info(msg)
    
    def log_error(self, action: str, error: str, details: Optional[Dict] = None):
        """Log errors with full context"""
        self.log_action(action, {
            "error": error,
            **(details or {})
        }, level="error")
    
    def log_block_detected(self, platform: str, details: Optional[Dict] = None):
        """Special logging for blocks / rate limits"""
        self.log_action("BLOCK_DETECTED", {
            "platform": platform,
            **(details or {})
        }, level="warning")
    
    def get_recent_actions(self, limit: int = 50) -> list:
        """Read recent audit entries (sync read is acceptable; only called from debug/report paths)"""
        if not self.audit_file.exists():
            return []
        
        entries = []
        with open(self.audit_file) as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))
        
        return entries[-limit:]

    def replay_sequence(self, limit: int = 30) -> list:
        """#253 lightweight replay from audit logs."""
        if not self.audit_file.exists():
            return []
        entries = self.get_recent_actions(limit * 3)
        seq = []
        for e in entries:
            a = str(e.get("action", "")).lower()
            if any(k in a for k in ("click", "type", "goto", "submit", "think", "safe")):
                seq.append({"timestamp": e.get("timestamp"), "action": e.get("action")})
        return seq[:limit]

    def _drain_audit_queue(self) -> None:
        """Background thread: drain audit queue and perform the actual (blocking) JSONL appends.
        Single writer thread eliminates the N-threads-per-action problem and keeps callers unblocked (#44).
        """
        while not self._shutdown.is_set():
            try:
                entry = self._audit_queue.get(timeout=0.25)
                if entry is None:
                    self._audit_queue.task_done()
                    continue
                try:
                    with open(self.audit_file, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                except Exception:
                    pass  # never crash writer
                finally:
                    self._audit_queue.task_done()
            except queue.Empty:
                continue
            except Exception:
                continue
        # Best-effort flush on shutdown
        try:
            while True:
                entry = self._audit_queue.get_nowait()
                try:
                    with open(self.audit_file, "a", encoding="utf-8") as f:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                except Exception:
                    pass
                self._audit_queue.task_done()
        except queue.Empty:
            pass

    def close(self) -> None:
        """Graceful shutdown of background writers and listeners (call from cleanup paths)."""
        try:
            self._shutdown.set()
            # Stop the stdlib queue listener (flushes its handler)
            if hasattr(self, "_listener") and self._listener:
                try:
                    self._listener.stop()
                except Exception:
                    pass
            # Give writer thread a moment
            if hasattr(self, "_writer_thread") and self._writer_thread.is_alive():
                self._writer_thread.join(timeout=1.0)
        except Exception:
            pass

    def get_correlation_id(self) -> str:
        """P2 #128: Get the correlation ID for this logger."""
        return self.correlation_id

    def set_correlation_id(self, correlation_id: str) -> None:
        """P2 #128: Set a new correlation ID (e.g., when linking to external trace)."""
        self.correlation_id = correlation_id

    def __del__(self):
        # Best effort
        try:
            self.close()
        except Exception:
            pass


class DebugReporter:
    """
    DX helper (#265) that captures and reports the exact stealth configuration
    applied to a browser instance: TLS fingerprint, headers, and applied patches.
    
    Allows operators to verify "what actually ran" for a given launch/preset.
    Safe no-op when debug=False; fully populated when debug=True or on explicit debug_report().
    """

    def __init__(self, logger: Optional[AuditLogger] = None, tls_manager=None, extra_headers: Optional[Dict[str, str]] = None):
        self.logger = logger
        self.tls_manager = tls_manager
        self.extra_headers = extra_headers or {}
        self.patches: Dict[str, Any] = {}
        self.records: list = []

    def record_patch(self, name: str, data: Dict[str, Any]):
        """Record a stealth patch application for later reporting."""
        self.patches[name] = data
        self.records.append({"type": "patch", "name": name, "data": data, "ts": datetime.now(timezone.utc).isoformat()})

    def dump_fingerprint(self) -> Dict[str, Any]:
        """Return the TLS / fingerprint profile chosen for this session."""
        if self.tls_manager and hasattr(self.tls_manager, "get_profile"):
            try:
                return self.tls_manager.get_profile()
            except Exception:
                pass
        if self.tls_manager and hasattr(self.tls_manager, "region"):
            return {"region": getattr(self.tls_manager, "region", "global"), "note": "partial profile"}
        return {"region": "global", "note": "default (no tls_manager available at report time)"}

    def dump_headers(self) -> Dict[str, Any]:
        """Return the extra HTTP headers that were applied."""
        return dict(self.extra_headers) if self.extra_headers else {"note": "headers not captured"}

    def dump_patches(self) -> Dict[str, Any]:
        """Return all recorded stealth patches."""
        return dict(self.patches)

    def full_debug_report(self, include_recent_logs: bool = True) -> Dict[str, Any]:
        """Produce a comprehensive debug bundle for the current browser state."""
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tls_fingerprint": self.dump_fingerprint(),
            "http_headers": self.dump_headers(),
            "stealth_patches": self.dump_patches(),
            "patch_count": len(self.patches),
        }
        if include_recent_logs and self.logger:
            try:
                report["recent_audit"] = self.logger.get_recent_actions(15)
            except Exception:
                report["recent_audit"] = ["<error reading audit>"]
        return report

    def print_human_report(self, report: Optional[Dict[str, Any]] = None):
        """Pretty(ish) console dump of the debug report. Redacts sensitive data before printing."""
        if report is None:
            report = self.full_debug_report()
        safe_report = AuditLogger._redact_sensitive(report) if isinstance(report, dict) else report
        print("\n" + "=" * 60)
        print("AGENTIC-STEALTH-BROWSER DEBUG REPORT (#265)")
        print("=" * 60)
        print(f"Generated: {safe_report.get('generated_at')}")
        print("\n[TLS / Fingerprint]")
        print(safe_report.get("tls_fingerprint"))
        print("\n[HTTP Headers]")
        for k, v in list(safe_report.get("http_headers", {}).items())[:8]:
            print(f"  {k}: {v}")
        print("\n[Stealth Patches Applied]")
        for name, data in safe_report.get("stealth_patches", {}).items():
            print(f"  - {name}: {data}")
        if "recent_audit" in safe_report:
            print(f"\n[Recent Audit Events] ({len(safe_report['recent_audit'])})")
            for e in safe_report["recent_audit"][-5:]:
                print(f"  {e}")
        print("=" * 60 + "\n")
