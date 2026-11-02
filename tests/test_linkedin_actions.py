"""
Tests for LinkedIn-specific actions.
Addresses #168: LinkedIn-specific actions support.
"""

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
            async def move(self, x, y):
                pass

            async def wheel(self, dx, dy):
                pass

        class Keyboard:
            async def press(self, k):
                pass

            async def type(self, t, **kw):
                pass

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

        asyncio.run(li.view_profile("testuser", duration_seconds=0.1))
        # Should have navigated to profile
        calls = li.page._calls
        goto_calls = [c for c in calls if c[0] == "goto"]
        assert any("testuser" in str(c) for c in goto_calls)

    def test_search_jobs_returns_list(self):
        li = self._make_actions()
        import asyncio

        results = asyncio.run(li.search_jobs("python", max_pages=1))
        assert isinstance(results, list)

    def test_post_update_returns_boolean(self):
        li = self._make_actions()
        import asyncio

        result = asyncio.run(li.post_update("Test post"))
        assert isinstance(result, bool)

    def test_send_connection_request_returns_boolean(self):
        li = self._make_actions()
        import asyncio

        result = asyncio.run(li.send_connection_request("testuser"))
        assert isinstance(result, bool)

    def test_endorse_skill_returns_boolean(self):
        li = self._make_actions()
        import asyncio

        result = asyncio.run(li.endorse_skill("testuser", "Python"))
        assert isinstance(result, bool)


class _RecordingPage(MockPage):
    """Fake page returning a handle for selected selectors and canned jobs."""

    def __init__(self, jobs=None, found_selectors=None):
        super().__init__()
        self._jobs = jobs or []
        self._found = found_selectors

    async def query_selector(self, selector):
        self._calls.append(("query_selector", selector))
        if self._found is None or selector in self._found:
            return object()
        return None

    async def evaluate(self, js):
        self._calls.append(("evaluate",))
        return list(self._jobs)


class TestLinkedInActionsEncoding:
    def _make(self, page=None):
        from linkedin.actions import LinkedInActions

        page = page or MockPage()
        human = MockHuman()
        return LinkedInActions(page, human)

    def _goto_urls(self, li):
        return [c[1] for c in li.page._calls if c[0] == "goto"]

    def test_view_profile_encodes_username_as_single_segment(self):
        import asyncio

        li = self._make()
        asyncio.run(li.view_profile("a/b?x=1&y=2#frag name", duration_seconds=0))
        (url,) = self._goto_urls(li)
        assert url == (
            "https://www.linkedin.com/in/a%2Fb%3Fx%3D1%26y%3D2%23frag%20name"
        )

    def test_search_jobs_encodes_query_params(self):
        import asyncio
        from urllib.parse import parse_qs, urlparse

        li = self._make()
        asyncio.run(
            li.search_jobs("python&f_TPR=r86400", location="New York &?", max_pages=1)
        )
        (url,) = self._goto_urls(li)
        parsed = urlparse(url)
        assert parsed.path == "/jobs/search/"
        params = parse_qs(parsed.query)
        assert params == {
            "keywords": ["python&f_TPR=r86400"],
            "location": ["New York &?"],
        }


class TestLinkedInActionsSelectors:
    def _make(self, page):
        from linkedin.actions import LinkedInActions

        human = MockHuman()
        return LinkedInActions(page, human), human

    def test_endorse_skill_clicks_skill_specific_selector(self):
        import asyncio

        page = _RecordingPage()
        li, human = self._make(page)
        result = asyncio.run(li.endorse_skill("testuser", "Python"))
        assert result is True
        expected = 'button[aria-label*="Python"]'
        queried = [c[1] for c in page._calls if c[0] == "query_selector"]
        clicked = [c[1] for c in human._calls if c[0] == "click"]
        assert queried == [expected]
        assert clicked == [expected]

    def test_endorse_skill_escapes_quote_in_skill(self):
        import asyncio

        page = _RecordingPage()
        li, human = self._make(page)
        result = asyncio.run(li.endorse_skill("testuser", 'Python "advanced"'))
        assert result is True
        clicked = [c[1] for c in human._calls if c[0] == "click"]
        assert clicked == ['button[aria-label*="Python \\"advanced\\""]']

    def test_send_connection_request_clicks_queried_selectors(self):
        import asyncio

        page = _RecordingPage()
        li, human = self._make(page)
        result = asyncio.run(li.send_connection_request("testuser"))
        assert result is True
        queried = [c[1] for c in page._calls if c[0] == "query_selector"]
        clicked = [c[1] for c in human._calls if c[0] == "click"]
        assert clicked == queried


class TestSearchJobsPagination:
    def _make(self, page):
        from linkedin.actions import LinkedInActions

        human = MockHuman()
        return LinkedInActions(page, human), human

    def test_single_page_results_not_duplicated(self):
        import asyncio

        jobs = [
            {"title": "A", "url": "https://www.linkedin.com/jobs/view/1"},
            {"title": "B", "url": "https://www.linkedin.com/jobs/view/2"},
        ]
        # MockPage.query_selector returns None: no Next control.
        page = _RecordingPage(jobs=jobs, found_selectors=set())
        li, _human = self._make(page)
        results = asyncio.run(li.search_jobs("python", max_pages=3))
        assert results == jobs
        assert len([c for c in page._calls if c[0] == "evaluate"]) == 1

    def test_repeated_page_results_deduplicated_by_url(self):
        import asyncio

        jobs = [{"title": "A", "url": "https://www.linkedin.com/jobs/view/1"}]
        # Next control exists, but evaluate keeps returning the same page.
        page = _RecordingPage(jobs=jobs)
        li, _human = self._make(page)
        results = asyncio.run(li.search_jobs("python", max_pages=3))
        assert results == jobs
