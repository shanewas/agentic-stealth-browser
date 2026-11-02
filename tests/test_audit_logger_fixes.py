"""
Regression tests for the audit/logger.py audit fixes (M1-M6, L1-L3).

Mirrors the style of tests/test_proxy_audit_fixes.py: pure logic,
tmp dirs only, no browser, no network.
"""

import json
import logging
import os
import queue
import sys
import threading
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from audit.logger import AuditLogger, verify_audit_chain

SLACK_TOKEN = "xoxb-EXAMPLE-TOKEN-0000000000"  # fake fixture; realistic shapes trip push protection
SLACK_TOKEN_P = "xoxp-EXAMPLE-TOKEN-0000000000"
JWT_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ."
    "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
)
GITHUB_PAT = "github_pat_EXAMPLE_TOKEN_000000000000"


def _make_logger(tmp_path, name="sess-a"):
    return AuditLogger(name, log_dir=str(tmp_path))


def _read_entries(audit_file):
    return [
        json.loads(line)
        for line in Path(audit_file).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class TestRedactionTokenClasses:
    """M1: advertised token classes, singular credential key, deep lists."""

    @pytest.mark.parametrize(
        "token", [SLACK_TOKEN, SLACK_TOKEN_P, JWT_TOKEN, GITHUB_PAT]
    )
    def test_new_token_classes_redacted(self, token):
        out = AuditLogger._redact_sensitive({"note": f"leaked {token} here"})
        assert token not in out["note"]
        assert "[REDACTED_KEY]" in out["note"]

    def test_existing_token_classes_still_redacted(self):
        out = AuditLogger._redact_sensitive_values(
            "ghp_" + "A" * 30 + " and sk-" + "B" * 30
        )
        assert "ghp_" not in out
        assert "sk-" + "B" * 30 not in out

    def test_singular_credential_key_redacted(self):
        out = AuditLogger._redact_sensitive(
            {"credential": "hunter2", "my_credential": "hunter2"}
        )
        assert out["credential"] == "***REDACTED***"
        assert out["my_credential"] == "***REDACTED***"

    def test_dict_in_list_of_lists_redacted(self):
        out = AuditLogger._redact_sensitive(
            {"items": [[{"note": SLACK_TOKEN}], [{"api_key": "abc123"}]]}
        )
        assert SLACK_TOKEN not in str(out)
        assert out["items"][0][0]["note"] == "[REDACTED_KEY]"
        assert out["items"][1][0]["api_key"] == "***REDACTED***"

    def test_ordinary_values_untouched(self):
        details = {"note": "hello world", "items": [[{"note": "plain text"}]], "n": 3}
        assert AuditLogger._redact_sensitive(details) == details


class TestDroppedEntriesDetectable:
    """M2: queue-full drops are counted, logged, and marked in the chain."""

    def test_drop_is_counted_and_logged(self, tmp_path, caplog):
        logger = _make_logger(tmp_path)
        entered = threading.Event()
        release = threading.Event()

        def blocked_writer(entry):
            entered.set()
            release.wait(timeout=5)

        try:
            logger._write_audit_line = blocked_writer
            logger._audit_queue = queue.Queue(maxsize=1)
            logger.log_action("first")
            assert entered.wait(timeout=5)
            logger.log_action("second")  # fills the tiny queue
            with caplog.at_level(logging.WARNING, logger="audit.logger"):
                logger.log_action("third")  # dropped: queue full
            assert logger.dropped_audit_entries >= 1
            assert logger.dropped_entries == logger.dropped_audit_entries
            assert "dropped" in caplog.text.lower()
        finally:
            release.set()
            logger.close()

    def test_drop_marker_written_before_next_entry(self, tmp_path):
        logger = _make_logger(tmp_path)
        try:
            logger.dropped_audit_entries = 2
            logger._unreported_drops = 2
            logger.log_action("after-drop")
        finally:
            logger.close()
        entries = _read_entries(logger.audit_file)
        actions = [e["action"] for e in entries]
        assert "AUDIT_ENTRIES_DROPPED" in actions
        marker = entries[actions.index("AUDIT_ENTRIES_DROPPED")]
        assert marker["details"]["dropped_count"] == 2
        assert actions.index("AUDIT_ENTRIES_DROPPED") < actions.index("after-drop")
        assert verify_audit_chain(str(logger.audit_file)) is True


class TestVerifyAuditChainMissingFile:
    """M3."""

    def test_missing_file_verifies_false(self, tmp_path):
        assert verify_audit_chain(str(tmp_path / "nope_audit.jsonl")) is False

    def test_empty_existing_file_keeps_verdict(self, tmp_path):
        empty = tmp_path / "empty_audit.jsonl"
        empty.write_text("", encoding="utf-8")
        assert verify_audit_chain(str(empty)) is True


class TestNoHmacKeyWarning:
    """M4: keyless chain warns, never hard-fails."""

    def test_writer_warns_when_key_unset(self, tmp_path, monkeypatch, caplog):
        monkeypatch.delenv("AGENTIC_AUDIT_HMAC_KEY", raising=False)
        logger = _make_logger(tmp_path)
        try:
            with caplog.at_level(logging.WARNING, logger="audit.logger"):
                logger.log_action("hello")
                logger.close()
            assert "AGENTIC_AUDIT_HMAC_KEY" in caplog.text
        finally:
            logger.close()

    def test_verifier_warns_when_key_unset(self, tmp_path, monkeypatch, caplog):
        monkeypatch.delenv("AGENTIC_AUDIT_HMAC_KEY", raising=False)
        logger = _make_logger(tmp_path)
        logger.log_action("hello")
        logger.close()
        caplog.clear()
        with caplog.at_level(logging.WARNING, logger="audit.logger"):
            assert verify_audit_chain(str(logger.audit_file)) is True
        assert "AGENTIC_AUDIT_HMAC_KEY" in caplog.text


class TestConcurrentSameNameLoggers:
    """M5: two live instances on one session keep one valid chain."""

    def test_alternating_writes_verify(self, tmp_path):
        first = _make_logger(tmp_path, name="shared-sess")
        second = _make_logger(tmp_path, name="shared-sess")
        try:
            for i in range(3):
                first.log_action(f"first-{i}")
                second.log_action(f"second-{i}")
        finally:
            first.close()
            second.close()
        entries = _read_entries(first.audit_file)
        assert len(entries) == 6
        assert verify_audit_chain(str(first.audit_file)) is True


class TestSessionNameValidation:
    """M6."""

    @pytest.mark.parametrize("bad", ["../outside", "a/b", "a\\b", "..", ""])
    def test_traversal_names_raise(self, tmp_path, bad):
        with pytest.raises(ValueError):
            AuditLogger(bad, log_dir=str(tmp_path))

    @pytest.mark.parametrize("good", ["sess-a", "linkedin_alice", "Session-1"])
    def test_normal_names_construct(self, tmp_path, good):
        logger = AuditLogger(good, log_dir=str(tmp_path))
        logger.close()


class TestGetRecentActionsLimits:
    """L1."""

    def test_zero_negative_and_normal_limits(self, tmp_path):
        logger = _make_logger(tmp_path)
        try:
            for i in range(3):
                logger.log_action(f"action-{i}")
        finally:
            logger.close()
        assert logger.get_recent_actions(limit=0) == []
        with pytest.raises(ValueError):
            logger.get_recent_actions(limit=-1)
        recent = logger.get_recent_actions(limit=2)
        assert [e["action"] for e in recent] == ["action-1", "action-2"]
        assert len(logger.get_recent_actions(limit=None)) == 3


class TestRetentionKeepsLiveFiles:
    """L2: purge must not unlink the just-opened session log."""

    def test_backdated_log_survives_reopen_and_receives_writes(self, tmp_path):
        logger = _make_logger(tmp_path, name="old-sess")
        logger.log_action("before")
        logger.close()

        old = time.time() - 40 * 86400
        for path in (logger.log_file, logger.audit_file):
            os.utime(path, (old, old))

        reopened = AuditLogger("old-sess", log_dir=str(tmp_path))
        try:
            assert reopened.log_file.exists()
            assert reopened.audit_file.exists()
            reopened.log_action("after-reopen")
        finally:
            reopened.close()
        assert reopened.log_file.exists()
        assert "after-reopen" in reopened.log_file.read_text(encoding="utf-8")


class TestCloseFlushesBacklog:
    """L3: close() returns only after pending entries are flushed."""

    def test_close_waits_for_slow_writer(self, tmp_path):
        logger = _make_logger(tmp_path)
        original = logger._write_audit_line

        def slow_writer(entry):
            time.sleep(0.05)
            original(entry)

        logger._write_audit_line = slow_writer
        try:
            for i in range(25):
                logger.log_action(f"bulk-{i}")
        finally:
            logger.close()
        entries = _read_entries(logger.audit_file)
        assert len(entries) == 25
        assert verify_audit_chain(str(logger.audit_file)) is True
