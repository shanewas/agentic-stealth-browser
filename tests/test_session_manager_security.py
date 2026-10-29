"""Path-traversal tests for session names and screenshot names."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sessions.session_manager import SessionManager

BAD_NAMES = [
    "../x",
    "..\\x",
    "/abs",
    "a/b",
    "a\\b",
    "",
    "   ",
    "..",
    ".",
    "bad\nname",
    "C:\\evil",
]


class TestSessionNameTraversal:
    def test_create_session_rejects_traversal_without_creating(self, tmp_path):
        manager = SessionManager(base_dir=str(tmp_path))
        for name in BAD_NAMES:
            with pytest.raises(ValueError):
                manager.create_session(name)
        assert list(tmp_path.iterdir()) == []

    def test_load_cleanup_clone_reject_traversal(self, tmp_path):
        manager = SessionManager(base_dir=str(tmp_path))
        manager.create_session("victim")
        for name in BAD_NAMES:
            with pytest.raises(ValueError):
                manager.get_session(name)
            with pytest.raises(ValueError):
                manager.cleanup_session(name, remove_dir=True)
            with pytest.raises(ValueError):
                manager.clone_session(name, "clone-ok")
            with pytest.raises(ValueError):
                manager.clone_session("victim", name)
        # Victim session untouched, nothing created outside or extra inside.
        assert (tmp_path / "victim" / "meta.json").exists()
        assert [p.name for p in tmp_path.iterdir()] == ["victim"]

    def test_normal_session_names_keep_working(self, tmp_path):
        manager = SessionManager(base_dir=str(tmp_path))
        meta = manager.create_session("linkedin-alice")
        assert meta["name"] == "linkedin-alice"
        assert manager.get_session("linkedin-alice")["name"] == "linkedin-alice"
        assert len(manager.list_sessions()) == 1
        cloned = manager.clone_session("linkedin-alice", "linkedin-alice-b")
        assert cloned["status"] == "success"
        assert manager.cleanup_session("linkedin-alice")["status"] == (
            "marked_compromised"
        )

    def test_agent_browser_rejects_traversal_session_name(
        self, tmp_path, monkeypatch
    ):
        import core.agent_browser as agent_browser_module

        monkeypatch.setattr(
            agent_browser_module,
            "SessionManager",
            lambda: SessionManager(base_dir=str(tmp_path)),
        )
        with pytest.raises(ValueError):
            agent_browser_module.AgentBrowser(session_name="../victim")
        assert list(tmp_path.iterdir()) == []


class TestCloneSessionMeta:
    def test_clone_meta_points_at_clone_and_state_copied(self, tmp_path):
        manager = SessionManager(base_dir=str(tmp_path))
        manager.create_session("source-a")
        (tmp_path / "source-a" / "cookies.json").write_text('[{"name": "c"}]')
        (tmp_path / "source-a" / "state.json").write_text('{"k": 1}')

        result = manager.clone_session("source-a", "clone-b")

        assert result["status"] == "success"
        clone_meta = manager.get_session("clone-b")
        assert clone_meta["name"] == "clone-b"
        assert clone_meta["user_data_dir"] == str(tmp_path / "clone-b" / "user_data")
        assert clone_meta["cookies_file"] == str(tmp_path / "clone-b" / "cookies.json")
        assert clone_meta["state_file"] == str(tmp_path / "clone-b" / "state.json")
        assert clone_meta["cloned_from"] == "source-a"
        assert json.loads((tmp_path / "clone-b" / "cookies.json").read_text()) == [
            {"name": "c"}
        ]
        assert json.loads((tmp_path / "clone-b" / "state.json").read_text()) == {"k": 1}
        # Source untouched.
        assert manager.get_session("source-a")["name"] == "source-a"


class TestCompromisedQuarantine:
    def test_mark_compromised_corrupt_meta_reports_non_success(self, tmp_path):
        manager = SessionManager(base_dir=str(tmp_path))
        manager.create_session("victim-a")
        (tmp_path / "victim-a" / "meta.json").write_text("{not json")

        result = manager.cleanup_session("victim-a")

        assert result["status"] != "marked_compromised"
        assert result["status"] in ("error", "partial")
        assert result["marked"] is False

    def test_mark_compromised_missing_meta_reports_non_success(self, tmp_path):
        manager = SessionManager(base_dir=str(tmp_path))
        manager.create_session("victim-b")
        (tmp_path / "victim-b" / "meta.json").unlink()

        result = manager.cleanup_session("victim-b")

        assert result["status"] != "marked_compromised"
        assert result["marked"] is False

    def test_recreate_compromised_session_preserves_flag(self, tmp_path):
        manager = SessionManager(base_dir=str(tmp_path))
        manager.create_session("victim-c")
        (tmp_path / "victim-c" / "cookies.json").write_text('[{"name": "keep"}]')
        assert manager.cleanup_session("victim-c")["status"] == "marked_compromised"
        assert manager.get_session("victim-c")["compromised"] is True

        # Preserve-flag choice: re-create must not clear quarantine, and
        # (matching that choice) existing cookies are left in place.
        manager.create_session("victim-c")

        assert manager.get_session("victim-c")["compromised"] is True
        assert json.loads((tmp_path / "victim-c" / "cookies.json").read_text()) == [
            {"name": "keep"}
        ]


class TestPruneEphemeral:
    def test_corrupt_created_at_survives_age_prune_and_is_reported(self, tmp_path):
        manager = SessionManager(base_dir=str(tmp_path))
        meta = manager.create_session("throwaway", ephemeral=True)
        name = meta["name"]
        meta_file = tmp_path / name / "meta.json"
        stored = json.loads(meta_file.read_text())
        stored["created_at"] = "not-a-date"
        meta_file.write_text(json.dumps(stored))

        result = manager.prune_ephemeral(max_age_hours=1)

        assert (tmp_path / name).exists()
        assert result["removed"] == 0
        assert result["errors"] >= 1
        assert name in result["skipped"]


class _FakePage:
    def __init__(self):
        self.screenshot_calls = []

    async def screenshot(self, path, full_page=False):
        self.screenshot_calls.append(path)
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"png")


class TestScreenshotOnErrorTraversal:
    def _browser(self, page):
        from core.agent_browser import AgentBrowser

        browser = object.__new__(AgentBrowser)
        browser._rate_limiter = None
        browser._page_getter = None
        browser.page = page
        browser.logger = None
        return browser

    @pytest.mark.parametrize(
        "name", ["../../evil", "../evil", "a/b/c", "..\\evil", "/abs/evil"]
    )
    def test_traversal_name_contained_under_screenshots(
        self, tmp_path, monkeypatch, name
    ):
        monkeypatch.chdir(tmp_path)
        page = _FakePage()
        browser = self._browser(page)
        result = asyncio.run(browser.screenshot_on_error(name))
        assert result is not None
        assert page.screenshot_calls == [result]
        result_path = Path(result)
        assert ".." not in result_path.parts
        assert result_path.parent == Path("screenshots")
        resolved = (tmp_path / result_path).resolve()
        assert resolved.is_relative_to((tmp_path / "screenshots").resolve())
        assert resolved.exists()
        assert not (tmp_path / "evil.png").exists()

    def test_normal_screenshot_name_keeps_working(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        page = _FakePage()
        browser = self._browser(page)
        result = asyncio.run(browser.screenshot_on_error("dashboard"))
        assert result is not None
        assert Path(result).parent == Path("screenshots")
        assert Path(result).name.startswith("dashboard_")
        assert (tmp_path / result).exists()
