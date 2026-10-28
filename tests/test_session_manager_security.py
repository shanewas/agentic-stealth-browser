"""Path-traversal tests for session names and screenshot names."""

import asyncio
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
