"""
Agentic Browser - Main class
Combines stealth, human behavior, and session management
"""

import asyncio
import random
import time
import os  # for env vars in launch (also used by other methods)
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from playwright.async_api import async_playwright, BrowserContext

from stealth.advanced_stealth import get_stealth_script, StealthConfig
from stealth.tls_fingerprint import get_tls_manager
from recovery.anti_block_orchestrator import AntiBlockOrchestrator
from behavior.human_behavior import HumanBehavior
from behavior.orchestration import BehaviorOrchestrator
from sessions.session_manager import SessionManager
from proxy.proxy_manager import ProxyManager
from stealth.headers import get_extra_http_headers
from audit.logger import AuditLogger
from scraping.scraper import StealthScraper
from ai.ai_hooks import AIHooks
from sessions.cookie_manager import CookieManager, SessionOrchestrator
from production.rate_limiter import domain_limiter, account_limiter, DomainRateLimiter, AccountRateLimiter
from production.metrics import metrics, MetricsCollector

# Persona system scaffolding (#109) - foundation only. Canonical in stealth/profiles.py
from stealth.profiles import Persona, DeviceProfile, DEFAULT_PERSONA, get_persona, list_personas


class AgentBrowser:
    """
    High-undetectability browser for autonomous agents.
    Supports multiple isolated sessions and deep human mimicry.

    P1 #79/#87: Each instance now carries its own rate_limiter and metrics (isolated by default).
    Pass shared AccountRateLimiter/MetricsCollector to constructor for coordinated "fleet" use.
    light_mode (#174/#113): reduces launch/warm-up cost/latency when True (skips heavy warm-ups + auto light downgrade in warm_up_before_work).
    """

    def __init__(
        self,
        session_name: Optional[str] = None,
        anonymous: bool = False,
        persona: Optional[Persona] = None,
        rate_limiter: Optional[AccountRateLimiter] = None,
        metrics_collector: Optional[MetricsCollector] = None,
        light_mode: bool = False,
    ):
        self.session_manager = SessionManager()
        self.session = self.session_manager.create_session(session_name, anonymous)
        self.proxy_manager = ProxyManager()
        self.human = None
        self.orchestrator = None
        self.logger = None
        self.scraper = None
        self.ai = None
        self.recovery = None
        self.cookie_manager = None
        self.session_orchestrator = None
        self.context: Optional[BrowserContext] = None
        self.browser = None   # Playwright BrowserContext (persistent) — see launch() docstring
        self.page = None      # Playwright Page (main) — use this for most page actions
        self.rng = random.Random()  # for warm_up, profile, screenshots, fallbacks (BUG-01 fix)
        self.persona = persona or DEFAULT_PERSONA  # Persona foundation integration

        # P1 #79/#87 (global singletons + multi-instance isolation):
        # Each AgentBrowser gets private rate limiting + metrics by default.
        # This prevents cross-talk between concurrent independent sessions/agents.
        # Advanced: pass the *same* limiter/metrics to multiple browsers for shared policy.
        self.rate_limiter: AccountRateLimiter = rate_limiter or AccountRateLimiter()
        self.metrics: MetricsCollector = metrics_collector or MetricsCollector()
        self.account_id: Optional[str] = None
        self.light_mode: bool = light_mode  # #174/#113/#92/#84 perf P1 final closer: light_mode now auto-wires to recovery so True reduces expensive content() calls + heavy detection
    
    async def launch(self, headless: bool = True, slow_mo: int = 0, headed: bool = False, persona: Optional[Persona] = None, light_mode: Optional[bool] = None):
        """Launch browser with full stealth + human behavior.
        
        IMPORTANT NAMING (to avoid integration bugs like BUG-02/BUG-03):
            - self.browser  -> Playwright BrowserContext (persistent context)
            - self.page     -> Playwright Page (main page created after launch)
            - self.context  -> alias for self.browser (for clarity in some paths)

        Consumers (including MCP wrappers) must use self.page for page methods
        (goto, content, inner_text, click, etc.). Never call them on self.browser.

        Preferred usage (issue #292):
            async with AgentBrowser() as browser:
                await browser.safe_goto(...)
                ...
            # automatic reliable cleanup even on exceptions

        Args:
            headless: Run without browser window (default True)
            slow_mo: Slow down actions by milliseconds
            headed: Force headed mode even if headless=True (for debugging)
            light_mode: Enable light mode (#174/#113) to reduce launch/warm-up cost/latency (skips heavy warm-ups + auto-downgrades warm_up_before_work).
            Proxy support: configure via self.proxy_manager.create_decodo_config(...) *before* calling launch()
            (or pass preconfigured ProxyManager in advanced usage); it is now wired into launch_persistent_context (#14, #29).
        """
        if persona is not None:
            self.persona = persona
        if light_mode is not None:
            self.light_mode = light_mode

        pw = await async_playwright().start()
        
        user_data = Path(self.session["user_data_dir"])
        user_data.mkdir(parents=True, exist_ok=True)
        
        extra_headers = get_extra_http_headers()

        # TLS Fingerprint spoofing (region-aware)
        self.tls_manager = get_tls_manager("global", self.session.get("name"))
        self.tls_manager.log_fingerprint_choice()
        tls_args = self.tls_manager.get_launch_args()

        base_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--no-sandbox",
        ]
        all_args = list(set(base_args + tls_args))

        # Persona integration hook (foundation only for #109)
        # Uses dataclass overrides for consistent fingerprint. No other side effects yet.
        p_over = getattr(self, "persona", None).to_launch_overrides() if getattr(self, "persona", None) else {}
        vp = p_over.get("viewport", {"width": 1366, "height": 768})
        ua = p_over.get("user_agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
        loc = p_over.get("locale", "en-US")
        tz = p_over.get("timezone_id", "America/New_York")

        # Proxy wiring (#14, #29): if caller pre-configured ProxyManager (e.g. create_decodo_config before launch),
        # pass the Playwright proxy dict (socks5 supported) so real traffic uses residential proxy.
        # Foundation for rotation (#38/#16). get_playwright_proxy_args is no longer dead code.
        proxy_args = getattr(self.proxy_manager, "get_playwright_proxy_args", lambda: {})()
        launch_proxy = proxy_args if proxy_args else None

        self.browser = await pw.chromium.launch_persistent_context(
            user_data_dir=str(user_data),
            headless=not headed if headed else headless,
            slow_mo=slow_mo,
            viewport=vp,
            user_agent=ua,
            locale=loc,
            timezone_id=tz,
            extra_http_headers=extra_headers,
            args=all_args,
            proxy=launch_proxy,
        )
        
        # Per-session stable fingerprint seed (canvas/WebGL noise + fonts) for consistency across reloads
        # and variation between sessions. Addresses #150 (re-apply), #94, #210 etc.
        session_name = (self.session or {}).get("name", "default-session")
        fp_seed = f"agentic-{session_name}-canvas-v4"

        # Inject on *context* (not page) so init script runs for:
        # - the initial page, all subsequently created pages (new_page etc.)
        # - every navigation, reload, and subframe
        # This ensures stealth patches (canvas/Offscreen/WebGL/font) are re-applied after nav/reload (#150)
        # and use the per-session seed for stable but unique fp.
        await self.browser.add_init_script(get_stealth_script(fingerprint_seed=fp_seed))
        
        # Create main page (critical fix)
        self.page = await self.browser.new_page()
        self.context = self.browser  # alias for clarity (BUG-03 naming hygiene)
        
        # Create human behavior controller + orchestrator
        self.human = HumanBehavior(self.page)
        self.orchestrator = BehaviorOrchestrator(self.human)

        # Seed JS mouse tracker from Python last_pos for continuity (#24 #101).
        # Must be after add_init_script + page ready. Safe best-effort.
        try:
            await self.human.initialize_mouse_tracker()
        except Exception:
            pass
        
        # Initialize audit logging
        self.logger = AuditLogger(self.session["name"])
        
        # Initialize scraper
        self.scraper = StealthScraper(self.page, self.human, self.orchestrator)
        
        # Initialize AI hooks (disabled by default)
        self.ai = AIHooks(provider="none")
        
        # Initialize Anti-Block Recovery Orchestrator (Phase 1 improvement)
        # BUG-04 fix: pass page getter so content-based block detection (CAPTCHA, LinkedIn security, etc.) works
        self.recovery = AntiBlockOrchestrator(
            browser=self.browser,
            session_manager=self.session_manager,
            proxy_manager=self.proxy_manager,
            page_getter=lambda: self.page,
            light_mode=getattr(self, "light_mode", None)  # ultra-narrow absolute final: light_mode on AgentBrowser automatically reduces expensive recovery detection (content calls, heavy path) for #92/#84 + #174
        )

        # Wire active session for #90 P1: auto cookie/session cleanup on ACCOUNT_RESTRICTION
        if self.recovery:
            self.recovery.set_current_session_name(self.session.get("name") if self.session else None)

        # Store playwright instance for proper cleanup
        self._pw = pw

        return self.browser
    
    async def goto(self, url: str, warm_up: bool = True, max_retries: int = 3):
        """Navigate with session warming and basic error recovery.

        Respects self.light_mode (#174/#113) to skip warm-up costs/latency (pre-warm, post-goto think, retry think) matching safe_goto for full launch/warm-up perf reduction.
        """
        if not self.browser:
            raise RuntimeError("Browser not launched. Call launch() first.")
        
        for attempt in range(max_retries):
            try:
                if warm_up and "linkedin.com" in url and attempt == 0 and not getattr(self, "light_mode", False):  # ultra-narrow absolute final closer for ONLY #174 and #113: legacy goto path now skips warm-up cost/latency under light_mode (matches safe_goto + class/launch doc promises for launch/warm-up perf)
                    # Natural session warming
                    await self.page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
                    await self.human.scroll_naturally(280)
                    await self.human.think(900, 1600)
                
                await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
                if not getattr(self, "light_mode", False):  # absolute final polish for #174/#113 launch/warm-up cost: also skip post-goto think delay in legacy goto (now fully matches safe_goto light_mode behavior)
                    await self.human.think(500, 1200)
                return True
                
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                if not getattr(self, "light_mode", False):  # ultra-narrow absolute final closer for ONLY #174 and #113: skip retry think latency cost too in legacy goto under light_mode (completes full launch/warm-up cost reduction, no artificial delays remain)
                    await self.human.think(2000, 4000)  # Wait before retry
                continue
        
        return False
    
    async def safe_goto(self, url: str, warm_up: bool = True, platform: str = "unknown"):
        """
        Navigate with full anti-block recovery.
        Uses the AntiBlockOrchestrator for intelligent detection and recovery.
        Recommended for production / high-reliability use.
        Respects self.light_mode to skip warm-ups per #174.
        """
        if not self.browser:
            raise RuntimeError("Browser not launched. Call launch() first.")
        
        if not self.recovery:
            # Fallback to normal goto if recovery not initialized
            return await self.goto(url, warm_up=warm_up)

        async def _navigate():
            if warm_up and "linkedin.com" in url and not getattr(self, "light_mode", False):  # ultra-narrow absolute final closer for ONLY #174 and #113: safe_goto now skips linkedin warm-up cost/latency under light_mode (matches legacy goto + doc promises for launch/warm-up perf)
                await self.page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
                await self.human.scroll_naturally(280)
                await self.human.think(900, 1600)
            
            response = await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if not getattr(self, "light_mode", False):  # ultra-narrow absolute final closer for ONLY #174 and #113: safe_goto skips post-goto think under light_mode completing full warm-up cost reduction for launch perf (#174 #113)
                await self.human.think(500, 1200)
            return response

        try:
            result = await self.recovery.execute_with_recovery(
                func=_navigate,
                platform=platform,
                url=url
            )
            return True
        except Exception as e:
            self.logger.log_error("safe_goto_failed", str(e), {"url": url, "platform": platform})
            return False




    async def load_cookies(self, cookies_path: str):
        """
        [DEPRECATED] Legacy cookie loader.
        Use load_cookies_from_file(..., encryption_key=...) + CookieManager for resilient + secure (#82) loading.
        Kept for backward compatibility; fixed .context access (BUG-03).
        """
        import json
        if not self.browser:
            raise RuntimeError("Browser not launched. Call launch() first.")

        with open(cookies_path, "r") as f:
            cookies = json.load(f)

        # Convert to Playwright format if needed
        for cookie in cookies:
            if "sameSite" in cookie:
                # Playwright expects "None", "Lax", or "Strict"
                if cookie["sameSite"] not in ["None", "Lax", "Strict"]:
                    cookie["sameSite"] = "None"
            try:
                # self.browser is the BrowserContext (naming kept for backward compat)
                await self.browser.add_cookies([cookie])
            except Exception as e:
                print(f"Warning: Could not add cookie {cookie.get('name')}: {e}")

        return {"status": "success", "cookies_loaded": len(cookies)}




    async def safe_click(self, selector: str, platform: str = "unknown"):
        """Click with recovery logic."""
        if not self.browser:
            raise RuntimeError("Browser not launched.")

        async def _click():
            await self.page.click(selector, timeout=10000)
            await self.human.think(300, 800)

        try:
            if self.recovery:
                await self.recovery.execute_with_recovery(
                    func=_click,
                    platform=platform,
                    url=getattr(self.page, 'url', '') if self.page else ''
                )
            else:
                await _click()
            return True
        except Exception as e:
            self.logger.log_error("safe_click_failed", str(e), {"selector": selector})
            return False

    async def safe_type(self, selector: str, text: str, platform: str = "unknown"):
        """Type with human-like behavior and recovery."""
        if not self.browser:
            raise RuntimeError("Browser not launched.")

        async def _type():
            await self.human.type_like_human(selector, text)

        try:
            if self.recovery:
                await self.recovery.execute_with_recovery(
                    func=_type,
                    platform=platform,
                    url=getattr(self.page, 'url', '') if self.page else ''
                )
            else:
                await _type()
            return True
        except Exception as e:
            self.logger.log_error("safe_type_failed", str(e), {"selector": selector})
            return False


    async def human_scroll_and_read(self, duration_seconds: float = 6.0):
        """Simulate natural reading behavior using the enhanced human behavior layer."""
        if self.human:
            await self.human.simulate_reading(duration_seconds)
        else:
            # Fallback (defensive after BUG-01 fix)
            if self.page:
                await self.page.mouse.wheel(0, self.rng.randint(200, 400))
            await asyncio.sleep(1.5)


    async def load_cookies_from_file(self, cookies_path: str, encryption_key: Optional[str] = None) -> Dict[str, Any]:
        """Load cookies using the resilient CookieManager.

        Supports encryption_key for P1 #82 secure (encrypted) cookie loads.
        Pass the same secret used with save_cookies_to_file(encrypt=True).
        """
        if not self.browser:
            raise RuntimeError("Browser not launched. Call launch() first.")

        self.cookie_manager = CookieManager(self.browser)
        result = await self.cookie_manager.load_cookies(cookies_path, encryption_key=encryption_key)

        if result.get("status") == "success":
            # Also initialize session orchestrator
            self.session_orchestrator = SessionOrchestrator()

        return result

    async def get_cookie_health(self) -> Dict[str, Any]:
        """Check health of current cookies."""
        if not self.cookie_manager:
            return {"status": "no_manager", "message": "No cookie manager initialized"}

        return await self.cookie_manager.get_cookie_health()

    async def save_cookies_to_file(self, cookies_path: str, encrypt: bool = False, encryption_key: Optional[str] = None) -> Dict[str, Any]:
        """Save cookies to file (plain or encrypted) via CookieManager.

        P1 #82: Use encrypt=True + any secret key for at-rest Fernet encryption + integrity protection.
        Complements the #90 cleanup flow: store good sessions securely, auto-clean bad ones.
        """
        if not self.browser:
            raise RuntimeError("Browser not launched. Call launch() first.")

        if not self.cookie_manager:
            self.cookie_manager = CookieManager(self.browser)
        else:
            # ensure latest context wiring for cookie ops
            self.cookie_manager.browser_context = self.browser

        return await self.cookie_manager.save_cookies_to_file(
            cookies_path, encrypt=encrypt, encryption_key=encryption_key
        )


    async def warm_up_before_work(self, intensity: str = "medium") -> Dict[str, Any]:
        """Perform natural warm-up before real automation work.

        Respects self.light_mode (#174/#113): auto-downgrades to 'light' to reduce launch/warm-up cost and latency.
        Now uses profile_action around mouse/click/hover/scroll actions for timing + visibility (#169).
        Best-effort: sub-failures logged (via profile + AuditLogger) but do not silently claim full success
        if critical warm-up gestures all failed. Returns partial/degraded status when needed.
        """
        if not self.human:
            return {"status": "error", "message": "Human behavior not initialized"}

        attempted = 0
        succeeded = 0
        errors = []

        def _should_profile(act_name: str) -> bool:
            # profile the ones that involve clicks/hovers/mouse moves (core of #169 complaint)
            return any(k in act_name.lower() for k in ("mouse", "click", "hover", "micro", "scroll", "idle", "read", "search", "jitter"))

        async def _run_step(name: str, coro_func):
            """Run a warm-up step, wrapped in profile_action when appropriate, best-effort."""
            nonlocal attempted, succeeded
            attempted += 1
            try:
                if _should_profile(name) and hasattr(self, "profile_action"):
                    # profile_action will print timing or "FAILED" + re-raise; we catch for best-effort
                    result = await self.profile_action(f"warmup_{name}", coro_func)
                else:
                    result = await coro_func()
                succeeded += 1
                return result
            except Exception as e:
                err_msg = f"{name}: {str(e)}"
                errors.append(err_msg)
                if self.logger:
                    try:
                        self.logger.log_error("warm_up_step_failed", str(e), {"step": name, "intensity": intensity})
                    except Exception:
                        pass
                # best-effort: continue; profile already logged the failure visibly
                return None

        try:
            if getattr(self, "light_mode", False):
                intensity = "light"

            if intensity == "light":
                await _run_step("scroll_light", lambda: self.human.scroll_naturally(200))
                await _run_step("think_light", lambda: self.human.think(800, 1500))

            elif intensity == "medium":
                await _run_step("scroll_med", lambda: self.human.scroll_naturally(350))
                await _run_step("think_med", lambda: self.human.think(1200, 2200))
                await _run_step("micro_move", lambda: self.human.micro_movement_while_waiting(600))
                if self.rng.random() < 0.4:
                    await _run_step("random_idle", lambda: self.human.random_idle_behavior(3.0))

            elif intensity == "heavy":
                await _run_step("simulate_reading", lambda: self.human.simulate_reading(6.0))
                await _run_step("viewport_jitter", lambda: self.human.apply_viewport_jitter())
                if self.rng.random() < 0.5:
                    await _run_step("fake_search", lambda: self.human.fake_search_action())
                await _run_step("random_idle_heavy", lambda: self.human.random_idle_behavior(4.0))

            status = "success"
            if attempted > 0 and succeeded == 0:
                status = "degraded"  # all critical steps (esp mouse/click profile ones) failed; do not pretend warmed (#169)
            elif attempted > 0 and succeeded < attempted:
                status = "partial"

            result = {"status": status, "intensity": intensity, "steps_attempted": attempted, "steps_succeeded": succeeded}
            if errors:
                result["errors"] = errors[:3]  # limit
            if self.logger:
                try:
                    self.logger.log_action("warm_up_complete", result)
                except Exception:
                    pass
            return result
        except Exception as e:
            # top level unexpected
            if self.logger:
                try:
                    self.logger.log_error("warm_up_failed", str(e), {"intensity": intensity})
                except Exception:
                    pass
            return {"status": "error", "message": str(e), "steps_attempted": attempted, "steps_succeeded": succeeded}

    async def ensure_cookies_fresh(self, max_age_hours: int = 8) -> Dict[str, Any]:
        """Ensure cookies are fresh before long operations."""
        if not self.cookie_manager:
            return {"status": "no_manager"}
        return await self.cookie_manager.refresh_cookies_if_needed(max_age_hours)

    async def cleanup_compromised_session(self, remove_dir: bool = False) -> Dict[str, Any]:
        """#90 P1: Invalidate current session cookies + mark as compromised.

        Call this after ACCOUNT_RESTRICTION (or any detected compromise) to avoid
        reusing tainted cookies. High-impact security/recovery hygiene.
        """
        name = None
        result = {"status": "noop"}
        if self.session:
            name = self.session.get("name")
            if self.session_manager:
                result = self.session_manager.cleanup_session(name, remove_dir=remove_dir)

        if self.cookie_manager:
            try:
                c = await self.cookie_manager.clear_cookies()
                result["cookie_clear"] = c
            except Exception as e:
                result["cookie_clear"] = {"status": "error", "message": str(e)}

        # Direct clear on context too (defense in depth)
        if self.browser:
            try:
                await self.browser.clear_cookies()
                result["context_direct_clear"] = True
            except Exception:
                pass

        result["session"] = name
        result["status"] = "cleaned"
        return result


    async def screenshot_on_error(self, name: str = "error"):
        """Take screenshot on error for visual debugging."""
        if not self.page:
            return None
        try:
            import os
            os.makedirs("screenshots", exist_ok=True)
            filename = f"screenshots/{name}_{int(time.time)}.png"
            await self.page.screenshot(path=filename, full_page=True)
            return filename
        except Exception as e:
            print(f"Screenshot failed: {e}")
            return None


    async def profile_action(self, name: str, action_func):
        """Profile the execution time of an action.
        Failures are printed + re-raised (no silent success) -- used in warm-up for #169 visibility.
        """
        start = time.time()
        try:
            result = await action_func()
            duration = time.time() - start
            
            # Record in per-instance metrics (P1 #79 isolation; always present now)
            self.metrics.record_time(name, duration)
            
            print(f"[Profile] {name}: {duration:.2f}s")
            return result
        except Exception as e:
            duration = time.time() - start
            print(f"[Profile] {name} FAILED after {duration:.2f}s: {e}")
            if getattr(self, "logger", None):
                try:
                    self.logger.log_error("profile_action_failed", str(e), {"name": name, "duration": duration})
                except Exception:
                    pass
            raise


    async def safe_goto_with_rate_limit(self, url: str, domain: str = None, account: str = None, **kwargs):
        """Navigate with rate limiting protection (now per-instance for #79/#87 isolation)."""
        if domain is None:
            try:
                domain = urlparse(url).netloc
            except:
                domain = "unknown"

        # Use *this instance's* rate limiter (isolated from other AgentBrowser instances)
        rl = self.rate_limiter
        effective_account = account or self.account_id or (self.session.get("name") if self.session else None) or "default"
        wait_time = await rl.wait_if_needed(effective_account, domain)

        if wait_time > 0:
            print(f"[Rate Limit] Waited {wait_time:.1f}s for {domain}")

        # Record the request in per-instance metrics
        self.metrics.increment("requests_total")

        return await self.safe_goto(url, **kwargs)

    def set_rate_limit(self, domain: str, requests_per_minute: int = 8, cooldown_seconds: int = 60, account: Optional[str] = None):
        """Configure custom rate limit for a domain (applied to this instance's limiter)."""
        from production.rate_limiter import RateLimitConfig
        config = RateLimitConfig(
            requests_per_minute=requests_per_minute,
            cooldown_seconds=cooldown_seconds
        )
        # Per-instance: target the sub-limiter for the given (or default) account
        dl = self.rate_limiter.get_limiter(account or "default")
        dl.set_limit(domain, config)

    async def close(self):
        """Close the browser, page, and underlying Playwright instance.

        This method is idempotent and safe to call multiple times.
        """
        try:
            if self.page:
                try:
                    await self.page.close()
                except Exception:
                    pass
                self.page = None

            if self.browser:
                try:
                    await self.browser.close()
                except Exception:
                    pass
                self.browser = None
                self.context = None

            if hasattr(self, '_pw') and self._pw:
                try:
                    await self._pw.stop()
                except Exception:
                    pass
                self._pw = None

            # Best-effort cleanup of other resources
            self.human = None
            self.orchestrator = None
            self.recovery = None
        except Exception:
            # Never let close() itself raise — we want reliable cleanup
            pass

    async def __aenter__(self):
        """Support for `async with AgentBrowser(...) as browser:` usage.

        This implements GitHub issue #292 (proper context manager for reliable cleanup).
        """
        if not self.browser:
            # Default launch parameters — callers can still call launch() explicitly first
            await self.launch(light_mode=getattr(self, "light_mode", None))  # ultra-narrow absolute final closer for ONLY #174 and #113: explicit light_mode wiring on implicit launch() path guarantees launch/warm-up cost reduction applies for context-manager users
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Guarantee cleanup even if an exception occurs inside the `async with` block."""
        await self.close()
        return False  # do not suppress exceptions
