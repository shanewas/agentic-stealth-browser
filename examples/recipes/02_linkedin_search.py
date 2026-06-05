"""02_linkedin_search.py

Demonstrate the `linkedin_2026` preset's stealth fingerprint on a LinkedIn
public page, then run an anonymous DuckDuckGo search scoped to LinkedIn to
show how a public-source job-discovery flow looks in practice.

We do NOT ship LinkedIn credentials. Anything behind the auth wall (logged-in
search, profile views, messaging) needs your own session cookies loaded into
the session -- see CONTRIBUTING.md and the `sessions/` module.

Run:
    pip install agentic-stealth-browser
    playwright install --with-deps chromium
    python 02_linkedin_search.py
"""

import asyncio
from core.agent_browser import AgentBrowser


SEARCH_TERM = "site reliability engineer"
DDG = "https://duckduckgo.com/html/"  # HTML endpoint, no JS fingerprinting noise


async def main() -> None:
    async with AgentBrowser(
        session_name="linkedin-search-demo",
        preset="linkedin_2026",
        region="us",
    ) as browser:
        await browser.launch(headless=True)

        # 1. Sanity-check the fingerprint on a public LinkedIn surface.
        await browser.safe_goto("https://www.linkedin.com/")
        webdriver = await browser.page.evaluate("navigator.webdriver")
        print(f"navigator.webdriver (must be falsy): {webdriver!r}")

        # 2. Public job search via DuckDuckGo's HTML endpoint.
        query = f"site%3Alinkedin.com%2Fjobs%20{SEARCH_TERM.replace(' ', '+')}"
        await browser.safe_goto(f"{DDG}?q={query}")
        results = await browser.page.locator("a.result__a").all()
        print(f"public linkedin matches for {SEARCH_TERM!r}: {len(results)}")
        for r in results[:3]:
            print(" -", await r.inner_text())


if __name__ == "__main__":
    asyncio.run(main())
