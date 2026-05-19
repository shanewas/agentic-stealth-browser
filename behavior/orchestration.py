"""
Behavioral Orchestration Layer
High-level human-like flows for agentic browsing
"""

import asyncio
import random
from typing import Optional


class BehaviorOrchestrator:
    """
    High-level human behavior flows.
    Use these instead of raw actions for better undetectability.
    """
    
    def __init__(self, human_behavior):
        self.human = human_behavior
        self.rng = random.Random()
    
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
