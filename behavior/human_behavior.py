"""
Human Behavior Orchestration Layer
Makes browser actions feel natural and human
"""

import os
import random
import asyncio
import math
import time
from typing import Optional, Tuple


class HumanBehavior:
    """Orchestrates realistic human-like actions"""

    def __init__(self, page):
        self.page = page
        self.rng = random.Random()

        # Python-side last known mouse position for reliable move chaining (fixes tracking bug where window.mouseX was never updated)
        # Small, high-impact realism fix for mouse paths starting from last instead of always ~center
        self.last_mouse_pos = (self.rng.randint(450, 850), self.rng.randint(280, 620))

        # Perf/ops: configurable realism to reduce CDP chatter + tiny sleeps in CI or low-resource envs (#258 #282 #123 #274)
        # Set AGENTIC_STEALTH_REALISM=light or off to skip heavy micro-movements, use bigger steps, shorter thinks
        env_r = (os.getenv("AGENTIC_STEALTH_REALISM") or os.getenv("STEALTH_REALISM") or "full").lower().strip()
        self.realism_level = {"off": 0, "light": 1, "medium": 2, "full": 3}.get(env_r, 3)

    async def think(self, min_ms: int = 400, max_ms: int = 1400):
        """Simulate thinking / reading pause"""
        delay = self.rng.uniform(min_ms, max_ms) / 1000
        await asyncio.sleep(delay)

    async def type_like_human(self, selector: str, text: str, mistake_rate: float = 0.025):
        """Type with realistic speed, variable rhythm, and occasional corrections"""
        await self.page.click(selector)
        await asyncio.sleep(self.rng.uniform(0.08, 0.25))

        for i, char in enumerate(text):
            # Small realism: longer natural pause before punctuation / capitals (from backlog typing realism)
            if char in ".,!?;:" or (char.isupper() and i > 0):
                if self.rng.random() < 0.35:
                    await asyncio.sleep(self.rng.uniform(0.18, 0.45))

            if self.rng.random() < 0.12:
                await asyncio.sleep(self.rng.uniform(0.4, 0.9))
            elif self.rng.random() < 0.25:
                await asyncio.sleep(self.rng.uniform(0.08, 0.18))

            if self.rng.random() < mistake_rate:
                wrong = self.rng.choice("abcdefghijklmnopqrstuvwxyz")
                await self.page.type(selector, wrong, delay=self.rng.uniform(25, 80))
                await asyncio.sleep(self.rng.uniform(0.2, 0.45))
                await self.page.keyboard.press("Backspace")
                # Occasional double correction for more human feel
                if self.rng.random() < 0.2:
                    await asyncio.sleep(self.rng.uniform(0.1, 0.25))
                    await self.page.keyboard.press("Backspace")
                await asyncio.sleep(self.rng.uniform(0.12, 0.3))

            delay = self.rng.uniform(28, 145)
            await self.page.type(selector, char, delay=delay)

            if i > 0 and i % 12 == 0 and self.rng.random() < 0.3:
                await asyncio.sleep(self.rng.uniform(0.35, 0.75))

    async def _bezier_curve(self, start: Tuple[float, float], end: Tuple[float, float], steps: int = 25):
        """Generate points along a more natural cubic-ish Bézier with controlled wobble.
        Small upgrade from pure quadratic for better human-like arcs and hesitation (mouse realism).
        """
        points = []
        # Primary control (mid)
        control_x = (start[0] + end[0]) / 2 + self.rng.uniform(-55, 55)
        control_y = (start[1] + end[1]) / 2 + self.rng.uniform(-35, 35)
        # Slight secondary influence for cubic flavor / overshoot tendency
        control2_x = (start[0] * 0.3 + end[0] * 0.7) + self.rng.uniform(-25, 25)
        control2_y = (start[1] * 0.3 + end[1] * 0.7) + self.rng.uniform(-20, 20)

        for i in range(steps + 1):
            t = i / steps
            # Quadratic base + small cubic blend for natural S-curve feel
            qx = (1 - t) ** 2 * start[0] + 2 * (1 - t) * t * control_x + t ** 2 * end[0]
            qy = (1 - t) ** 2 * start[1] + 2 * (1 - t) * t * control_y + t ** 2 * end[1]
            # blend in second control slightly near end
            blend = t * 0.25
            x = (1 - blend) * qx + blend * ((1 - t) * control2_x + t * end[0])
            y = (1 - blend) * qy + blend * ((1 - t) * control2_y + t * end[1])

            wobble_x = self.rng.uniform(-2.3, 2.3) * (1 - abs(t - 0.5) * 1.15)
            wobble_y = self.rng.uniform(-1.7, 1.7) * (1 - abs(t - 0.5) * 1.15)

            points.append((x + wobble_x, y + wobble_y))

        return points

    async def move_mouse_naturally(self, x: int, y: int, speed: str = "normal"):
        """Move mouse using improved Bézier curves with natural acceleration and micro-corrections.
        Now uses internal last_mouse_pos for reliable chaining (major mouse realism win).
        """
        # Prefer tracked Python pos (reliable); fallback to JS or default
        current_x, current_y = self.last_mouse_pos
        try:
            pos = await self.page.evaluate("() => ({x: window.mouseX || 0, y: window.mouseY || 0})")
            jx = pos.get("x", 0)
            jy = pos.get("y", 0)
            if jx > 50 and jy > 50:  # only trust plausible JS values
                current_x, current_y = jx, jy
        except Exception as e:
            # non-fatal, use python tracked
            print(f"[HumanBehavior] mouse pos eval non-fatal (using tracked): {e}")

        base_steps = 22 if speed == "normal" else 10
        max_steps = 42 if speed == "normal" else 20
        # Perf: fewer steps when realism reduced
        if self.realism_level <= 1:
            steps = self.rng.randint(max(3, base_steps//2), max(5, max_steps//2))
        else:
            steps = self.rng.randint(base_steps, max_steps)
        points = await self._bezier_curve((current_x, current_y), (x, y), steps)

        for px, py in points:
            await self.page.mouse.move(px, py)
            progress = (points.index((px, py)) + 1) / len(points)
            base_delay = 0.008 if speed == "normal" else 0.004
            delay = base_delay + (math.sin(progress * math.pi) * 0.018)
            await asyncio.sleep(delay)

        # micro correction
        if self.rng.random() < 0.65:
            await asyncio.sleep(self.rng.uniform(0.025, 0.07))
            final_x = x + self.rng.randint(-4, 4)
            final_y = y + self.rng.randint(-3, 3)
            await self.page.mouse.move(final_x, final_y)
            # update tracked
            self.last_mouse_pos = (final_x, final_y)
        else:
            self.last_mouse_pos = (x, y)

    async def human_click(self, selector: str = None, x: int = None, y: int = None):
        """Human-like click"""
        if selector:
            try:
                box = await self.page.query_selector(selector)
                if box:
                    box_info = await box.bounding_box()
                    if box_info:
                        target_x = box_info["x"] + box_info["width"] * self.rng.uniform(0.2, 0.8)
                        target_y = box_info["y"] + box_info["height"] * self.rng.uniform(0.2, 0.8)
                        await self.move_mouse_naturally(int(target_x), int(target_y))
            except Exception as e:
                print(f"[HumanBehavior] non-fatal error (was silent): {e}")
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
        """Scroll in small, human-like increments with occasional re-read backticks (realism)."""
        steps = self.rng.randint(5, 12)
        base_step = total_pixels // steps
        did_back = False

        for i in range(steps):
            variation = self.rng.randint(-30, 45)
            amount = base_step + variation

            if direction == "up":
                amount = -amount

            await self.page.mouse.wheel(0, amount)

            # Small realism improvement: ~8% chance of a tiny back scroll mid-sequence (human re-check)
            if not did_back and self.rng.random() < 0.08 and i > 1 and i < steps-2:
                back = int(amount * 0.3) if amount > 0 else int(amount * 0.25)
                await asyncio.sleep(self.rng.uniform(0.15, 0.35))
                await self.page.mouse.wheel(0, -back if amount > 0 else abs(back))
                did_back = True

            if self.rng.random() < 0.22:
                await asyncio.sleep(self.rng.uniform(0.6, 1.4))
            else:
                await asyncio.sleep(self.rng.uniform(0.12, 0.38))

    async def simulate_reading(self, duration_seconds: float = 8.0):
        """Simulate a person reading a page"""
        end_time = time.monotonic() + duration_seconds

        while time.monotonic() < end_time:
            scroll_amount = self.rng.randint(120, 280)
            await self.scroll_naturally(scroll_amount)
            await asyncio.sleep(self.rng.uniform(1.2, 3.8))

            if self.rng.random() < 0.18:
                await self.page.mouse.wheel(0, -self.rng.randint(40, 90))
                await asyncio.sleep(self.rng.uniform(0.8, 1.6))

    async def random_idle(self):
        """Occasional idle / reading behavior - improved dispatch"""
        choices = [
            ("think", lambda: self.think(1500, 4000)),
            ("micro", lambda: self.micro_movement_while_waiting(600)),
            ("scroll", lambda: self.scroll_naturally(self.rng.randint(60, 160))),
        ]
        name, maker = self.rng.choice(choices)
        coro = maker()
        await coro

    async def apply_viewport_jitter(self):
        """Occasional small viewport size changes"""
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
        except Exception as e:
            print(f"[HumanBehavior] viewport_jitter non-fatal: {e}")

    async def fake_search_action(self, query: str = None):
        """Simulate a natural search action"""
        if query is None:
            queries = ["python developer", "data analyst", "project manager"]
            query = self.rng.choice(queries)

        try:
            search_selectors = [
                "input[type='search']",
                "input[name='q']",
                "input[placeholder*='search']"
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
                except Exception as e:
                    print(f"[HumanBehavior] search selector try non-fatal: {e}")
                    continue

            await self.page.keyboard.type(query)
            await asyncio.sleep(0.6)
            await self.page.keyboard.press("Enter")
            return True

        except Exception as e:
            return False

    async def random_idle_behavior(self, duration_seconds: float = 5.0):
        """Advanced random idle behavior with multiple patterns - robust dispatch"""
        end_time = time.monotonic() + duration_seconds

        patterns = [
            lambda: self.think(800, 2200),
            lambda: self.micro_movement_while_waiting(800),
            lambda: self.scroll_naturally(self.rng.randint(80, 180)),
            lambda: asyncio.sleep(self.rng.uniform(1.2, 2.8)),
        ]

        while time.monotonic() < end_time:
            pattern = self.rng.choice(patterns)
            # Always produce and await a coroutine for safety
            coro = pattern()
            await coro

            if self.rng.random() < 0.3:
                break

    async def micro_movement_while_waiting(self, duration_ms: int = 800):
        """Small, natural mouse movements while waiting. Now updates tracked pos."""
        end_time = time.monotonic() + (duration_ms / 1000)

        while time.monotonic() < end_time:
            try:
                dx = self.rng.randint(-25, 25)
                dy = self.rng.randint(-18, 18)

                current = await self.page.evaluate("() => ({x: window.mouseX || 600, y: window.mouseY || 400})")
                new_x = current.get("x", 600) + dx
                new_y = current.get("y", 400) + dy

                await self.page.mouse.move(new_x, new_y)
                self.last_mouse_pos = (new_x, new_y)
            except Exception as e:
                print(f"[HumanBehavior] non-fatal error (was silent): {e}")

            sleep_base = 0.35 if self.realism_level >= 3 else (0.1 if self.realism_level >= 2 else 0.01)
            await asyncio.sleep(self.rng.uniform(sleep_base, sleep_base + 0.1))

    async def idle_while_loading(self, max_wait_seconds: float = 4.0):
        """Natural idle behavior while loading - robust"""
        start = time.monotonic()

        while time.monotonic() - start < max_wait_seconds:
            behavior = self.rng.choice([
                lambda: self.micro_movement_while_waiting(600),
                lambda: asyncio.sleep(self.rng.uniform(0.6, 1.4)),
                lambda: self.scroll_naturally(self.rng.randint(60, 140))
            ])

            coro = behavior()
            await coro

            if self.rng.random() < 0.25:
                break

    # --- Phase 8 Human Behavior Realism Additions (Closes #275, #267, #260, #284, #291) ---

    async def accidental_click_with_correction(self, selector: str = None, x: int = None, y: int = None):
        """Simulate realistic accidental click followed by immediate correction (#275)"""
        await self.human_click(selector, x, y)
        await asyncio.sleep(self.rng.uniform(0.05, 0.15))
        if self.rng.random() < 0.15 and self.realism_level >= 2:
            try:
                await self.page.mouse.move(
                    (x or 500) + self.rng.randint(-30, 30),
                    (y or 400) + self.rng.randint(-20, 20)
                )
                await asyncio.sleep(0.08)
                if self.rng.random() < 0.4:
                    await self.page.keyboard.press("Escape")
                else:
                    await self.human_click(selector, x, y)
            except Exception:
                pass

    async def type_with_select_all_replace(self, selector: str, new_text: str, mistake_rate: float = 0.02):
        """Simulate realistic 'select all + replace' editing pattern (#267)"""
        await self.human_click(selector)
        await asyncio.sleep(self.rng.uniform(0.1, 0.25))
        if self.rng.random() < 0.7:
            await self.page.keyboard.press("Control+A" if self.rng.random() > 0.5 else "Meta+A")
            await asyncio.sleep(self.rng.uniform(0.05, 0.12))
            if self.rng.random() < 0.3:
                await self.page.keyboard.press("Backspace")
        await self.type_like_human(selector, new_text, mistake_rate=mistake_rate)

    async def press_keyboard_shortcut(self, shortcut: str):
        """Simulate realistic keyboard shortcut / hotkey usage (#260)"""
        try:
            await asyncio.sleep(self.rng.uniform(0.05, 0.2))
            await self.page.keyboard.press(shortcut)
            await asyncio.sleep(self.rng.uniform(0.1, 0.4))
        except Exception as e:
            print(f"[HumanBehavior] shortcut non-fatal: {shortcut} {e}")

    async def simulate_terms_privacy_reading(self, min_pauses: int = 2):
        """Simulate realistic reading of terms/privacy policy with pauses and micro-scrolls (#284)"""
        for i in range(self.rng.randint(min_pauses, min_pauses + 3)):
            await self.think(1800, 4200)
            await self.scroll_naturally(self.rng.randint(40, 120))
            if self.rng.random() < 0.6:
                await self.micro_movement_while_waiting(400)
            if self.rng.random() < 0.25:
                await self.page.keyboard.press("PageDown")
        await self.think(600, 1400)

    async def mobile_in_spirit_interaction(self, action: str = "tap"):
        """Approximate small-screen / mobile-like interaction patterns even on desktop (#291)"""
        if action == "tap":
            await asyncio.sleep(self.rng.uniform(0.15, 0.35))
            try:
                pos = await self.page.evaluate("() => ({x: window.mouseX||500, y: window.mouseY||400})")
                await self.page.mouse.move(
                    pos.get("x", 500) + self.rng.randint(-12, 12),
                    pos.get("y", 400) + self.rng.randint(-8, 8)
                )
                await self.page.mouse.down()
                await asyncio.sleep(0.08)
                await self.page.mouse.up()
                if self.rng.random() < 0.2:
                    await asyncio.sleep(0.12)
                    await self.page.mouse.down()
                    await asyncio.sleep(0.05)
                    await self.page.mouse.up()
            except Exception:
                pass
