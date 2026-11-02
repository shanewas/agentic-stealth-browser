"""
Scraper recovery-wiring / failure / injection tests (S1-S5 audit fixes).

Style mirrors tests/test_integration_modules.py: small local fakes, no live
browser, asyncio.run() around async bodies.
"""

import asyncio
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.agent_browser import AgentBrowser
from production.sdk.client import StealthClient
from recovery.anti_block_orchestrator import MaxRetriesExceeded
from scraping.scraper import StealthScraper


class FakePage:
    def __init__(self, evaluate_result=None):
        self.goto_calls = []
        self.evaluate_calls = []
        self.evaluate_result = evaluate_result

    async def goto(self, url, **kwargs):
        self.goto_calls.append(url)
        return None

    async def evaluate(self, script, arg=None):
        self.evaluate_calls.append(script)
        return self.evaluate_result

    async def close(self):
        pass


class FakeContext:
    def __init__(self):
        self.pages = []

    async def close(self):
        pass

    async def new_page(self):
        page = FakePage()
        self.pages.append(page)
        return page


class FakeRecovery:
    """Recovery double that runs the nav func like the real orchestrator."""

    def __init__(self):
        self.calls = []

    async def execute_with_recovery(self, func, platform=None, url=None):
        self.calls.append({"platform": platform, "url": url})
        return await func()


class FailingRecovery:
    async def execute_with_recovery(self, func, platform=None, url=None):
        raise MaxRetriesExceeded(
            "blocked", platform=platform or "", max_retries=3, last_error="captcha"
        )


CONTENT = {
    "title": "Example Title",
    "url": "https://example.com/",
    "text": "hello body text",
    "headings": ["H1"],
}


# --- S1: AgentBrowser wires its recovery orchestrator into the scraper ---


class TestScraperRecoveryWiring:
    def test_switch_to_page_scraper_carries_recovery(self):
        async def _run():
            browser = AgentBrowser(session_name="scraper-wiring-test")
            ctx = FakeContext()
            page = FakePage()
            ctx.pages = [page]
            recovery = FakeRecovery()
            browser.browser = ctx
            browser.page = page
            browser.recovery = recovery

            assert await browser.switch_to_page(page) is True
            assert browser.scraper is not None
            assert browser.scraper.recovery is recovery
            assert browser.scraper.page is page
            await browser.close()

        asyncio.run(_run())

    def test_new_page_scraper_carries_recovery(self):
        async def _run():
            browser = AgentBrowser(session_name="scraper-wiring-new-page")
            ctx = FakeContext()
            recovery = FakeRecovery()
            browser.browser = ctx
            browser.recovery = recovery

            new_page = await browser.new_page(make_current=True)
            assert browser.scraper is not None
            assert browser.scraper.recovery is recovery
            assert browser.scraper.page is new_page
            await browser.close()

        asyncio.run(_run())


# --- S1/S2: _safe_goto routing through recovery, and failure propagation ---


class TestSafeGotoRecovery:
    def test_safe_goto_goes_through_recovery(self):
        async def _run():
            page = FakePage()
            recovery = FakeRecovery()
            scraper = StealthScraper(page, None, None, recovery=recovery)

            result = await scraper._safe_goto("https://example.com/", platform="test")
            assert result is True
            assert len(recovery.calls) == 1
            assert page.goto_calls == ["https://example.com/"]

        asyncio.run(_run())

    def test_safe_goto_without_recovery_uses_plain_goto(self):
        async def _run():
            page = FakePage()
            scraper = StealthScraper(page, None, None)

            assert await scraper._safe_goto("https://example.com/") is True
            assert page.goto_calls == ["https://example.com/"]

        asyncio.run(_run())

    def test_recovery_failure_does_not_retry_unprotected(self):
        async def _run():
            page = FakePage(evaluate_result=dict(CONTENT))
            scraper = StealthScraper(page, None, None, recovery=FailingRecovery())

            with pytest.raises(MaxRetriesExceeded):
                await scraper._safe_goto("https://example.com/")
            # No raw fallback goto after the protected navigation failed.
            assert page.goto_calls == []

        asyncio.run(_run())

    def test_scrape_page_returns_no_content_after_recovery_failure(self):
        async def _run():
            page = FakePage(evaluate_result=dict(CONTENT))
            scraper = StealthScraper(page, None, None, recovery=FailingRecovery())

            with pytest.raises(MaxRetriesExceeded):
                await scraper.scrape_page("https://example.com/")
            assert page.goto_calls == []
            assert page.evaluate_calls == []

        asyncio.run(_run())


# --- S3: max_images validation before it reaches the page script ---


class TestExtractImagesValidation:
    def test_hostile_max_images_raises_and_never_evaluates(self):
        async def _run():
            page = FakePage(evaluate_result=[])
            scraper = StealthScraper(page, None, None)

            with pytest.raises(ValueError):
                await scraper.extract_images(max_images="1); globalThis.pwned = 1; //")
            assert page.evaluate_calls == []

        asyncio.run(_run())

    def test_normal_int_max_images_still_works(self):
        async def _run():
            images_result = [{"src": "a.png", "alt": "", "width": 1, "height": 1}]
            page = FakePage(evaluate_result=images_result)
            scraper = StealthScraper(page, None, None)

            images = await scraper.extract_images(max_images=3)
            assert images == [{"src": "a.png", "alt": "", "width": 1, "height": 1}]
            assert len(page.evaluate_calls) == 1
            assert "slice(0, 3)" in page.evaluate_calls[0]

        asyncio.run(_run())

    def test_negative_max_images_clamps_to_zero(self):
        async def _run():
            page = FakePage(evaluate_result=[])
            scraper = StealthScraper(page, None, None)

            assert await scraper.extract_images(max_images=-5) == []
            assert "slice(0, 0)" in page.evaluate_calls[0]

        asyncio.run(_run())


# --- S4/S5: SDK reads scrape_page's nested shape; wall-clock timestamp ---


class _NestedScraper:
    async def scrape_page(self, url, extract_images=False, platform="unknown"):
        return {
            "url": url,
            "timestamp": 1_700_000_000.0,
            "content": dict(CONTENT),
            "images": [{"src": "a.png"}],
        }


class _FakeBrowserWithScraper:
    def __init__(self):
        self.scraper = _NestedScraper()


class TestSdkScrapeMapping:
    def test_scrape_populates_title_and_text_from_nested_content(self):
        async def _run():
            client = StealthClient(session_name="sdk-scrape-test")
            client._launched = True
            client._browser = _FakeBrowserWithScraper()

            result = await client.scrape("https://example.com/")
            assert result.title == "Example Title"
            assert result.text == "hello body text"
            assert result.url == "https://example.com/"
            assert result.images == [{"src": "a.png"}]
            # scrape_page extracts no links; none are fabricated.
            assert result.links == []
            assert result.metadata["headings"] == ["H1"]
            assert result.metadata["timestamp"] == 1_700_000_000.0

        asyncio.run(_run())


class TestScrapePageTimestamp:
    def test_timestamp_is_wall_clock_epoch(self):
        async def _run():
            page = FakePage(evaluate_result=dict(CONTENT))
            scraper = StealthScraper(page, None, None)

            before = time.time()
            result = await scraper.scrape_page("https://example.com/")
            after = time.time()

            assert before - 5 <= result["timestamp"] <= after + 5
            assert result["content"]["title"] == "Example Title"

        asyncio.run(_run())
