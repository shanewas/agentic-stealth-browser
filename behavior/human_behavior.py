"""
Human Behavior Orchestration Layer
Makes browser actions feel natural and human
"""

import os
import random
import asyncio
import math
import time
from typing import Optional, Tuple, Any


class HumanBehavior:
    """Orchestrates realistic human-like actions"""

    def __init__(self, page, rng: Optional["random.Random"] = None, device_profile: Optional[Any] = None, logger: Optional[Any] = None):
        self.page = page
        self.rng = rng or random.Random()
        self._logger = logger  # Optional AuditLogger for structured logging

        # Authoritative Python-side last mouse pos (with JS sync) for reliable chaining.
        # Every gesture (move, click, micro, correction) starts from previous end point.
        # Combined with initialize + _record + tracker in stealth: fixes #24 #101 completely.
        self.last_mouse_pos = (self.rng.randint(450, 850), self.rng.randint(280, 620))

        self.device_profile = device_profile
        self.session_start_time = time.time()
        self.action_count = 0
        self.fatigue_level = 0.0

        # Initialize realism level from environment
        env_r = (os.getenv("AGENTIC_STEALTH_REALISM") or os.getenv("STEALTH_REALISM") or "").lower().strip()
        ci_indicators = bool(
            os.getenv("CI") or os.getenv("GITHUB_ACTIONS") or os.getenv("GITLAB_CI") or
            os.getenv("JENKINS_URL") or os.getenv("AGENTIC_STEALTH_LIGHT_CI") or
            os.getenv("HEADLESS") == "1"
        )
        if not env_r:
            env_r = "light" if ci_indicators else "full"
        self.realism_level = {"off": 0, "light": 1, "medium": 2, "full": 3}.get(env_r, 3)
        if self.realism_level > 1 and (os.getenv("STEALTH_HEADLESS", "").lower() in ("1", "true") or ci_indicators):
            self.realism_level = 1

    def _log(self, msg: str, level: str = "warning"):
        """Log a message via AuditLogger if available, otherwise fall back to print."""
        if self._logger and hasattr(self._logger, "log_action"):
            self._logger.log_action(f"human_behavior.{level}", {"message": msg}, level=level)
        else:
            print(f"[HumanBehavior] {msg}")

    async def _record_mouse_position(self, x: float, y: float) -> None:
        """Update Python authoritative last pos + sync to JS window.mouseX/Y.
        This + stealth init + calls after every move fixes continuity (#24 #101).
        Cursor no longer resets; gestures chain from real previous end point.
        """
        self.last_mouse_pos = (int(round(x)), int(round(y)))
        try:
            await self.page.evaluate(
                f"window.mouseX = {self.last_mouse_pos[0]}; window.mouseY = {self.last_mouse_pos[1]};"
            )
        except Exception:
            # JS sync best-effort (page may be navigating etc); Python state authoritative
            pass

    async def initialize_mouse_tracker(self) -> None:
        """Call after page ready (e.g. in launch) to seed JS tracker from our Python last_pos.
        Also installs a passive mousemove listener so real events (if any) keep JS in sync.
        """
        x, y = self.last_mouse_pos
        try:
            await self.page.evaluate(f"""
                (function() {{
                    if (typeof window.mouseX === 'undefined' || !window.mouseX) window.mouseX = {x};
                    if (typeof window.mouseY === 'undefined' || !window.mouseY) window.mouseY = {y};
                    if (!window._mouseTrackerInstalled) {{
                        window._mouseTrackerInstalled = true;
                        document.addEventListener('mousemove', function(e) {{
                            window.mouseX = e.clientX;
                            window.mouseY = e.clientY;
                        }}, {{passive: true}});
                    }}
                }})();
            """)
        except Exception:
            pass

    async def think(self, min_ms: int = 400, max_ms: int = 1400):
        """Simulate thinking / reading pause"""
        delay = self.rng.uniform(min_ms, max_ms) / 1000
        await asyncio.sleep(delay)

    def _update_fatigue(self) -> None:
        """#251 fatigue ramp."""
        if not hasattr(self, "session_start_time") or self.session_start_time is None:
            self.session_start_time = time.time()
            self.action_count = 0
            self.fatigue_level = 0.0
            return
        elapsed_h = (time.time() - self.session_start_time) / 3600.0
        self.fatigue_level = min(0.82, 0.05 * elapsed_h + 0.001 * self.action_count)

    def _get_fatigue_factor(self) -> float:
        self._update_fatigue()
        return getattr(self, "fatigue_level", 0.0)

    @property
    def _fatigue_factor(self):
        def _g(): return self._get_fatigue_factor()
        return _g

    async def think_before_action(self, importance: str = "normal"):
        """#251: thinking pauses before important actions (login etc), fatigue aware."""
        self.action_count += 1
        self._update_fatigue()
        fat = self.fatigue_level
        b = (1100, 3000) if importance == "critical" else (400, 1300)
        await self.think(int(b[0]*(1+fat*0.5)), int(b[1]*(1+fat*0.9)))

    async def simulate_distraction(self, max_seconds: float = 0.7):
        """#251 / #178 distraction before commit: realistic user distraction patterns.
        Simulates common real-user behaviors: checking clock, tab hesitation,
        looking away, micro-scroll, cursor drift, etc.
        """
        self._update_fatigue()
        if self.realism_level < 1:
            await asyncio.sleep(0.05)
            return

        distraction_type = self.rng.choice([
            "idle_stare", "cursor_drift", "micro_scroll",
            "tab_hesitation", "clock_check", "re_read"
        ])

        duration = self.rng.uniform(0.15, max_seconds * 0.6)
        # Fatigue increases distraction duration
        duration *= (1 + self.fatigue_level * 0.4)

        if distraction_type == "idle_stare":
            # User just pauses, looking at screen
            await asyncio.sleep(duration)

        elif distraction_type == "cursor_drift":
            # Mouse drifts slightly while user is distracted
            cx, cy = self.last_mouse_pos
            drift_x = self.rng.randint(-40, 40)
            drift_y = self.rng.randint(-30, 30)
            await self.move_mouse_naturally(cx + drift_x, cy + drift_y, speed="slow")
            await asyncio.sleep(duration * 0.5)

        elif distraction_type == "micro_scroll":
            # Small scroll up/down while losing focus
            try:
                direction = self.rng.choice([-1, 1])
                amount = self.rng.randint(20, 80) * direction
                await self.page.mouse.wheel(0, amount)
            except Exception:
                pass
            await asyncio.sleep(duration * 0.4)

        elif distraction_type == "tab_hesitation":
            # Brief pause as if considering switching tabs
            await asyncio.sleep(duration * 0.3)
            # Maybe move mouse toward top of page (tab bar area)
            if self.rng.random() < 0.4:
                cx, cy = self.last_mouse_pos
                await self.move_mouse_naturally(
                    cx + self.rng.randint(-100, 100),
                    self.rng.randint(5, 30),
                    speed="slow"
                )
                await asyncio.sleep(duration * 0.3)
                # Move back
                await self.move_mouse_naturally(cx, cy, speed="slow")

        elif distraction_type == "clock_check":
            # Very brief pause, like glancing at clock/phone
            await asyncio.sleep(self.rng.uniform(0.1, 0.3))

        elif distraction_type == "re_read":
            # Scroll back slightly as if re-reading
            try:
                await self.page.mouse.wheel(0, -self.rng.randint(30, 100))
            except Exception:
                pass
            await asyncio.sleep(duration * 0.5)

    async def type_like_human(self, selector: str, text: str, mistake_rate: float = 0.025):
        """Type with realistic speed, variable rhythm, and occasional corrections.
        Uses human_click for natural mouse approach to input (continuity + realism).
        """
        # Use human_click (which does tracked move + click) instead of direct page.click
        # This ensures mouse pos updated and no teleport jump (#24 #101 continuity)
        await self.human_click(selector)
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
                # P2 #115: richer realistic correction patterns (word-level deletes, varied hesitation,
                # multi-backspace, retype pauses) matching human typing error distributions.
                wrong = self.rng.choice("abcdefghijklmnopqrstuvwxyz")
                await self.page.type(selector, wrong, delay=self.rng.uniform(25, 80))
                await asyncio.sleep(self.rng.uniform(0.18, 0.42))
                # 1-3 backspaces with human-like rhythm (fatigue aware but simple here)
                n_back = 1 if self.rng.random() < 0.7 else (2 if self.rng.random() < 0.8 else 3)
                for b in range(n_back):
                    await self.page.keyboard.press("Backspace")
                    await asyncio.sleep(self.rng.uniform(0.08, 0.22) if b > 0 else 0.12)
                # Hesitation / "oops" pause, occasional re-mistake or just continue
                if self.rng.random() < 0.35:
                    await asyncio.sleep(self.rng.uniform(0.25, 0.65))
                    if self.rng.random() < 0.15:  # rare second correction pass
                        await self.page.keyboard.press("Backspace")
                        await asyncio.sleep(self.rng.uniform(0.1, 0.3))
                await asyncio.sleep(self.rng.uniform(0.12, 0.28))

            delay = self.rng.uniform(28, 145)
            await self.page.type(selector, char, delay=delay)

            if i > 0 and i % 12 == 0 and self.rng.random() < 0.3:
                await asyncio.sleep(self.rng.uniform(0.35, 0.75))

    async def _bezier_curve(self, start: Tuple[float, float], end: Tuple[float, float], steps: int = 25):
        """Generate points along a more natural cubic-ish Bézier with controlled wobble + ease.
        P2 realism (#160 #144 #108): non-linear t (ease-in-out) distributes points to simulate
        natural acceleration/deceleration (human motor + typical OS pointer accel curves).
        Real OS accel is driver-level; we match observed event density/timing + wobble.
        Combined with sin-based delay in caller for velocity profile.
        """
        points = []
        # Primary control (mid)
        control_x = (start[0] + end[0]) / 2 + self.rng.uniform(-55, 55)
        control_y = (start[1] + end[1]) / 2 + self.rng.uniform(-35, 35)
        # Slight secondary influence for cubic flavor / overshoot tendency
        control2_x = (start[0] * 0.3 + end[0] * 0.7) + self.rng.uniform(-25, 25)
        control2_y = (start[1] * 0.3 + end[1] * 0.7) + self.rng.uniform(-20, 20)

        def _ease(t: float) -> float:
            # Cubic ease-in-out for accel/decel point spacing (more points mid-gesture? no:
            # ease makes slower near ends => denser points at start/end for natural stop)
            return t*t*(3-2*t)

        for i in range(steps + 1):
            t = i / steps
            te = _ease(t)  # eased t for natural accel feel
            # Quadratic base + small cubic blend for natural S-curve feel
            qx = (1 - te) ** 2 * start[0] + 2 * (1 - te) * te * control_x + te ** 2 * end[0]
            qy = (1 - te) ** 2 * start[1] + 2 * (1 - te) * te * control_y + te ** 2 * end[1]
            # blend in second control slightly near end
            blend = te * 0.25
            x = (1 - blend) * qx + blend * ((1 - te) * control2_x + te * end[0])
            y = (1 - blend) * qy + blend * ((1 - te) * control2_y + te * end[1])

            wobble_x = self.rng.uniform(-2.3, 2.3) * (1 - abs(t - 0.5) * 1.15)
            wobble_y = self.rng.uniform(-1.7, 1.7) * (1 - abs(t - 0.5) * 1.15)

            points.append((x + wobble_x, y + wobble_y))

        return points

    async def move_mouse_naturally(self, x: int, y: int, speed: str = "normal"):
        """Move mouse using improved Bézier curves with natural acceleration and micro-corrections.
        Uses authoritative self.last_mouse_pos + JS sync for true continuity across gestures.
        No more reset on every call (#24, #101 fixed).

        Perf fix (#45): batched JS-executed path (single evaluate + page MouseEvent dispatch
        with exact original timings) replaces 25-42 sequential CDP `page.mouse.move()` calls per gesture.
        Only 1 CDP `mouse.move` at the very end to keep Playwright's internal mouse position model in sync
        for subsequent .down()/.up() etc. Human-likeness 100% preserved (same points, wobbles, easing,
        event sequence and timing from the page's POV).
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
            self._log(f"mouse pos eval non-fatal (using tracked): {e}")

        base_steps = 22 if speed == "normal" else 10
        max_steps = 42 if speed == "normal" else 20
        # Perf: fewer steps when realism reduced
        if self.realism_level <= 1:
            steps = self.rng.randint(max(3, base_steps//2), max(5, max_steps//2))
        else:
            steps = self.rng.randint(base_steps, max_steps)
        points = await self._bezier_curve((current_x, current_y), (x, y), steps)

        if not points:
            await self._record_mouse_position(x, y)
            return

        # Precompute exact same delay schedule as the original per-CDP version for identical human feel
        path_data = []
        for i, (px, py) in enumerate(points):
            progress = (i + 1) / len(points)
            base_delay = 0.008 if speed == "normal" else 0.004
            delay = base_delay + (math.sin(progress * math.pi) * 0.018)
            path_data.append({"x": float(px), "y": float(py), "delay": float(delay)})

        # Batched JS path (#45): 1 evaluate round-trip runs the full multi-step gesture inside the page
        # using real MouseEvents + window.mouse* updates at the precise human-like delays.
        # No more per-point CDP chatter / round-trips. Fallback preserves old behavior if JS eval fails.
        try:
            await self.page.evaluate(
                """
                async (path) => {
                    for (const p of path) {
                        const x = p.x;
                        const y = p.y;
                        const d = (typeof p.delay === 'number') ? p.delay : 0;
                        const evt = new MouseEvent('mousemove', {
                            clientX: Math.round(x),
                            clientY: Math.round(y),
                            bubbles: true,
                            cancelable: false,
                            view: window
                        });
                        document.dispatchEvent(evt);
                        if (typeof window !== 'undefined') {
                            window.mouseX = Math.round(x);
                            window.mouseY = Math.round(y);
                        }
                        if (d > 0) {
                            await new Promise(r => setTimeout(r, Math.max(1, d * 1000)));
                        }
                    }
                    return path.length;
                }
                """,
                path_data
            )
        except Exception as e:
            # Rare fallback (e.g. navigation edge or test fakes): original CDP loop (still correct)
            self._log(f"JS mouse path non-fatal (fallback to CDP loop for gesture): {e}")
            for px, py in points:
                await self.page.mouse.move(px, py)
                progress = (points.index((px, py)) + 1) / len(points)
                base_delay = 0.008 if speed == "normal" else 0.004
                delay = base_delay + (math.sin(progress * math.pi) * 0.018)
                await asyncio.sleep(delay)

        # micro correction (final CDP mouse.move also serves as the single sync of Playwright mouse state)
        if self.rng.random() < 0.65:
            await asyncio.sleep(self.rng.uniform(0.025, 0.07))
            final_x = x + self.rng.randint(-4, 4)
            final_y = y + self.rng.randint(-3, 3)
            await self.page.mouse.move(final_x, final_y)  # syncs Playwright internal cursor for .down/.up/clicks
            await self._record_mouse_position(final_x, final_y)
        else:
            final_x, final_y = points[-1]
            await self.page.mouse.move(final_x, final_y)  # 1 CDP call: keeps PW mouse model consistent (key to low chattiness)
            await self._record_mouse_position(final_x, final_y)

    async def human_click(self, selector: str = None, x: int = None, y: int = None):
        """Human-like click. Always maintains mouse position continuity (no teleport to 0,0).
        Uses tracked pos for bare clicks; records after action (#24 #101).
        """
        # #251 automatic think for critical selectors
        if selector and any(k in (selector or "").lower() for k in ["submit", "login", "send", "save", "post", "confirm", "button"]):
            try:
                await self.think_before_action("critical")
            except Exception:
                pass
        did_move = False
        if selector:
            try:
                box = await self.page.query_selector(selector)
                if box:
                    box_info = await box.bounding_box()
                    if box_info:
                        target_x = box_info["x"] + box_info["width"] * self.rng.uniform(0.2, 0.8)
                        target_y = box_info["y"] + box_info["height"] * self.rng.uniform(0.2, 0.8)
                        await self.move_mouse_naturally(int(target_x), int(target_y))
                        did_move = True
            except Exception as e:
                self._log(f"non-fatal error (was silent): {e}")
        elif x is not None and y is not None:
            await self.move_mouse_naturally(x, y)
            did_move = True

        await asyncio.sleep(self.rng.uniform(0.04, 0.12))

        # Click at/near current tracked position (never hard 0,0 which broke continuity)
        cx, cy = self.last_mouse_pos
        if self.rng.random() < 0.08:
            # occasional small natural offset for click variety (still continuous)
            click_x = cx + self.rng.randint(-4, 4)
            click_y = cy + self.rng.randint(-3, 3)
            await self.page.mouse.click(click_x, click_y)
            await self._record_mouse_position(click_x, click_y)
        else:
            await self.page.mouse.down()
            await asyncio.sleep(self.rng.uniform(0.03, 0.08))
            await self.page.mouse.up()
            # position unchanged; ensure recorded (in case first bare click)
            await self._record_mouse_position(cx, cy)

    async def human_right_click(self, selector: str = None, x: int = None, y: int = None):
        """#229 minimal realistic right-click / context menu simulation (opt-in, high-value for human mimic).
        Natural mouse approach (reuses move continuity) then right button click + brief hold/pause as if reviewing menu.
        Does not auto-choose menu item (caller can follow up if needed).
        """
        # #251 think if critical context? rare for right, but consistent
        if selector and any(k in (selector or "").lower() for k in ["submit", "login", "send"]):
            try:
                await self.think_before_action("normal")
            except Exception:
                pass
        did_move = False
        if selector:
            try:
                box = await self.page.query_selector(selector)
                if box:
                    box_info = await box.bounding_box()
                    if box_info:
                        target_x = box_info["x"] + box_info["width"] * self.rng.uniform(0.25, 0.75)
                        target_y = box_info["y"] + box_info["height"] * self.rng.uniform(0.25, 0.75)
                        await self.move_mouse_naturally(int(target_x), int(target_y))
                        did_move = True
            except Exception:
                pass
        elif x is not None and y is not None:
            await self.move_mouse_naturally(x, y)
            did_move = True

        await asyncio.sleep(self.rng.uniform(0.06, 0.15))
        cx, cy = self.last_mouse_pos
        # Right click via Playwright mouse (button support)
        await self.page.mouse.click(cx, cy, button="right")
        await self._record_mouse_position(cx, cy)
        # Realistic pause as if context menu rendered / user considering
        await asyncio.sleep(self.rng.uniform(0.25, 0.85))
        if self.realism_level >= 2 and self.rng.random() < 0.3:
            # occasional small corrective move away after right-click (human "whoops" or inspect)
            await self.move_mouse_naturally(cx + self.rng.randint(-20, 40), cy + self.rng.randint(-15, 25))

    async def simulate_changed_mind(self, probability: float = 0.09) -> bool:
        """#235: simulate realistic "I changed my mind" abort / re-plan (opt-in, call before high-stakes commit).
        Returns True if action was "aborted" (caller should re-think or skip).
        Uses back-scroll re-read (existing pattern), occasional Escape, or distraction + think.
        Ties into fatigue/distraction from #251 for more natural abort rate.
        """
        self._update_fatigue()
        fat = getattr(self, "fatigue_level", 0.0)
        eff_prob = min(0.35, probability + fat * 0.25)  # fatigued users change mind more
        if self.realism_level < 1 or self.rng.random() >= eff_prob:
            return False
        # Choose abort flavor
        if self.rng.random() < 0.45:
            # back up / re-read (like scroll backticks)
            try:
                await self.page.mouse.wheel(0, -self.rng.randint(60, 140))
            except Exception:
                pass
        elif self.rng.random() < 0.35 and self.realism_level >= 2:
            try:
                await self.page.keyboard.press("Escape")
            except Exception:
                pass
        else:
            await self.simulate_distraction(0.4)
        await self.think(250, int(900 * (1 + fat * 0.4)))
        return True

    async def scroll_naturally(self, total_pixels: int = 400, direction: str = "down"):
        """Scroll in small, human-like increments with occasional re-read backticks (realism).
        P2 perf (#81 #108 #153 #89 #123): batched JS wheel/scrollBy sequence (1 evaluate)
        replaces N sequential page.mouse.wheel CDP calls + roundtrips. Same timing, events,
        backticks. Falls back to per-call for safety. Fewer steps + longer sleeps in light realism.
        """
        # Perf: reduce steps/chatter in low realism (addresses tiny sleeps + CDP in CI/light)
        if self.realism_level <= 1:
            steps = self.rng.randint(2, 5)
        else:
            steps = self.rng.randint(5, 12)
        base_step = total_pixels // steps
        scroll_actions = []
        did_back = False

        def _ease(t: float) -> float:
            # ease-in-out cubic for scroll velocity profile (#144): slower start/end, faster mid-scroll
            return t*t*(3-2*t)

        for i in range(steps):
            progress = (i + 0.5) / max(1, steps)
            e = _ease(progress)
            # vary amount slightly by eased progress for natural accel feel
            var_factor = 0.7 + 0.6 * e
            variation = int(self.rng.randint(-30, 45) * var_factor)
            amount = int((base_step + variation) * (0.85 + 0.3 * e))
            if direction == "up":
                amount = -amount
            delay_after = self.rng.uniform(0.6, 1.4) if self.rng.random() < 0.22 else self.rng.uniform(0.12, 0.38)
            if self.realism_level <= 1:
                delay_after = max(0.05, delay_after * 0.4)  # consolidate for perf
            # bias mid delays shorter for accel profile
            if 0.3 < progress < 0.7:
                delay_after *= 0.75
            scroll_actions.append({"dy": amount, "delay": delay_after, "is_back": False})

            # Pre-plan occasional backtick into sequence (no separate CDP after)
            if not did_back and self.rng.random() < 0.08 and i > 1 and i < steps-2:
                back = int(amount * 0.3) if amount > 0 else int(amount * 0.25)
                back_d = self.rng.uniform(0.15, 0.35)
                if self.realism_level <= 1:
                    back_d = 0.05
                scroll_actions.append({"dy": -back if amount > 0 else abs(back), "delay": back_d, "is_back": True})
                did_back = True

        # Batched JS scroll (P2 CDP reduction): single evaluate runs all wheel dispatches + scrollBy + precise delays inside browser
        # Eliminates per-step CDP roundtrips for scroll sequences (matches mouse batching #45 pattern)
        try:
            await self.page.evaluate(
                """
                async (actions) => {
                    for (const a of actions) {
                        const dy = a.dy || 0;
                        const d = (typeof a.delay === 'number') ? a.delay : 0;
                        // Perform actual scroll
                        window.scrollBy(0, dy);
                        // Dispatch synthetic wheel for any page listeners / fingerprint parity
                        const evt = new WheelEvent('wheel', {
                            deltaX: 0,
                            deltaY: dy,
                            bubbles: true,
                            cancelable: false
                        });
                        document.dispatchEvent(evt);
                        if (d > 0) {
                            await new Promise(r => setTimeout(r, Math.max(1, d * 1000)));
                        }
                    }
                    return actions.length;
                }
                """,
                scroll_actions
            )
            return
        except Exception as e:
            # Fallback preserves exact prior behavior + CDP calls if JS batch fails (nav etc)
            self._log(f"JS scroll batch non-fatal (fallback per-CDP): {e}")

        # Fallback CDP loop (original)
        for a in scroll_actions:
            await self.page.mouse.wheel(0, a["dy"])
            if a["delay"] > 0:
                await asyncio.sleep(a["delay"])

    async def simulate_reading(self, duration_seconds: float = 8.0, content_factor: float = 1.0):
        """Simulate a person reading a page.
        P2 #131: duration scaled by content_factor (e.g. longer text / more scrolls => longer realistic read time).
        Proxy: caller can pass based on page length or prior scroll total.
        P2 #131 fix: Added variable pause ranges and occasional re-read patterns for realism.
        """
        scaled = duration_seconds * max(0.4, min(2.5, content_factor))
        end_time = time.monotonic() + scaled

        while time.monotonic() < end_time:
            scroll_amount = self.rng.randint(120, 280)
            await self.scroll_naturally(scroll_amount)
            # P2 #131: Variable pause ranges instead of fixed (1.2, 3.8)
            # Real readers vary pace: fast skimming vs slow careful reading
            reading_pace = self.rng.choice(["fast", "normal", "slow", "re-read"])
            if reading_pace == "fast":
                pause = self.rng.uniform(0.5, 1.5)
            elif reading_pace == "slow":
                pause = self.rng.uniform(3.0, 6.0)
            elif reading_pace == "re-read":
                # Occasional re-read: scroll back and pause longer
                await self.page.mouse.wheel(0, -self.rng.randint(80, 200))
                pause = self.rng.uniform(2.0, 5.0)
            else:
                pause = self.rng.uniform(1.2, 3.8) * max(0.6, min(1.8, content_factor))
            await asyncio.sleep(pause)

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
            self._log(f"viewport_jitter non-fatal: {e}")

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
                    self._log(f"search selector try non-fatal: {e}")
                    continue

            await self.page.keyboard.type(query)
            await asyncio.sleep(0.6)
            await self.page.keyboard.press("Enter")
            return True

        except Exception:
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
        if self.realism_level < 1:
            # P2: skip micro entirely in CI/low-resource (prefer pure sleeps/think)
            patterns = [p for p in patterns if "micro" not in getattr(p, "__name__", "")] or patterns[1:]

        while time.monotonic() < end_time:
            pattern = self.rng.choice(patterns)
            # Always produce and await a coroutine for safety
            coro = pattern()
            await coro

            if self.rng.random() < 0.3:
                break

    async def micro_movement_while_waiting(self, duration_ms: int = 800):
        """Small, natural mouse movements while waiting. Uses + updates authoritative tracked pos + JS sync.
        P2 perf: early return (skip all CDP moves) when realism_level low (CI/headless/light_mode).
        """
        if self.realism_level < 1:
            # Skip micro-movements entirely in low-resource/CI (no mouse.move CDP spam)
            await asyncio.sleep(max(0.001, min(duration_ms / 2000.0, 0.05)))
            return
        end_time = time.monotonic() + (duration_ms / 1000)

        while time.monotonic() < end_time:
            try:
                dx = self.rng.randint(-25, 25)
                dy = self.rng.randint(-18, 18)

                # Prefer Python tracked for continuity; fallback JS or default
                cx, cy = self.last_mouse_pos
                try:
                    jpos = await self.page.evaluate("() => ({x: window.mouseX || 0, y: window.mouseY || 0})")
                    jx, jy = jpos.get("x", 0), jpos.get("y", 0)
                    if jx > 50 and jy > 50:
                        cx, cy = jx, jy
                except Exception:
                    pass

                new_x = cx + dx
                new_y = cy + dy

                await self.page.mouse.move(new_x, new_y)
                await self._record_mouse_position(new_x, new_y)
            except Exception as e:
                self._log(f"non-fatal error (was silent): {e}")

            sleep_base = 0.45 if self.realism_level >= 3 else (0.18 if self.realism_level >= 2 else 0.05)
            await asyncio.sleep(self.rng.uniform(sleep_base, sleep_base + 0.15))
            # P2 #89 #123: larger sleeps + light skip reduces event-loop wakeups / CDP during idle waits

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
                # Use tracked pos + small correction move; record for continuity
                base_x, base_y = self.last_mouse_pos
                corr_x = base_x + self.rng.randint(-30, 30)
                corr_y = base_y + self.rng.randint(-20, 20)
                await self.page.mouse.move(corr_x, corr_y)
                await self._record_mouse_position(corr_x, corr_y)
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
            self._log(f"shortcut non-fatal: {shortcut} {e}")

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
        """Approximate small-screen / mobile-like interaction patterns even on desktop (#291).
        Now uses and updates tracked mouse pos for continuity.
        """
        if action == "tap":
            await asyncio.sleep(self.rng.uniform(0.15, 0.35))
            try:
                # Prefer tracked last pos (continuity) over stale JS default
                base_x, base_y = self.last_mouse_pos
                try:
                    jpos = await self.page.evaluate("() => ({x: window.mouseX||0, y: window.mouseY||0})")
                    jx = jpos.get("x", 0)
                    jy = jpos.get("y", 0)
                    if jx > 50 and jy > 50:
                        base_x, base_y = jx, jy
                except Exception:
                    pass
                tap_x = base_x + self.rng.randint(-12, 12)
                tap_y = base_y + self.rng.randint(-8, 8)
                await self.page.mouse.move(tap_x, tap_y)
                await self._record_mouse_position(tap_x, tap_y)
                await self.page.mouse.down()
                await asyncio.sleep(0.08)
                await self.page.mouse.up()
                if self.rng.random() < 0.2:
                    await asyncio.sleep(0.12)
                    tap2_x = tap_x + self.rng.randint(-5, 5)
                    tap2_y = tap_y + self.rng.randint(-3, 3)
                    await self.page.mouse.move(tap2_x, tap2_y)
                    await self._record_mouse_position(tap2_x, tap2_y)
                    await self.page.mouse.down()
                    await asyncio.sleep(0.05)
                    await self.page.mouse.up()
                    await self._record_mouse_position(tap2_x, tap2_y)
            except Exception:
                pass
