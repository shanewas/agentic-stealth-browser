"""
Tests for Session Checkpoint & Export.
Addresses #62: Session checkpoint/export for resumption across hosts or restarts.
"""

import pytest
import time
import json
import base64
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.session_checkpoint import (
    SessionCheckpoint,
    CheckpointMetadata,
    SessionManager,
)


class MockPage:
    """Mock Playwright Page for testing."""

    def __init__(self):
        self._url = "https://example.com"
        self._title = "Example"
        self._cookies = [{"name": "session", "value": "abc123", "domain": "example.com"}]
        self._local_storage = {"key1": "value1", "key2": "value2"}
        self._session_storage = {"temp": "data"}
        self._calls = []

    class MockContext:
        def __init__(self, cookies):
            self._cookies = cookies
            self._added_cookies = []

        async def cookies(self):
            return self._cookies

        async def add_cookies(self, cookies):
            self._added_cookies = cookies

    def __init__(self):
        self._url = "https://example.com"
        self._title = "Example"
        self._cookies = [{"name": "session", "value": "abc123", "domain": "example.com"}]
        self._local_storage = {"key1": "value1", "key2": "value2"}
        self._session_storage = {"temp": "data"}
        self._calls = []
        self.context = self.MockContext(self._cookies)

    @property
    def url(self):
        return self._url

    async def title(self):
        return self._title

    async def goto(self, url):
        self._calls.append(("goto", url))
        self._url = url

    async def evaluate(self, js):
        self._calls.append(("evaluate", js))
        if "localStorage" in js:
            return self._local_storage
        if "sessionStorage" in js:
            return self._session_storage
        return {}


class TestCheckpointMetadata:
    """Metadata serialization tests."""

    def test_to_dict_contains_all_fields(self):
        meta = CheckpointMetadata(
            account_id="test",
            session_id="sess1",
            page_url="https://example.com",
            mouse_position=(100, 200),
        )
        d = meta.to_dict()
        assert d["account_id"] == "test"
        assert d["session_id"] == "sess1"
        assert d["page_url"] == "https://example.com"
        assert d["mouse_position"] == [100, 200]

    def test_round_trip(self):
        meta = CheckpointMetadata(
            account_id="test",
            session_id="sess1",
            page_url="https://example.com",
            mouse_position=(100, 200),
            total_actions=42,
        )
        restored = CheckpointMetadata.from_dict(meta.to_dict())
        assert restored.account_id == meta.account_id
        assert restored.session_id == meta.session_id
        assert restored.mouse_position == meta.mouse_position
        assert restored.total_actions == meta.total_actions


class TestSessionCheckpoint:
    """Checkpoint serialization tests."""

    def test_to_dict_contains_all_sections(self):
        cp = SessionCheckpoint(
            metadata=CheckpointMetadata(account_id="test"),
            cookies=[{"name": "session", "value": "abc"}],
            local_storage={"key": "value"},
            health_state={"score": 0.8},
        )
        d = cp.to_dict()
        assert "metadata" in d
        assert "cookies" in d
        assert "local_storage" in d
        assert "health_state" in d

    def test_json_round_trip(self):
        cp = SessionCheckpoint(
            metadata=CheckpointMetadata(account_id="test", session_id="sess1"),
            cookies=[{"name": "session", "value": "abc"}],
            local_storage={"key": "value"},
            custom_data={"custom": "data"},
        )
        json_str = cp.to_json()
        restored = SessionCheckpoint.from_json(json_str)
        assert restored.metadata.account_id == "test"
        assert restored.metadata.session_id == "sess1"
        assert len(restored.cookies) == 1
        assert restored.local_storage == {"key": "value"}

    def test_checksum_is_deterministic(self):
        cp = SessionCheckpoint(
            metadata=CheckpointMetadata(account_id="test"),
            cookies=[{"name": "session", "value": "abc"}],
        )
        checksum1 = cp.checksum()
        checksum2 = cp.checksum()
        assert checksum1 == checksum2

    def test_checksum_changes_with_content(self):
        cp1 = SessionCheckpoint(
            metadata=CheckpointMetadata(account_id="test1"),
        )
        cp2 = SessionCheckpoint(
            metadata=CheckpointMetadata(account_id="test2"),
        )
        assert cp1.checksum() != cp2.checksum()


class TestSessionManager:
    """Session manager tests."""

    def test_create_checkpoint(self, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        cp = manager.create_checkpoint(
            account_id="test",
            cookies=[{"name": "session", "value": "abc"}],
            local_storage={"key": "value"},
        )
        assert cp.metadata.account_id == "test"
        assert len(cp.cookies) == 1
        assert cp.local_storage == {"key": "value"}

    def test_save_and_load_checkpoint(self, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        cp = manager.create_checkpoint(
            account_id="test",
            session_id="sess1",
            cookies=[{"name": "session", "value": "abc"}],
        )
        filepath = manager.save_checkpoint(cp)
        assert filepath.exists()

        loaded = manager.load_checkpoint(filepath.name)
        assert loaded.metadata.account_id == "test"
        assert loaded.metadata.session_id == "sess1"

    def test_latest_checkpoint(self, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        cp1 = manager.create_checkpoint(account_id="test")
        manager.save_checkpoint(cp1)

        cp2 = manager.create_checkpoint(account_id="test")
        manager.save_checkpoint(cp2)

        latest = manager.load_latest("test")
        assert latest is not None
        assert latest.metadata.account_id == "test"

    def test_list_checkpoints(self, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        cp1 = manager.create_checkpoint(account_id="user1")
        cp2 = manager.create_checkpoint(account_id="user1")
        cp3 = manager.create_checkpoint(account_id="user2")
        manager.save_checkpoint(cp1)
        manager.save_checkpoint(cp2)
        manager.save_checkpoint(cp3)

        user1_cps = manager.list_checkpoints("user1")
        assert len(user1_cps) >= 2  # At least 2 + _latest

        all_cps = manager.list_checkpoints()
        assert len(all_cps) >= 3

    def test_delete_checkpoint(self, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        cp = manager.create_checkpoint(account_id="test")
        filepath = manager.save_checkpoint(cp)

        manager.delete_checkpoint(filepath.name)
        assert not filepath.exists()

    def test_cleanup_old_checkpoints(self, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        # Create 10 checkpoints
        for i in range(10):
            cp = manager.create_checkpoint(account_id="test")
            cp.metadata.created_at = time.time() + i  # Ensure unique timestamps
            manager.save_checkpoint(cp, filename=f"test_{i}.json")

        manager.cleanup_old_checkpoints("test", keep=3)
        remaining = manager.list_checkpoints("test")
        # Should have 3 + _latest.json
        assert len(remaining) <= 4


class TestSessionManagerBrowser:
    """Browser integration tests."""

    @pytest.mark.asyncio
    def test_capture_from_browser(self, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        page = MockPage()

        import asyncio
        cp = asyncio.run(
            manager.capture_from_browser(page, account_id="test")
        )

        assert cp.metadata.account_id == "test"
        assert len(cp.cookies) == 1
        assert cp.local_storage == {"key1": "value1", "key2": "value2"}

    @pytest.mark.asyncio
    def test_restore_to_browser(self, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        page = MockPage()

        cp = SessionCheckpoint(
            metadata=CheckpointMetadata(
                account_id="test",
                page_url="https://restored.com",
            ),
            cookies=[{"name": "restored", "value": "xyz", "domain": "restored.com"}],
            local_storage={"restored": "true"},
        )

        import asyncio
        asyncio.run(
            manager.restore_to_browser(page, cp)
        )

        # Check that goto was called
        assert any(call[0] == "goto" for call in page._calls)

    @pytest.mark.asyncio
    def test_restore_cookies(self, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        page = MockPage()

        cookies = [{"name": "test", "value": "cookie", "domain": "example.com"}]
        import asyncio
        asyncio.run(
            manager.restore_cookies(page, cookies)
        )

        assert len(page.context._added_cookies) == 1


class TestSessionManagerTransfer:
    """Cross-host transfer tests."""

    def test_export_for_transfer(self, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        cp = manager.create_checkpoint(
            account_id="test",
            cookies=[{"name": "session", "value": "abc"}],
        )

        encoded = manager.export_for_transfer(cp)
        # Should be valid base64
        decoded = base64.b64decode(encoded)
        assert b'"account_id": "test"' in decoded

    def test_import_from_transfer(self, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        cp = manager.create_checkpoint(
            account_id="test",
            session_id="sess1",
            cookies=[{"name": "session", "value": "abc"}],
        )

        encoded = manager.export_for_transfer(cp)
        imported = manager.import_from_transfer(encoded)

        assert imported.metadata.account_id == "test"
        assert imported.metadata.session_id == "sess1"
        assert len(imported.cookies) == 1

    def test_round_trip_transfer(self, tmp_path):
        manager = SessionManager(data_dir=str(tmp_path))
        original = manager.create_checkpoint(
            account_id="test",
            cookies=[{"name": "session", "value": "abc"}],
            local_storage={"key": "value"},
            health_state={"score": 0.8},
            custom_data={"data": "value"},
        )

        encoded = manager.export_for_transfer(original)
        restored = manager.import_from_transfer(encoded)

        assert restored.metadata.account_id == original.metadata.account_id
        assert restored.cookies == original.cookies
        assert restored.local_storage == original.local_storage
        assert restored.health_state == original.health_state
        assert restored.custom_data == original.custom_data
