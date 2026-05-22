"""
Behavioral Orchestration Layer
High-level human-like flows for agentic browsing
"""

import random
from typing import Optional


class BehaviorOrchestrator:
    """
    High-level human behavior flows.
    Use these instead of raw actions for better undetectability.
    """
    
    def __init__(self, human_behavior, rng: Optional["random.Random"] = None):
        self.human = human_behavior
        self.rng = rng or random.Random()
    
    async def read_page_naturally(self, min_scrolls: int = 2, max_scrolls: int = 5):
        """Simulate reading a page like a human"""
        scrolls = self.rng.randint(min_scrolls, max_scrolls)
        
        for i in range(scrolls):
            # Scroll a bit
            scroll_amount = self.rng.randint(200, 450)
            await self.human.scroll_naturally(scroll_amount)
            
            # Read / think
            if i < scrolls - 1:
                await self.human.think(1200, 2800)
            
            # Occasional mouse movement while "reading"
            if self.rng.random() < 0.4:
                x = self.rng.randint(300, 900)
                y = self.rng.randint(200, 600)
                await self.human.move_mouse_naturally(x, y)
                await self.human.think(400, 900)
    
    async def browse_feed_naturally(self, actions: int = 4):
        """Simulate natural feed browsing behavior"""
        for _ in range(actions):
            # Scroll feed
            await self.human.scroll_naturally(self.rng.randint(300, 600))
            await self.human.think(800, 2200)
            
            # Occasional hover / mouse movement
            if self.rng.random() < 0.5:
                x = self.rng.randint(400, 1000)
                y = self.rng.randint(250, 700)
                await self.human.move_mouse_naturally(x, y)
            
            # Small chance of longer pause (reading a post)
            if self.rng.random() < 0.25:
                await self.human.think(2500, 4500)
    
    async def view_profile_naturally(self):
        """Natural profile viewing flow"""
        # Initial read
        await self.read_page_naturally(2, 4)
        
        # Scroll to experience / about section
        await self.human.scroll_naturally(350)
        await self.human.think(900, 1800)
        
        # More reading
        await self.read_page_naturally(1, 3)
        
        # Final small movements
        await self.human.move_mouse_naturally(600, 400)
        await self.human.think(600, 1200)


    async def natural_linkedin_browsing(self, actions: int = 5):
        """Simulate natural LinkedIn browsing behavior"""
        for i in range(actions):
            # Read feed naturally
            await self.read_page_naturally(1, 3)

            # Occasional profile hover / click
            if self.rng.random() < 0.35:
                await self.human.move_mouse_naturally(
                    self.rng.randint(450, 850),
                    self.rng.randint(280, 520)
                )
                await self.human.think(600, 1300)

            # Scroll more
            await self.human.scroll_naturally(self.rng.randint(350, 650))

            # Longer reading pause
            if self.rng.random() < 0.4:
                await self.human.think(1800, 4200)

            # Small chance of clicking into a post
            if self.rng.random() < 0.22 and i > 1:
                await self.human.human_click()
                await self.read_page_naturally(1, 2)
                # Go back
                await self.human.think(800, 1600)

    async def natural_amazon_shopping(self, actions: int = 4):
        """Natural Amazon browsing flow"""
        for _ in range(actions):
            await self.human.scroll_naturally(self.rng.randint(280, 520))
            await self.human.think(900, 2100)

            # Occasional product hover
            if self.rng.random() < 0.45:
                await self.human.move_mouse_naturally(
                    self.rng.randint(300, 700),
                    self.rng.randint(250, 550)
                )
                await self.human.apply_viewport_jitter()

            # Longer pause on interesting items
            if self.rng.random() < 0.3:
                await self.human.think(2200, 4800)

    async def natural_search_session(self, query: str = None):
        """Simulate a natural search + browsing session"""
        # Initial page read
        await self.read_page_naturally(2, 4)

        # Search behavior
        if query and self.rng.random() < 0.6:
            try:
                # Type search query naturally
                await self.human.type_like_human("input[type='search'], input[name='q']", query)
                await self.human.think(400, 900)
                await self.human.human_click("button[type='submit'], button[aria-label*='search']")
                await self.human.think(1200, 2400)
            except Exception:
                # Search may fail if page structure differs; continue gracefully
                pass

        # Browse results
        await self.human.scroll_naturally(self.rng.randint(400, 700))
        await self.read_page_naturally(1, 3)

