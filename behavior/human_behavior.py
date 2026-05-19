"""
Human Behavior Orchestration Layer
Makes browser actions feel natural and human
"""

import random
import asyncio
from typing import Optional


class HumanBehavior:
    """Orchestrates realistic human-like actions"""
    
    def __init__(self, page):
        self.page = page
        self.rng = random.Random()
    
    async def think(self, min_ms: int = 400, max_ms: int = 1400):
        """Simulate thinking / reading pause"""
        delay = self.rng.uniform(min_ms, max_ms) / 1000
        await asyncio.sleep(delay)
    
    async def type_like_human(self, selector: str, text: str, mistake_rate: float = 0.03):
        """Type with realistic speed and occasional corrections"""
        await self.page.click(selector)
        await asyncio.sleep(self.rng.uniform(0.1, 0.3))
        
        for char in text:
            # Occasional small pause (thinking)
            if self.rng.random() < 0.07:
                await asyncio.sleep(self.rng.uniform(0.25, 0.7))
            
            # Small chance of "mistake" then correction
            if self.rng.random() < mistake_rate:
                wrong = self.rng.choice("abcdefghijklmnopqrstuvwxyz")
                await self.page.type(selector, wrong, delay=self.rng.uniform(30, 90))
                await asyncio.sleep(self.rng.uniform(0.15, 0.4))
                await self.page.keyboard.press("Backspace")
                await asyncio.sleep(self.rng.uniform(0.1, 0.25))
            
            await self.page.type(selector, char, delay=self.rng.uniform(35, 160))
    
    async def move_mouse_naturally(self, x: int, y: int):
        """Move mouse in a slightly curved, noisy path"""
        try:
            box = await self.page.evaluate("() => ({x: window.scrollX || 0, y: window.scrollY || 0})")
            current_x = box.get("x", 400)
            current_y = box.get("y", 300)
        except:
            current_x, current_y = 400, 300
        
        steps = self.rng.randint(10, 22)
        for i in range(steps):
            progress = (i + 1) / steps
            # Add some noise
            noise_x = self.rng.uniform(-12, 12)
            noise_y = self.rng.uniform(-8, 8)
            px = current_x + (x - current_x) * progress + noise_x
            py = current_y + (y - current_y) * progress + noise_y
            await self.page.mouse.move(px, py)
            await asyncio.sleep(self.rng.uniform(0.008, 0.035))
    
    async def scroll_naturally(self, total_pixels: int = 400, direction: str = "down"):
        """Scroll in small, human-like increments"""
        steps = self.rng.randint(4, 9)
        step_size = total_pixels // steps
        
        for _ in range(steps):
            variation = self.rng.randint(-25, 35)
            amount = step_size + variation
            if direction == "up":
                amount = -amount
            await self.page.mouse.wheel(0, amount)
            await asyncio.sleep(self.rng.uniform(0.18, 0.55))
    
    async def random_idle(self):
        """Occasional idle / reading behavior"""
        if self.rng.random() < 0.25:
            await asyncio.sleep(self.rng.uniform(1.2, 3.5))
