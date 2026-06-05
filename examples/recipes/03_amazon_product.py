"""03_amazon_product.py

Fetch a single Amazon product page with the full stealth stack (init-script
patching + behavior layer ready), then extract the title and price into a
plain dict. Useful as a starting point for product research or monitoring.

Note: Amazon rotates its selectors; if this script returns None for `price`,
re-run with a current product URL and adjust the selector.

Run:
    pip install agentic-stealth-browser
    playwright install --with-deps chromium
    python 03_amazon_product.py
"""

import asyncio
from core.agent_browser import AgentBrowser


# A stable, well-known Amazon product page. Replace with any ASIN URL.
PRODUCT_URL = "https://www.amazon.com/dp/B0BSHF7WHW"


async def main() -> None:
    async with AgentBrowser(session_name="amazon-product-demo", region="us") as browser:
        await browser.launch(headless=True)
        await browser.safe_goto(PRODUCT_URL, rate_limit=False)
        await asyncio.sleep(2)  # let dynamic content settle

        title = await browser.page.locator("#productTitle").first.inner_text()
        # Amazon's price block has changed IDs over time; try a few.
        price = None
        for sel in (
            "span.a-price span.a-offscreen",
            "#priceblock_ourprice",
            "#priceblock_dealprice",
        ):
            try:
                if await browser.page.locator(sel).count():
                    price = await browser.page.locator(sel).first.inner_text()
                    break
            except Exception:
                continue

        print({"title": title.strip(), "price": (price or "").strip() or None})


if __name__ == "__main__":
    asyncio.run(main())
