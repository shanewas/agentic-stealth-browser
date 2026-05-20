"""
Agentic Browser - Main class
Combines stealth, human behavior, and session management

DX improvements (Phase 8 / DX Agent):
- debug=True mode with full fingerprint/headers/patches dump (#265 "debug mode")
- Platform presets support including "linkedin_2026" (#288)
- get_health_status() + enhanced stealth_status MCP (#281)
- apply_preset() and launch(preset=...) helpers
- Integrated with AuditLogger + new DebugReporter
"""

import asyncio
import random
import time
from pathlib import Path
from typing import Optional, Dict, Any, Union

from playwright.async_api import async_playwright, BrowserContext

from stealth.advanced_stealth import get_stealth_script, StealthConfig
from stealth.tls_fingerprint import get_tls_manager, Region
from recovery.anti_block_orchestrator import AntiBlockOrchestrator
from behavior.human_behavior import HumanBehavior
from behavior.orchestration import BehaviorOrchestrator
from sessions.session_manager import SessionManager
from proxy.proxy_manager import ProxyManager
from stealth.headers import get_extra_http_headers
from audit.logger import AuditLogger, DebugReporter
from scraping.scraper import StealthScraper
from ai.ai_hooks import AIHooks
from sessions.cookie_manager import CookieManager, SessionOrchestrator
from production.rate_limiter import domain_limiter, account_limiter

# Metrics wiring (perf/observability fixes #239, #294, #102 context)
try:
    from production.metrics import metrics as global_metrics
except Exception:
    global_metrics = None


# DX Presets (#288) - high value for operators
from stealth.presets import (
    get_preset, PlatformPreset, build_launch_config_from_preset, 
    PRESETS, list_presets, LINKEDIN_2026
)


class AgentBrowser:
    """
    High-undetectability browser for autonomous agents.
    Supports multiple isolated sessions and deep human mimicry.

    DX Features:
        browser = AgentBrowser()
        await browser.launch(debug=True, preset="linkedin_2026")
        await browser.debug_report(print_report=True)   # dumps exact TLS + headers + patches
        health = browser.get_health_status()
    """
    
    def __init__(self, session_name: Optional[str] = None, anonymous: bool = False):
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

        # Wire metrics (eliminates dead hasattr paths, enables observability)
        self.metrics = global_metrics  # shared global by default; can be replaced with per-instance if needed


        # DX state
        self.debug_mode: bool = False
        self.debug_reporter: Optional[DebugReporter] = None
        self.tls_manager = None
        self._current_preset: Optional[PlatformPreset] = None
        self._launch_config: Dict[str, Any] = {}
    
    async def launch(
        self,
        headless: bool = True,
        slow_mo: int = 0,
        headed: bool = False,
        debug: bool = False,
        preset: Optional[str] = None,
        region: Optional[str] = None,
    ):
        """Launch browser with full stealth + human behavior + DX features.

        New DX parameters (Phase 8):
            debug: Enable verbose fingerprint/headers/patches dumps (#265). Use with debug_report().
            preset: One of "linkedin_2026", "amazon", "upwork_2026", "cloudflare", "general" etc. (#288)
            region: Override TLS region ("us", "japan", "eu", "korea", "global")

        See also: apply_preset(), get_health_status(), debug_report()
        """
        pw = await async_playwright().start()
        
        user_data = Path(self.session["user_data_dir"])
        user_data.mkdir(parents=True, exist_ok=True)
        
        extra_headers = get_extra_http_headers()

        # === DX: Apply preset first (overrides region/headers/behavior defaults) ===
        tls_region_str = "global"
        if preset:
            self._current_preset = get_preset(preset)
            cfg = build_launch_config_from_preset(self._current_preset, extra_headers)
            self._launch_config = cfg
            tls_region_str = cfg.get("tls_region", "global")
            extra_headers = cfg.get("extra_http_headers", extra_headers)
            # Locale/timezone from preset take precedence for realism
            locale = cfg.get("locale", "en-US")
            tz = cfg.get("timezone_id", "America/New_York")
        else:
            locale = "en-US"
            tz = "Asia/Tokyo"

        # Allow explicit region override (takes precedence)
        if region:
            tls_region_str = region

        # TLS Fingerprint spoofing (region-aware, now preset-aware)
        self.tls_manager = get_tls_manager(tls_region_str, self.session.get("name"))
        self.tls_manager.log_fingerprint_choice()
        tls_args = self.tls_manager.get_launch_args()

        base_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--no-sandbox",
        ]
        all_args = list(set(base_args + tls_args))

        # Proxy support (wired from proxy_manager if pre-configured).
        # Enables residential proxies from launch and sets foundation for recovery rotation (#38, #16, #99).
        # Rotation during active session still requires relaunch (see future work for context recreation).
        proxy_settings = None
        if self.proxy_manager and getattr(self.proxy_manager, "current_config", None):
            proxy_settings = self.proxy_manager.get_playwright_proxy_args()

        launch_kwargs = {
            "user_data_dir": str(user_data),
            "headless": not headed if headed else headless,
            "slow_mo": slow_mo,
            "viewport": {"width": 1366, "height": 768},
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "locale": "en-US",
            "timezone_id": "Asia/Tokyo",
            "extra_http_headers": extra_headers,
            "args": all_args,
        }
        if proxy_settings:
            launch_kwargs["proxy"] = proxy_settings

        
        # Use the prepared launch_kwargs (includes proxy if set, and preset-driven locale/tz)
        # Note: we set locale/tz in the dict using the computed values (preset-aware)
        launch_kwargs["locale"] = locale
        launch_kwargs["timezone_id"] = tz
        self.browser = await pw.chromium.launch_persistent_context(**launch_kwargs)
        
        # Create main page (critical fix)
        self.page = await self.browser.new_page()
        self.context = self.browser  # alias for clarity (BUG-03 naming hygiene)
        
        # Inject advanced stealth on the page
        await self.page.add_init_script(get_stealth_script(fingerprint_seed=f"{self.session.get('name', 'default')}-stealth-v3"))
        
        # Create human behavior controller + orchestrator
        self.human = HumanBehavior(self.page)
        self.orchestrator = BehaviorOrchestrator(self.human)
        
        # Initialize audit logging
        self.logger = AuditLogger(self.session["name"])
        
        # === DX: DebugReporter + immediate dumps on debug=True (#265) ===
        self.debug_reporter = DebugReporter(
            self.logger,
            self.tls_manager,
            extra_headers
        )
        self.debug_reporter.record_patch("advanced_stealth.get_stealth_script", {
            "patches": ["webdriver", "hardware", "canvas", "webgl", "audio", "chrome_runtime"]
        })
        
        if debug or (self._current_preset and "debug" in str(self._current_preset.notes).lower()):
            self.debug_mode = True
            self.logger.enable_debug_mode()
            # Dump the exact things operators asked for in #265
            self.debug_reporter.dump_fingerprint()
            self.debug_reporter.dump_headers()
            self.debug_reporter.dump_patches()
            self.logger.log_action("debug_mode_activated_on_launch", {
                "preset": self._current_preset.name if self._current_preset else None,
                "region": tls_region_str
            })
        
        # Initialize scraper
        self.scraper = StealthScraper(self.page, self.human, self.orchestrator)
        
        # Initialize AI hooks (disabled by default)
        self.ai = AIHooks(provider="none")
        
        # Initialize Anti-Block Recovery Orchestrator
        self.recovery = AntiBlockOrchestrator(
            browser=self.browser,
            session_manager=self.session_manager,
            proxy_manager=self.proxy_manager,
            page_getter=lambda: self.page
        )
        
        # If preset had recovery overrides, we could propagate here (future enhancement)
        if self._current_preset:
            # For now, log the recommendation so recovery can be manually tuned or extended
            self.logger.log_action("preset_applied", {
                "preset": self._current_preset.name,
                "recommended_retries": self._current_preset.recovery_max_retries,
                "notes": self._current_preset.notes[:200]
            })

        # Store playwright instance for proper cleanup
        self._pw = pw

        return self.browser
    
    async def apply_preset(self, name: str) -> Dict[str, Any]:
        """
        Apply (or re-apply) a platform preset at runtime.
        For full effect on TLS/headers/locale, re-launch is recommended.
        Updates recovery hints and behavior recommendations immediately.
        """
        preset = get_preset(name)
        self._current_preset = preset
        self._launch_config = build_launch_config_from_preset(preset, get_extra_http_headers())
        
        if self.logger:
            self.logger.log_action("preset_applied_runtime", {
                "name": preset.name,
                "tls_region": preset.tls_region.value,
                "behavior": preset.behavior_intensity,
                "warm_up": preset.warm_up
            })
        
        # If we have a recovery orchestrator, we could dynamically adjust strategy (future)
        return {
            "status": "success",
            "preset": preset.name,
            "description": preset.description,
            "recommendation": "For maximum effect (TLS + headers), call launch(..., preset=...) or relaunch.",
            "notes": preset.notes[:300]
        }
    
    def get_health_status(self) -> Dict[str, Any]:
        """
        Operator-friendly health / status snapshot (#281).
        Used by MCP stealth_status and for dashboards / debugging loops.
        """
        status = {
            "launched": bool(self.browser and self.page),
            "session": self.session.get("name") if self.session else None,
            "debug_mode": self.debug_mode,
            "current_preset": self._current_preset.name if self._current_preset else None,
            "current_url": None,
            "tls_region": None,
            "fingerprint_profile": None,
            "recovery_attempts": 0,
            "cookie_health": "unknown",
            "recent_blocks": 0,
            "last_action": None,
        }
        
        if self.page:
            try:
                status["current_url"] = getattr(self.page, "url", None)
            except Exception:
                pass
        
        if self.tls_manager:
            try:
                prof = self.tls_manager.get_profile()
                status["tls_region"] = self.tls_manager.region.value
                status["fingerprint_profile"] = prof.get("name")
            except Exception:
                pass
        
        if self.logger:
            try:
                recent = self.logger.get_recent_actions(10)
                status["last_action"] = recent[-1]["action"] if recent else None
                status["recent_blocks"] = sum(1 for a in recent if "BLOCK" in a.get("action", "").upper())
            except Exception:
                pass
        
        if self.recovery and hasattr(self.recovery, "recovery_history"):
            try:
                status["recovery_attempts"] = sum(self.recovery.recovery_history.values())
            except Exception:
                pass
        
        try:
            ch = asyncio.get_event_loop().run_until_complete(self.get_cookie_health()) if self.cookie_manager else {"status": "no_manager"}
            status["cookie_health"] = ch.get("status", "ok")
        except Exception:
            status["cookie_health"] = "check_failed"
        
        return status
    
    async def debug_report(self, print_report: bool = False, full: bool = True) -> Dict[str, Any]:
        """
        #265: Return (and optionally pretty-print) the exact fingerprint, headers, and patches dump.
        This is the primary developer/operator tool for understanding what stealth was applied.
        """
        if not self.debug_reporter:
            # Create on demand
            headers = get_extra_http_headers()
            self.debug_reporter = DebugReporter(
                self.logger or AuditLogger(self.session.get("name", "debug")),
                self.tls_manager,
                headers
            )
        
        if full:
            report = self.debug_reporter.full_debug_report(include_recent_logs=True)
        else:
            report = {
                "tls_fingerprint": self.debug_reporter.dump_fingerprint(),
                "http_headers": self.debug_reporter.dump_headers(),
                "stealth_patches": self.debug_reporter.dump_patches(),
            }
        
        if print_report:
            self.debug_reporter.print_human_report(report)
        
        # Also log to audit for post-mortem
        if self.logger:
            self.logger.log_action("debug_report_generated", {"print": print_report, "full": full})
        
        return report
    
    # === Rest of original methods (unchanged except minor guards) ===
    
    async def goto(self, url: str, warm_up: bool = True, max_retries: int = 3):
        """Navigate with session warming and basic error recovery"""
        if not self.browser:
            raise RuntimeError("Browser not launched. Call launch() first.")
        
        for attempt in range(max_retries):
            try:
                if warm_up and "linkedin.com" in url and attempt == 0:
                    await self.page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
                    await self.human.scroll_naturally(280)
                    await self.human.think(900, 1600)
                
                await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await self.human.think(500, 1200)
                return True
                
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                await self.human.think(2000, 4000)
                continue
        
        return False
    
    async def safe_goto(self, url: str, warm_up: bool = True, platform: str = "unknown"):
        """Navigate with full anti-block recovery."""
        if not self.browser:
            raise RuntimeError("Browser not launched. Call launch() first.")
        
        if not self.recovery:
            return await self.goto(url, warm_up=warm_up)

        async def _navigate():
            if warm_up and "linkedin.com" in url:
                await self.page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
                await self.human.scroll_naturally(280)
                await self.human.think(900, 1600)
            
            response = await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
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
            if self.logger:
                self.logger.log_error("safe_goto_failed", str(e), {"url": url, "platform": platform})
            return False

    async def load_cookies(self, cookies_path: str):
        """[DEPRECATED] Legacy cookie loader. Use load_cookies_from_file()."""
        import json
        if not self.browser:
            raise RuntimeError("Browser not launched. Call launch() first.")

        with open(cookies_path, "r") as f:
            cookies = json.load(f)

        for cookie in cookies:
            if "sameSite" in cookie:
                if cookie["sameSite"] not in ["None", "Lax", "Strict"]:
                    cookie["sameSite"] = "None"
            try:
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
            if self.logger:
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
            if self.logger:
                self.logger.log_error("safe_type_failed", str(e), {"selector": selector})
            return False

    async def human_scroll_and_read(self, duration_seconds: float = 6.0):
        if self.human:
            await self.human.simulate_reading(duration_seconds)
        else:
            if self.page:
                await self.page.mouse.wheel(0, self.rng.randint(200, 400))
            await asyncio.sleep(1.5)

    async def load_cookies_from_file(self, cookies_path: str) -> Dict[str, Any]:
        if not self.browser:
            raise RuntimeError("Browser not launched. Call launch() first.")

        self.cookie_manager = CookieManager(self.browser)
        result = await self.cookie_manager.load_cookies(cookies_path)

        if result.get("status") == "success":
            self.session_orchestrator = SessionOrchestrator()

        return result

    async def get_cookie_health(self) -> Dict[str, Any]:
        if not self.cookie_manager:
            return {"status": "no_manager", "message": "No cookie manager initialized"}

        return await self.cookie_manager.get_cookie_health()

    async def warm_up_before_work(self, intensity: str = "medium") -> Dict[str, Any]:
        if not self.human:
            return {"status": "error", "message": "Human behavior not initialized"}

        try:
            if intensity == "light":
                await self.human.scroll_naturally(200)
                await self.human.think(800, 1500)
            elif intensity == "medium":
                await self.human.scroll_naturally(350)
                await self.human.think(1200, 2200)
                await self.human.micro_movement_while_waiting(600)
                if self.rng.random() < 0.4:
                    await self.human.random_idle_behavior(3.0)
            elif intensity == "heavy":
                await self.human.simulate_reading(6.0)
                await self.human.apply_viewport_jitter()
                if self.rng.random() < 0.5:
                    await self.human.fake_search_action()
                await self.human.random_idle_behavior(4.0)

            # DX: record warm-up in debug
            if self.debug_reporter and self.debug_mode:
                self.debug_reporter.record_patch("warm_up", {"intensity": intensity})

            return {"status": "success", "intensity": intensity, "preset": self._current_preset.name if self._current_preset else None}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def ensure_cookies_fresh(self, max_age_hours: int = 8) -> Dict[str, Any]:
        if not self.cookie_manager:
            return {"status": "no_manager"}

        return await self.cookie_manager.ensure_fresh_cookies(max_age_hours)

    async def screenshot_on_error(self, name: str = "error"):
        if not self.page:
            return None
        try:
            import os
            os.makedirs("screenshots", exist_ok=True)
            filename = f"screenshots/{name}_{int(time.time())}.png"
            await self.page.screenshot(path=filename, full_page=True)
            return filename
        except Exception as e:
            print(f"Screenshot failed: {e}")
            return None

    async def profile_action(self, name: str, action_func):
        start = time.time()
        try:
            result = await action_func()
            duration = time.time() - start
            
            if self.metrics:
                self.metrics.record_time(name, duration)
            
            print(f"[Profile] {name}: {duration:.2f}s")
            return result
        except Exception as e:
            duration = time.time() - start
            print(f"[Profile] {name} FAILED after {duration:.2f}s: {e}")
            raise

    async def safe_goto_with_rate_limit(self, url: str, domain: str = None, account: str = None, **kwargs):
        if domain is None:
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
            except:
                domain = "unknown"

        if account:
            wait_time = await account_limiter.wait_if_needed(account, domain)
        else:
            wait_time = await domain_limiter.wait_if_needed(domain)

        if wait_time > 0:
            print(f"[Rate Limit] Waited {wait_time:.1f}s for {domain}")

        if self.metrics:
            self.metrics.increment("requests_total")

        return await self.safe_goto(url, **kwargs)

    def set_rate_limit(self, domain: str, requests_per_minute: int = 8, cooldown_seconds: int = 60):
        from production.rate_limiter import RateLimitConfig
        config = RateLimitConfig(
            requests_per_minute=requests_per_minute,
            cooldown_seconds=cooldown_seconds
        )
        domain_limiter.set_limit(domain, config)

    async def close(self):
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

            self.human = None
            self.orchestrator = None
            self.recovery = None
        except Exception:
            pass

    async def __aenter__(self):
        """Support for `async with AgentBrowser(...) as browser:` usage (#292)."""
        if not self.browser:
            await self.launch()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False


# Convenience: expose preset list at module level for docs / CLI
__all__ = [
    "AgentBrowser", "get_preset", "list_presets", "PlatformPreset", 
    "LINKEDIN_2026", "PRESETS"
]
