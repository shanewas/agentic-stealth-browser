"""
LinkedIn-specific action support.
Addresses #168: First-class support for LinkedIn-specific actions.
"""

import random
from typing import Optional, Any


class LinkedInActions:
    """LinkedIn-specific browser actions with stealth-aware behavior.

    Usage:
        li = LinkedInActions(page, human_behavior)
        await li.view_profile("williamhgates")
        await li.send_connection_request("williamhgates")
    """

    def __init__(self, page, human_behavior, logger: Optional[Any] = None):
        self.page = page
        self.human = human_behavior
        self._logger = logger

    async def view_profile(self, username: str, duration_seconds: float = 5.0):
        """View a LinkedIn profile naturally."""
        url = f"https://www.linkedin.com/in/{username}"
        await self.page.goto(url, wait_until="domcontentloaded")

        # Natural reading behavior
        await self.human.scroll_naturally(300)
        await self.human.think(1000, 2000)
        await self.human.scroll_naturally(200)
        await self.human.think(800, 1500)

        # Simulate reading for duration
        elapsed = 0
        while elapsed < duration_seconds:
            await self.human.think(500, 1500)
            if random.random() < 0.3:
                await self.human.scroll_naturally(random.randint(50, 150))
            elapsed += 1

    async def send_connection_request(
        self, username: str, message: Optional[str] = None
    ):
        """Send a connection request naturally."""
        await self.view_profile(username, duration_seconds=3.0)

        # Look for connect button
        try:
            connect_btn = await self.page.query_selector(
                "button[aria-label*='Connect'], button[aria-label*='connect']"
            )
            if connect_btn:
                await self.human.human_click("button[aria-label*='Connect']")
                await self.human.think(500, 1000)

                # Add message if provided
                if message:
                    await self.human.type_like_human("textarea", message)
                    await self.human.think(300, 800)

                # Send
                send_btn = await self.page.query_selector(
                    "button[aria-label*='Send'], button[data-control-name*='send']"
                )
                if send_btn:
                    await self.human.human_click("button[aria-label*='Send']")
                    return True
        except Exception:
            pass
        return False

    async def search_jobs(self, keywords: str, location: str = "", max_pages: int = 2):
        """Search for jobs naturally."""
        url = f"https://www.linkedin.com/jobs/search/?keywords={keywords}"
        if location:
            url += f"&location={location}"

        await self.page.goto(url, wait_until="domcontentloaded")
        await self.human.think(1000, 2000)

        results = []
        for page_num in range(max_pages):
            # Extract job listings
            try:
                jobs = await self.page.evaluate("""
                    () => {
                        return Array.from(document.querySelectorAll('.job-card-container'))
                            .slice(0, 10)
                            .map(el => ({
                                title: el.querySelector('.job-card-list__title')?.innerText || '',
                                company: el.querySelector('.artdeco-entity-lockup__subtitle')?.innerText || '',
                                location: el.querySelector('.artdeco-entity-lockup__caption')?.innerText || ''
                            }));
                    }
                """)
                results.extend(jobs)
            except Exception:
                pass

            # Natural browsing between pages
            await self.human.scroll_naturally(400)
            await self.human.think(1500, 3000)

            # Next page
            if page_num < max_pages - 1:
                try:
                    next_btn = await self.page.query_selector(
                        "button[aria-label*='Next']"
                    )
                    if next_btn:
                        await self.human.human_click("button[aria-label*='Next']")
                        await self.human.think(2000, 4000)
                except Exception:
                    pass

        return results

    async def post_update(self, text: str):
        """Post a LinkedIn update naturally."""
        await self.page.goto(
            "https://www.linkedin.com/feed/", wait_until="domcontentloaded"
        )
        await self.human.think(1000, 2000)

        # Click start post
        try:
            await self.human.human_click("button[aria-label*='Start a post']")
            await self.human.think(500, 1000)

            # Type post
            await self.human.type_like_human("div[contenteditable='true']", text)
            await self.human.think(800, 1500)

            # Post
            await self.human.human_click("button[aria-label*='Post']")
            return True
        except Exception:
            return False

    async def endorse_skill(self, username: str, skill: str):
        """Endorse a skill naturally."""
        await self.view_profile(username, duration_seconds=2.0)

        # Scroll to skills section
        await self.human.scroll_naturally(800)
        await self.human.think(500, 1000)

        # Find and click endorse button
        try:
            endorse_btn = await self.page.query_selector(
                f"button[aria-label*='{skill}'], button[aria-label*='Endorse']"
            )
            if endorse_btn:
                await self.human.human_click("button[aria-label*='Endorse']")
                return True
        except Exception:
            pass
        return False
