"""01_cloudflare_bypass.py

Load a known Cloudflare-protected test page (nowsecure.nl), let the
AntiBlockOrchestrator + init-script stealth run, save a screenshot,
and print the final page title so you can eyeball the result.

Run:
    pip install agentic-stealth-browser
    playwright install --with-deps chromium
    python 01_cloudflare_bypass.py
"""

import asyncio
from core.agent_browser import AgentBrowser


TARGET = "https://nowsecure.nl"


async def main() -> None:
    async with AgentBrowser(session_name="cf-bypass-demo", region="us") as browser:
        await browser.launch(headless=True)
        await browser.safe_goto(TARGET, timeout=45_000)
        await asyncio.sleep(3)  # let the challenge resolve
        title = await browser.page.title()
        await browser.page.screenshot(path="cloudflare_bypass.png", full_page=True)
        print(f"title: {title}")
        print("screenshot: cloudflare_bypass.png")


if __name__ == "__main__":
    asyncio.run(main())
