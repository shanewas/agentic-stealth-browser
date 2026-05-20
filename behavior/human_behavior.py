"""
Human Behavior Orchestration Layer
Makes browser actions feel natural and human
"""

import random
import asyncio
import math
from typing import Optional, Tuple


class HumanBehavior:
    """Orchestrates realistic human-like actions"""

    def __init__(self, page):
        self.page = page
        self.rng = random.Random()

    async def think(self, min_ms: int = 400, max_ms: int = 1400):
        """Simulate thinking / reading pause"""
        delay = self.rng.uniform(min_ms, max_ms) / 1000
        await asyncio.sleep(delay)

    async def type_like_human(self, selector: str, text: str, mistake_rate: float = 0.025):
        """Type with realistic speed, variable rhythm, and occasional corrections"""
        await self.page.click(selector)
        await asyncio.sleep(self.rng.uniform(0.08, 0.25))

        for i, char in enumerate(text):
            if self.rng.random() < 0.12:
                await asyncio.sleep(self.rng.uniform(0.4, 0.9))
            elif self.rng.random() < 0.25:
                await asyncio.sleep(self.rng.uniform(0.08, 0.18))

            if self.rng.random() < mistake_rate:
                wrong = self.rng.choice("abcdefghijklmnopqrstuvwxyz")
                await self.page.type(selector, wrong, delay=self.rng.uniform(25, 80))
                await asyncio.sleep(self.rng.uniform(0.2, 0.45))
                await self.page.keyboard.press("Backspace")
                await asyncio.sleep(self.rng.uniform(0.12, 0.3))

            delay = self.rng.uniform(28, 145)
            await self.page.type(selector, char, delay=delay)

            if i > 0 and i % 12 == 0 and self.rng.random() < 0.3:
                await asyncio.sleep(self.rng.uniform(0.35, 0.75))

    async def _bezier_curve(self, start: Tuple[float, float], end: Tuple[float, float], steps: int = 25):
        """Generate points along a quadratic Bézier curve with slight randomness"""
        points = []
        control_x = (start[0] + end[0]) / 2 + self.rng.uniform(-60, 60)
        control_y = (start[1] + end[1]) / 2 + self.rng.uniform(-40, 40)

        for i in range(steps + 1):
            t = i / steps
            x = (1 - t) ** 2 * start[0] + 2 * (1 - t) * t * control_x + t ** 2 * end[0]
            y = (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * control_y + t ** 2 * end[1]

            wobble_x = self.rng.uniform(-2.5, 2.5) * (1 - abs(t - 0.5) * 1.2)
            wobble_y = self.rng.uniform(-1.8, 1.8) * (1 - abs(t - 0.5) * 1.2)

            points.append((x + wobble_x, y + wobble_y))

        return points

    async def move_mouse_naturally(self, x: int, y: int, speed: str = "normal"):
        """Move mouse using Bézier curves with natural acceleration and micro-corrections"""
        try:
            pos = await self.page.evaluate("() => ({x: window.mouseX || 500, y: window.mouseY || 350})")
            current_x = pos.get("x", 500)
            current_y = pos.get("y", 350)
        except:
            current_x, current_y = 500, 350

        steps = self.rng.randint(22, 42) if speed == "normal" else self.rng.randint(10, 20)
        points = await self._bezier_curve((current_x, current_y), (x, y), steps)

        for px, py in points:
            await self.page.mouse.move(px, py)
            progress = (points.index((px, py)) + 1) / len(points)
            base_delay = 0.008 if speed == "normal" else 0.004
            delay = base_delay + (math.sin(progress * math.pi) * 0.018)
            await asyncio.sleep(delay)

        if self.rng.random() < 0.65:
            await asyncio.sleep(self.rng.uniform(0.025, 0.07))
            await self.page.mouse.move(
                x + self.rng.randint(-4, 4),
                y + self.rng.randint(-3, 3)
            )

    async def human_click(self, selector: str = None, x: int = None, y: int = None):
        """Human-like click: move naturally then click with slight overshoot correction"""
        if selector:
            try:
                box = await self.page.query_selector(selector)
                if box:
                    box_info = await box.bounding_box()
                    if box_info:
                        target_x = box_info["x"] + box_info["width"] * self.rng.uniform(0.2, 0.8)
                        target_y = box_info["y"] + box_info["height"] * self.rng.uniform(0.2, 0.8)
                        await self.move_mouse_naturally(int(target_x), int(target_y))
            except:
                pass
        elif x is not None and y is not None:
            await self.move_mouse_naturally(x, y)

        await asyncio.sleep(self.rng.uniform(0.04, 0.12))

        if self.rng.random() < 0.08:
            await self.page.mouse.click(0, 0)
        else:
            await self.page.mouse.down()
            await asyncio.sleep(self.rng.uniform(0.03, 0.08))
            await self.page.mouse.up()

    async def scroll_naturally(self, total_pixels: int = 400, direction: str = "down"):
        """Scroll in small, human-like increments with variable speed and pauses"""
        steps = self.rng.randint(5, 12)
        base_step = total_pixels // steps

        for i in range(steps):
            variation = self.rng.randint(-30, 45)
            amount = base_step + variation

            if direction == "up":
                amount = -amount

            await self.page.mouse.wheel(0, amount)

            if self.rng.random() < 0.22:
                await asyncio.sleep(self.rng.uniform(0.6, 1.4))
            else:
                await asyncio.sleep(self.rng.uniform(0.12, 0.38))

            if i > 2 and self.rng.random() < 0.08:
                await asyncio.sleep(self.rng.uniform(0.3, 0.6))
                reverse = -amount // 3
                await self.page.mouse.wheel(0, reverse)
                await asyncio.sleep(self.rng.uniform(0.2, 0.4))

    async def simulate_reading(self, duration_seconds: float = 8.0):
        """Simulate a person reading a page"""
        end_time = asyncio.get_event_loop().time() + duration_seconds
        total_scrolled = 0

        while asyncio.get_event_loop().time() < end_time:
            scroll_amount = self.rng.randint(120, 280)
            await self.scroll_naturally(scroll_amount)
            total_scrolled += scroll_amount

            await asyncio.sleep(self.rng.uniform(1.2, 3.8))

            if self.rng.random() < 0.18:
                await self.page.mouse.wheel(0, -self.rng.randint(40, 90))
                await asyncio.sleep(self.rng.uniform(0.8, 1.6))

    async def random_idle(self):
        """Occasional idle / reading behavior"""
        behaviors = [
            lambda: asyncio.sleep(self.rng.uniform(1.5, 4.0)),
            lambda: self.page.mouse.move(
                self.rng.randint(200, 800),
                self.rng.randint(150, 500)
            ),
            self.scroll_naturally,
        ]

        behavior = self.rng.choice(behaviors)
        if asyncio.iscoroutinefunction(behavior):
            await behavior()
        else:
            await behavior()

    async def apply_viewport_jitter(self):
        """Occasional small viewport size changes (very effective against fingerprinting)"""
        try:
            current = await self.page.evaluate("() => ({width: window.innerWidth, height: window.innerHeight})")
            w = current.get("width", 1366)
            h = current.get("height", 768)

            jitter_w = w + self.rng.randint(-18, 24)
            jitter_h = h + self.rng.randint(-14, 18)

            await self.page.set_viewport_size({"width": jitter_w, "height": jitter_h})
            await asyncio.sleep(self.rng.uniform(0.25, 0.7))

            if self.rng.random() < 0.4:
                await asyncio.sleep(self.rng.uniform(3.5, 9))
                await self.page.set_viewport_size({"width": w, "height": h})
        except:
            pass

    async def occasional_window_resize(self):
        """Rare but noticeable window resize"""
        if self.rng.random() < 0.11:
            try:
                sizes = [(1366, 768), (1440, 900), (1280, 720), (1536, 864), (1920, 1080)]
                new_size = self.rng.choice(sizes)
                await self.page.set_viewport_size({"width": new_size[0], "height": new_size[1]})
                await self.think(600, 1400)
            except:
                pass

    async def micro_movement_while_waiting(self, duration_ms: int = 800):
        """Small, natural mouse movements while waiting for elements"""
        end_time = asyncio.get_event_loop().time() + (duration_ms / 1000)

        while asyncio.get_event_loop().time() < end_time:
            try:
                dx = self.rng.randint(-25, 25)
                dy = self.rng.randint(-18, 18)

                current = await self.page.evaluate("() => ({x: window.mouseX || 600, y: window.mouseY || 400})")
                new_x = current.get("x", 600) + dx
                new_y = current.get("y", 400) + dy

                await self.page.mouse.move(new_x, new_y)
            except:
                pass

            await asyncio.sleep(self.rng.uniform(0.35, 0.85))

    async def idle_while_loading(self, max_wait_seconds: float = 4.0):
        """Natural idle behavior while page/elements are loading"""
        start = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start < max_wait_seconds:
            behavior = self.rng.choice([
                lambda: self.micro_movement_while_waiting(600),
                lambda: asyncio.sleep(self.rng.uniform(0.6, 1.4)),
                lambda: self.scroll_naturally(self.rng.randint(60, 140))
            ])

            if asyncio.iscoroutinefunction(behavior):
                await behavior()
            else:
                await behavior()

            if self.rng.random() < 0.25:
                break

async def fake_search_action(self, query: str = None):
        """Simulate a natural search action (very effective warm-up)."""
        if query is None:
            queries = ["python developer", "data analyst", "project manager", "marketing specialist"]
            query = self.rng.choice(queries)

        try:
            # Look for search input
            search_selectors = [
                "input[type='search']",
                "input[name='q']",
                "input[placeholder*='search']",
                "input[aria-label*='search']"
            ]

            for selector in search_selectors:
                try:
                    el = await self.page.query_selector(selector)
                    if el:
                        await self.human_click(selector)
                        await self.type_like_human(selector, query)
                        await asyncio.sleep(self.rng.uniform(0.4, 0.9))
                        await self.page.keyboard.press("Enter")
                        await self.think(1200, 2400)
                        return True
                except:
                    continue

            # Fallback: just type in body
            await self.page.keyboard.type(query)
            await asyncio.sleep(0.6)
            await self.page.keyboard.press("Enter")
            return True

        except Exception as e:
            return False

    async def random_idle_behavior(self, duration_seconds: float = 5.0):
        """Advanced random idle behavior with multiple patterns."""
        end_time = asyncio.get_event_loop().time() + duration_seconds

        patterns = [
            lambda: self.think(800, 2200),
            lambda: self.micro_movement_while_waiting(800),
            lambda: self.scroll_naturally(self.rng.randint(80, 180)),
            lambda: asyncio.sleep(self.rng.uniform(1.2, 2.8)),
        ]

        while asyncio.get_event_loop().time() < end_time:
            pattern = self.rng.choice(patterns)
            if asyncio.iscoroutinefunction(pattern):
                await pattern()
            else:
                await pattern()

            if self.rng.random() < 0.3:
                break
