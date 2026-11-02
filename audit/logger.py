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

import hashlib
import hmac
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

from sessions.validation import validate_identifier

_NO_HMAC_KEY_MSG = (
    "AGENTIC_AUDIT_HMAC_KEY is not set or empty: the audit HMAC chain is "
    "using an empty key and can be recomputed by anyone who can edit the "
    "audit file. Set AGENTIC_AUDIT_HMAC_KEY to make the chain tamper-evident."
)

# Per-audit-file locks (M5): serialize writers from multiple AuditLogger
# instances for the same file in this process.
_AUDIT_FILE_LOCKS: Dict[str, threading.Lock] = {}
_AUDIT_FILE_LOCKS_GUARD = threading.Lock()


def _lock_for_audit_file(path: Path) -> threading.Lock:
    key = os.path.abspath(str(path))
    with _AUDIT_FILE_LOCKS_GUARD:
        lock = _AUDIT_FILE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _AUDIT_FILE_LOCKS[key] = lock
        return lock


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

    def __init__(
        self,
        session_name: str,
        log_dir: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ):
        # M6: session_name becomes path components / a glob prefix below.
        # Reuse SessionManager's identifier rules (sessions.validation is a
        # stdlib-only leaf, so this import creates no cycle).
        validate_identifier(session_name, field="session_name")
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
        self._prev_hash: Optional[str] = None
        # M5: tail signature (size, mtime_ns) matching _prev_hash; a mismatch
        # means another instance wrote, so the last hash is re-read.
        self._audit_tail_signature: Optional[tuple] = None
        self._audit_file_lock = _lock_for_audit_file(self.audit_file)
        self._hmac_key_warned = False
        # M2: dropped / failed audit entries are counted, never silent.
        self.dropped_audit_entries = 0
        self.failed_audit_writes = 0
        self._unreported_drops = 0
        self._drop_lock = threading.Lock()

        # === Non-blocking queued writers for #44 P1 perf ===
        # audit JSONL uses dedicated queue + background drainer thread (single writer, no per-call threads)
        self._audit_queue: "queue.Queue[Dict[str, Any]]" = queue.Queue(maxsize=5000)
        self._shutdown = threading.Event()
        self._writer_thread = threading.Thread(
            target=self._drain_audit_queue,
            daemon=True,
            name=f"audit-writer-{session_name[:16]}",
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
                logging.getLogger(__name__).debug("suppressed exception", exc_info=True)

        self._std_log_queue: "queue.Queue[logging.LogRecord]" = queue.Queue(
            maxsize=2000
        )
        qhandler = logging.handlers.QueueHandler(self._std_log_queue)
        self.logger.addHandler(qhandler)

        file_handler = logging.handlers.RotatingFileHandler(
            self.log_file,
            maxBytes=int(os.getenv("AGENTIC_AUDIT_MAX_BYTES", str(10 * 1024 * 1024))),
            backupCount=int(os.getenv("AGENTIC_AUDIT_BACKUP_COUNT", "5")),
        )
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(formatter)
        self._listener = logging.handlers.QueueListener(
            self._std_log_queue, file_handler, respect_handler_level=True
        )
        self._listener.start()

        self._debug_enabled = False
        self._debug_log_file = self.log_dir / f"{session_name}_debug.jsonl"

        self._purge_old_logs()

    def enable_debug_mode(self):
        """Enable verbose debug logging for fingerprint/stealth analysis (DX #265)."""
        self._debug_enabled = True
        # Ensure debug handler exists (idempotent). Note: when debug on, direct FileHandler on logger
        # means its writes are sync (rare, non-hotpath for normal operation; debug is explicit DX).
        if not any(
            isinstance(h, logging.FileHandler)
            and getattr(h, "baseFilename", "").endswith("debug.jsonl")
            for h in self.logger.handlers
        ):
            debug_handler = logging.FileHandler(self._debug_log_file)
            debug_handler.setFormatter(logging.Formatter("%(message)s"))
            self.logger.addHandler(debug_handler)

    @staticmethod
    def _redact_sensitive_values(value: str) -> str:
        """Redact sensitive VALUE patterns from a string (issue #167).

        Applies value-level redaction regardless of key name:
        - Email addresses → [user@REDACTED]
        - Common API key prefixes (ghp_*, github_pat_*, sk-*, xai-*, AIza*, AKIA*) → [REDACTED_KEY]
        - Slack tokens (xoxb-/xoxp-/xoxa-/xoxr-/xoxs-*) and JWTs (eyJ…) → [REDACTED_KEY]
        - URLs with embedded credentials (user:pass@host) → [REDACTED]@host
        - Query-param tokens (?token=xxx&api_key=xxx) → ?token=[REDACTED]&api_key=[REDACTED]
        - Bearer tokens (Bearer xxx) → Bearer [REDACTED]
        """
        if not isinstance(value, str):
            return value

        # Bearer tokens: "Bearer <token>"
        value = re.sub(
            r"\bBearer\s+\S+",
            "Bearer [REDACTED]",
            value,
            flags=re.IGNORECASE,
        )

        # URLs with credentials: scheme://user:pass@host → scheme://user:[REDACTED]@host
        value = re.sub(
            r"(://[^:@/]+:)([^@]+)(@)",
            r"\1[REDACTED]\3",
            value,
        )

        # Sensitive query parameters: ?key=xxx where key is token/api_key/etc.
        _SENSITIVE_QP_KEYS = (
            r"token|api_key|apikey|access_key|secret|password|passwd|"
            r"private_key|auth|session_id|sessionid|credentials"
        )
        value = re.sub(
            rf"([?&](?:{_SENSITIVE_QP_KEYS})=)[^&#\s]+",
            r"\1[REDACTED]",
            value,
            flags=re.IGNORECASE,
        )

        # Common API key prefixes (must come after query-param pass so full URL context is preserved)
        value = re.sub(
            r"\b(ghp_[A-Za-z0-9]{20,})\b",
            "[REDACTED_KEY]",
            value,
        )
        value = re.sub(
            r"\b(sk-[A-Za-z0-9]{20,})\b",
            "[REDACTED_KEY]",
            value,
        )
        value = re.sub(
            r"\b(xai-[A-Za-z0-9]{20,})\b",
            "[REDACTED_KEY]",
            value,
        )
        value = re.sub(
            r"\b(AIza[A-Za-z0-9_-]{20,})\b",
            "[REDACTED_KEY]",
            value,
        )
        value = re.sub(
            r"\b(AKIA[A-Z0-9]{12,})\b",
            "[REDACTED_KEY]",
            value,
        )
        value = re.sub(
            r"\b(github_pat_[A-Za-z0-9_]{20,})\b",
            "[REDACTED_KEY]",
            value,
        )
        value = re.sub(
            r"\b(xox[bpras]-[A-Za-z0-9-]{10,})\b",
            "[REDACTED_KEY]",
            value,
        )
        # JWT: three base64url segments, header segment starts with eyJ.
        value = re.sub(
            r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
            "[REDACTED_KEY]",
            value,
        )

        # Email addresses: user@domain → [user@REDACTED]
        value = re.sub(
            r"\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b",
            r"[\1@REDACTED]",
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

        Redaction is always on and cannot be disabled.
        """
        SENSITIVE_KEYS = frozenset(
            [
                "password",
                "passwd",
                "secret",
                "token",
                "api_key",
                "apikey",
                "access_key",
                "private_key",
                "auth",
                "credential",
                "credentials",
                "cookie",
                "session_id",
                "sessionid",
                "session_token",
                "session_secret",
                "session_key",
            ]
        )
        if not isinstance(details, dict):
            return details
        redacted = {}
        for k, v in details.items():
            k_lower = k.lower() if isinstance(k, str) else str(k).lower()
            if any(s in k_lower for s in SENSITIVE_KEYS):
                redacted[k] = "***REDACTED***"
            else:
                redacted[k] = AuditLogger._redact_value(v)
        return redacted

    @staticmethod
    def _redact_value(v: Any) -> Any:
        """Recursively redact a value; dicts are handled at any list depth (M1)."""
        if isinstance(v, dict):
            return AuditLogger._redact_sensitive(v)
        if isinstance(v, str):
            return AuditLogger._redact_sensitive_values(v)
        if isinstance(v, (list, tuple)):
            return [AuditLogger._redact_value(item) for item in v]
        return v

    @property
    def dropped_entries(self) -> int:
        """Alias for ``dropped_audit_entries`` (M2)."""
        return self.dropped_audit_entries

    @property
    def dropped_count(self) -> int:
        """Alias for ``dropped_audit_entries`` (M2)."""
        return self.dropped_audit_entries

    @property
    def drop_count(self) -> int:
        """Alias for ``dropped_audit_entries`` (M2)."""
        return self.dropped_audit_entries

    @property
    def write_failure_count(self) -> int:
        """Alias for ``failed_audit_writes`` (M2)."""
        return self.failed_audit_writes

    @property
    def write_failures(self) -> int:
        """Alias for ``failed_audit_writes`` (M2)."""
        return self.failed_audit_writes

    def _record_drop(self, entry: Dict[str, Any]) -> None:
        with self._drop_lock:
            self.dropped_audit_entries += 1
            self._unreported_drops += 1
            count = self.dropped_audit_entries
        logging.getLogger(__name__).warning(
            "AuditLogger dropped audit entry (queue full): "
            "dropped_audit_entries=%d action=%s",
            count,
            entry.get("action") if isinstance(entry, dict) else None,
        )

    def _record_write_failure(self, entry: Any) -> None:
        with self._drop_lock:
            self.failed_audit_writes += 1
            count = self.failed_audit_writes
        logging.getLogger(__name__).error(
            "AuditLogger failed to write audit entry: "
            "failed_audit_writes=%d action=%s",
            count,
            entry.get("action") if isinstance(entry, dict) else None,
            exc_info=True,
        )

    def _write_drop_marker_if_needed(self) -> None:
        """Write a chained AUDIT_ENTRIES_DROPPED marker for unreported drops (M2)."""
        with self._drop_lock:
            pending = self._unreported_drops
        if not pending:
            return
        marker = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session": self.session_name,
            "correlation_id": self.correlation_id,
            "action": "AUDIT_ENTRIES_DROPPED",
            "level": "error",
            "details": {"dropped_count": pending},
        }
        try:
            self._write_audit_line(marker)
        except Exception:
            self._record_write_failure(marker)
            return
        with self._drop_lock:
            self._unreported_drops = max(0, self._unreported_drops - pending)

    def _write_entry_counted(self, entry: Any) -> None:
        """Write one entry, flushing any pending drop marker first (M2)."""
        self._write_drop_marker_if_needed()
        try:
            self._write_audit_line(entry)
        except Exception:
            self._record_write_failure(entry)

    def log_action(
        self, action: str, details: Optional[Dict] = None, level: str = "info"
    ):
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
            "level": level,
            "details": safe_details,
        }

        # Queue the audit JSONL entry (drained by background thread; never blocks caller)
        try:
            self._audit_queue.put_nowait(entry)
        except queue.Full:
            # Extremely high volume: drop (never block hot path or OOM), but
            # never silently (M2): count it and log at drop time.
            self._record_drop(entry)

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
        self.log_action(action, {"error": error, **(details or {})}, level="error")

    def log_block_detected(self, platform: str, details: Optional[Dict] = None):
        """Special logging for blocks / rate limits"""
        self.log_action(
            "BLOCK_DETECTED", {"platform": platform, **(details or {})}, level="warning"
        )

    def get_recent_actions(
        self,
        limit: Optional[int] = 50,
        since_ts: Optional[str] = None,
        before_ts: Optional[str] = None,
    ) -> list:
        """Read recent audit entries (sync read is acceptable; only called from debug/report paths)

        Supports optional time filtering for pagination (#381):
        - since_ts: only entries with timestamp >= since_ts (ISO strings are comparable)
        - before_ts: only entries with timestamp < before_ts (used when cursor provided for older pages)
        After any filter, returns the most recent 'limit' of the matching entries (chronological order).
        L1: limit=0 returns []; a negative limit raises ValueError;
        limit=None returns all matching entries.
        """
        if limit is not None and limit < 0:
            raise ValueError("limit must be non-negative or None")
        if limit == 0:
            return []
        if not self.audit_file.exists():
            return []

        entries = []
        with open(self.audit_file) as f:
            for line in f:
                if line.strip():
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        logging.getLogger(__name__).debug(
                            "suppressed exception", exc_info=True
                        )  # tolerate corrupt lines

        if since_ts or before_ts:
            filtered = []
            for e in entries:
                ts = str(e.get("timestamp", ""))
                if since_ts and ts < since_ts:
                    continue
                if before_ts and ts >= before_ts:
                    continue
                filtered.append(e)
            entries = filtered

        if limit is None:
            return entries
        return entries[-limit:]

    def replay_sequence(
        self,
        limit: int = 30,
        cursor: Optional[str] = None,
        since_ts: Optional[str] = None,
    ) -> list:
        """#253 lightweight replay from audit logs. Extended for #381 cursor/since_ts pagination (minimal keyset on timestamp)."""
        if not self.audit_file.exists():
            return []
        before_ts = cursor if cursor else None
        fetch_n = (limit * 5) if (cursor or since_ts) else (limit * 3)
        entries = self.get_recent_actions(
            fetch_n, since_ts=since_ts, before_ts=before_ts
        )
        seq = []
        for e in entries:
            a = str(e.get("action", "")).lower()
            if any(
                k in a for k in ("click", "type", "goto", "submit", "think", "safe")
            ):
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
                    self._write_entry_counted(entry)  # never crashes; counts failures (M2)
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
                    if entry is not None:
                        self._write_entry_counted(entry)
                finally:
                    self._audit_queue.task_done()
        except queue.Empty:
            logging.getLogger(__name__).debug("suppressed exception", exc_info=True)
        # Record any drops that no later entry triggered a marker for (M2).
        try:
            self._write_drop_marker_if_needed()
        except Exception:
            logging.getLogger(__name__).debug("suppressed exception", exc_info=True)

    def _purge_old_logs(self) -> None:
        """Retention: delete log files for this session older than AGENTIC_AUDIT_RETENTION_DAYS."""
        try:
            days = int(os.getenv("AGENTIC_AUDIT_RETENTION_DAYS", "30"))
            if days <= 0:
                return
            cutoff = datetime.now(timezone.utc).timestamp() - (days * 86400)
            # L2: never purge this logger's own live files; unlinking the
            # just-opened .log would send writes to an unlinked inode.
            own_files = {
                os.path.abspath(str(self.log_file)),
                os.path.abspath(str(self.audit_file)),
                os.path.abspath(str(self._debug_log_file)),
            }
            for p in self.log_dir.glob(f"{self.session_name}*"):
                try:
                    if os.path.abspath(str(p)) in own_files:
                        continue
                    if p.is_file() and p.stat().st_mtime < cutoff:
                        p.unlink()
                except Exception:
                    logging.getLogger(__name__).debug(
                        "suppressed exception", exc_info=True
                    )
        except Exception:
            logging.getLogger(__name__).debug("suppressed exception", exc_info=True)

    def _rotate_jsonl(self) -> None:
        """Rotate self.audit_file into numbered backups (audit_file.1, .2, ...)."""
        backup = int(os.getenv("AGENTIC_AUDIT_BACKUP_COUNT", "5"))
        for i in range(backup - 1, 0, -1):
            src = Path(f"{self.audit_file}.{i}")
            dst = Path(f"{self.audit_file}.{i + 1}")
            if src.exists():
                os.replace(src, dst)
        if self.audit_file.exists():
            os.replace(self.audit_file, Path(f"{self.audit_file}.1"))

    def _read_last_hash(self) -> str:
        genesis = "0" * 64
        if not self.audit_file.exists():
            return genesis
        last = None
        try:
            with open(self.audit_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        last = line
        except Exception:
            return genesis
        if not last:
            return genesis
        try:
            return json.loads(last).get("entry_hash", genesis)
        except Exception:
            return genesis

    def _audit_file_signature(self) -> Optional[tuple]:
        try:
            st = self.audit_file.stat()
            return (st.st_size, st.st_mtime_ns)
        except (FileNotFoundError, OSError):
            return None

    def _write_audit_line(self, entry) -> None:
        # M5: serialize same-file writers in this process and re-read the
        # tail hash whenever the file changed since this instance last wrote.
        with self._audit_file_lock:
            key = os.getenv("AGENTIC_AUDIT_HMAC_KEY", "").encode("utf-8")
            if not key and not self._hmac_key_warned:
                # M4: never silent about the forgeable empty-key chain.
                self._hmac_key_warned = True
                logging.getLogger(__name__).warning(_NO_HMAC_KEY_MSG)
            rotated = False
            try:
                max_bytes = int(
                    os.getenv("AGENTIC_AUDIT_MAX_BYTES", str(10 * 1024 * 1024))
                )
                if (
                    self.audit_file.exists()
                    and self.audit_file.stat().st_size >= max_bytes
                ):
                    self._rotate_jsonl()
                    self._prev_hash = "0" * 64
                    rotated = True
            except Exception:
                logging.getLogger(__name__).debug(
                    "suppressed exception", exc_info=True
                )
            if rotated:
                prev = "0" * 64
            elif (
                self._prev_hash is None
                or self._audit_file_signature() != self._audit_tail_signature
            ):
                prev = self._read_last_hash()
                self._prev_hash = prev
            else:
                prev = self._prev_hash
            canonical = json.dumps(entry, sort_keys=True, ensure_ascii=False)
            entry_hash = hmac.new(
                key, (prev + canonical).encode("utf-8"), hashlib.sha256
            ).hexdigest()
            chained = {**entry, "prev_hash": prev, "entry_hash": entry_hash}
            with open(self.audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(chained, ensure_ascii=False) + "\n")
            self._prev_hash = entry_hash
            self._audit_tail_signature = self._audit_file_signature()

    def close(self) -> None:
        """Graceful shutdown of background writers and listeners (call from cleanup paths)."""
        try:
            self._shutdown.set()
            # Stop the stdlib queue listener (flushes its handler)
            if hasattr(self, "_listener") and self._listener:
                try:
                    self._listener.stop()
                except Exception:
                    logging.getLogger(__name__).debug(
                        "suppressed exception", exc_info=True
                    )
            # L3: wait until the writer has drained the queue (its shutdown
            # flush runs before the thread exits); no fixed time cap.
            if hasattr(self, "_writer_thread") and self._writer_thread.is_alive():
                self._writer_thread.join()
        except Exception:
            logging.getLogger(__name__).debug("suppressed exception", exc_info=True)

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
            logging.getLogger(__name__).debug("suppressed exception", exc_info=True)


class DebugReporter:
    """
    DX helper (#265) that captures and reports the exact stealth configuration
    applied to a browser instance: TLS fingerprint, headers, and applied patches.

    Allows operators to verify "what actually ran" for a given launch/preset.
    Safe no-op when debug=False; fully populated when debug=True or on explicit debug_report().
    """

    def __init__(
        self,
        logger: Optional[AuditLogger] = None,
        tls_manager=None,
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        self.logger = logger
        self.tls_manager = tls_manager
        self.extra_headers = extra_headers or {}
        self.patches: Dict[str, Any] = {}
        self.records: list = []

    def record_patch(self, name: str, data: Dict[str, Any]):
        """Record a stealth patch application for later reporting."""
        self.patches[name] = data
        self.records.append(
            {
                "type": "patch",
                "name": name,
                "data": data,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )

    def dump_fingerprint(self) -> Dict[str, Any]:
        """Return the TLS / fingerprint profile chosen for this session."""
        if self.tls_manager and hasattr(self.tls_manager, "get_profile"):
            try:
                return self.tls_manager.get_profile()
            except Exception:
                logging.getLogger(__name__).debug("suppressed exception", exc_info=True)
        if self.tls_manager and hasattr(self.tls_manager, "region"):
            return {
                "region": getattr(self.tls_manager, "region", "global"),
                "note": "partial profile",
            }
        return {
            "region": "global",
            "note": "default (no tls_manager available at report time)",
        }

    def dump_headers(self) -> Dict[str, Any]:
        """Return the extra HTTP headers that were applied."""
        return (
            dict(self.extra_headers)
            if self.extra_headers
            else {"note": "headers not captured"}
        )

    def dump_patches(self) -> Dict[str, Any]:
        """Return all recorded stealth patches."""
        return dict(self.patches)

    def full_debug_report(
        self,
        include_recent_logs: bool = True,
        recent_limit: Optional[int] = None,
        cursor: Optional[str] = None,
        since_ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Produce a comprehensive debug bundle for the current browser state.
        #381: recent_limit/cursor/since_ts control the recent_audit list via get_recent_actions (pagination support).
        """
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tls_fingerprint": self.dump_fingerprint(),
            "http_headers": self.dump_headers(),
            "stealth_patches": self.dump_patches(),
            "patch_count": len(self.patches),
        }
        if include_recent_logs and self.logger:
            try:
                rlimit = recent_limit if recent_limit is not None else 15
                before = cursor
                report["recent_audit"] = self.logger.get_recent_actions(
                    rlimit, since_ts=since_ts, before_ts=before
                )
            except Exception:
                report["recent_audit"] = ["<error reading audit>"]
        return report

    def print_human_report(self, report: Optional[Dict[str, Any]] = None):
        """Pretty(ish) console dump of the debug report. Redacts sensitive data before printing."""
        if report is None:
            report = self.full_debug_report()
        safe_report = (
            AuditLogger._redact_sensitive(report)
            if isinstance(report, dict)
            else report
        )
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


# ponytail: HMAC-keyed chain (env AGENTIC_AUDIT_HMAC_KEY). Chain resets on rotation; cross-file continuity not verified.
def verify_audit_chain(audit_file: str) -> bool:
    import hmac as _hm
    import hashlib as _h
    import json as _j
    import os as _os
    from pathlib import Path as _P

    key = _os.getenv("AGENTIC_AUDIT_HMAC_KEY", "").encode("utf-8")
    if not key:
        # M4: never silent about the forgeable empty-key chain (once per call;
        # do not hard-fail keyless deployments).
        logging.getLogger(__name__).warning(_NO_HMAC_KEY_MSG)
    p = _P(audit_file)
    if not p.exists():
        # M3: a missing audit file is not a verified chain. An empty but
        # existing file still verifies (loop below finds no bad entries).
        return False
    prev = "0" * 64
    with open(p, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rec = _j.loads(line)
            except Exception:
                return False
            cp = rec.get("prev_hash")
            ch = rec.get("entry_hash")
            if cp is None or ch is None:
                return False
            base = {
                k: v for k, v in rec.items() if k not in ("prev_hash", "entry_hash")
            }
            canonical = _j.dumps(base, sort_keys=True, ensure_ascii=False)
            expected = _hm.new(
                key, (cp + canonical).encode("utf-8"), _h.sha256
            ).hexdigest()
            if cp != prev or ch != expected:
                return False
            prev = ch
    return True
