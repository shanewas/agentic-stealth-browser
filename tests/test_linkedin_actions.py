"""
Tests for LinkedIn-specific actions.
Addresses #168: LinkedIn-specific actions support.
"""

import pytest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class MockPage:
    """Mock Playwright Page for testing."""

    def __init__(self):
        self._url = "https://linkedin.com"
        self._calls = []
        class Mouse:
            async def move(self, x, y): pass
            async def wheel(self, dx, dy): pass
        class Keyboard:
            async def press(self, k): pass
            async def type(self, t, **kw): pass
        self.mouse = Mouse()
        self.keyboard = Keyboard()

    @property
    def url(self):
        return self._url

    async def goto(self, url, **kwargs):
        self._calls.append(("goto", url))
        self._url = url

    async def query_selector(self, selector):
        self._calls.append(("query_selector", selector))
        return None

    async def evaluate(self, js):
        self._calls.append(("evaluate",))
        return []


class MockHuman:
    """Mock human behavior for testing."""

    def __init__(self):
        self._calls = []

    async def scroll_naturally(self, pixels):
        self._calls.append(("scroll", pixels))

    async def think(self, min_ms, max_ms):
        self._calls.append(("think", min_ms, max_ms))

    async def human_click(self, selector):
        self._calls.append(("click", selector))

    async def type_like_human(self, selector, text):
        self._calls.append(("type", selector, text))


class TestLinkedInActions:
    """LinkedIn actions tests."""

    def _make_actions(self):
        from linkedin.actions import LinkedInActions
        page = MockPage()
        human = MockHuman()
        return LinkedInActions(page, human)

    def test_view_profile_navigates_to_profile(self):
        li = self._make_actions()
        import asyncio
        asyncio.run(
            li.view_profile("testuser", duration_seconds=0.1)
        )
        # Should have navigated to profile
        calls = li.page._calls
        goto_calls = [c for c in calls if c[0] == "goto"]
        assert any("testuser" in str(c) for c in goto_calls)

    def test_search_jobs_returns_list(self):
        li = self._make_actions()
        import asyncio
        results = asyncio.run(
            li.search_jobs("python", max_pages=1)
        )
        assert isinstance(results, list)

    def test_post_update_returns_boolean(self):
        li = self._make_actions()
        import asyncio
        result = asyncio.run(
            li.post_update("Test post")
        )
        assert isinstance(result, bool)

    def test_send_connection_request_returns_boolean(self):
        li = self._make_actions()
        import asyncio
        result = asyncio.run(
            li.send_connection_request("testuser")
        )
        assert isinstance(result, bool)

    def test_endorse_skill_returns_boolean(self):
        li = self._make_actions()
        import asyncio
        result = asyncio.run(
            li.endorse_skill("testuser", "Python")
        )
        assert isinstance(result, bool)
