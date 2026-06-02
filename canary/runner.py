"""Main run loop: one AgentBrowser, visits 6 sites, scores each."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from core.agent_browser import AgentBrowser
from canary.score import score_results
from canary.sites import SITES, CanarySite


class CanaryRunner:
    """Runs the canary: 6 sites, one browser session, ~5 minutes."""

    async def run_all(self) -> dict[str, Any]:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        version = self._get_version()
        started = time.monotonic()
        per_site: dict[str, str] = {}
        error: str | None = None

        browser = AgentBrowser(session_name=f"canary-{ts}")
        try:
            await browser.launch(headless=True)
            for site in SITES:
                result = await self._test_site(browser, site)
                per_site[site["key"]] = result
        except Exception as e:
            error = f"runner crash: {type(e).__name__}: {e}"
        finally:
            try:
                await browser.close()  # type: ignore[no-untyped-call]
            except Exception:
                pass

        score = score_results(per_site)
        return {
            "ts": ts,
            "version": version,
            "score": score,
            "per_site": per_site,
            "duration_s": int(time.monotonic() - started),
            "error": error,
        }

    async def _test_site(self, browser: AgentBrowser, site: CanarySite) -> str:
        """Returns one of: pass, detected, soft-detect, fail."""
        try:
            success = await browser.safe_goto(
                site["url"], platform=site["platform"], warm_up=False
            )
            if not success:
                return "fail"
            human = browser.human
            if human is None:
                return "fail"
            await human.think(1500, 3000)
            page = getattr(browser, "page", None)
            if page is None:
                return "fail"
            content = (await page.content()).lower()
            for sig in site["expected_signals"]:
                if sig.lower() in content:
                    return "detected"
            if site["platform"] == "cloudflare":
                title = (await page.title()).lower()
                if "just a moment" in title or "checking your browser" in title:
                    return "detected"
                if "cloudflare" in content or "cf-" in content:
                    return "soft-detect"
            return "pass"
        except Exception:
            return "fail"

    def _get_version(self) -> str:
        try:
            from canary import __version__

            return __version__
        except ImportError:
            return "unknown"