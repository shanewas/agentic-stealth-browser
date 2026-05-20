"""
Agentic Browser - Main class
Combines stealth, human behavior, and session management
"""

import asyncio
from pathlib import Path
from typing import Optional
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


class AgentBrowser:
    """
    High-undetectability browser for autonomous agents.
    Supports multiple isolated sessions and deep human mimicry.
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
        self.browser = None
    
    async def launch(self, headless: bool = True, slow_mo: int = 0):
        """Launch browser with full stealth + human behavior"""
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

        
        self.browser = await pw.chromium.launch_persistent_context(
            user_data_dir=str(user_data),
            headless=headless,
            slow_mo=slow_mo,
            viewport={"width": 1366, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="Asia/Tokyo",
            extra_http_headers=extra_headers,
            args=all_args,
        )
        
        # Create main page (critical fix)
        self.page = await self.browser.new_page()
        
        # Inject advanced stealth on the page
        await self.page.add_init_script(get_stealth_script())
        
        # Create human behavior controller + orchestrator
        self.human = HumanBehavior(self.page)
        self.orchestrator = BehaviorOrchestrator(self.human)
        
        # Initialize audit logging
        self.logger = AuditLogger(self.session["name"])
        
        # Initialize scraper
        self.scraper = StealthScraper(self.page, self.human, self.orchestrator)
        
        # Initialize AI hooks (disabled by default)
        self.ai = AIHooks(provider="none")
        
        # Initialize Anti-Block Recovery Orchestrator (Phase 1 improvement)
        self.recovery = AntiBlockOrchestrator(
            browser=self.browser,
            session_manager=self.session_manager,
            proxy_manager=self.proxy_manager
        )

        return self.browser
    
    async def goto(self, url: str, warm_up: bool = True, max_retries: int = 3):
        """Navigate with session warming and basic error recovery"""
        if not self.browser:
            raise RuntimeError("Browser not launched. Call launch() first.")
        
        for attempt in range(max_retries):
            try:
                if warm_up and "linkedin.com" in url and attempt == 0:
                    # Natural session warming
                    await self.page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
                    await self.human.scroll_naturally(280)
                    await self.human.think(900, 1600)
                
                await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await self.human.think(500, 1200)
                return True
                
            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                await self.human.think(2000, 4000)  # Wait before retry
                continue
        
        return False
    
    async def safe_goto(self, url: str, warm_up: bool = True, platform: str = "unknown"):
        """
        Navigate with full anti-block recovery.
        Uses the AntiBlockOrchestrator for intelligent detection and recovery.
        Recommended for production / high-reliability use.
        """
        if not self.browser:
            raise RuntimeError("Browser not launched. Call launch() first.")
        
        if not self.recovery:
            # Fallback to normal goto if recovery not initialized
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
            self.logger.log_error("safe_goto_failed", str(e), {"url": url, "platform": platform})
            return False


    async def load_cookies(self, cookies_path: str):
        """
        Load cookies from a JSON file (exported from real browser).
        This is the most reliable way to bypass login + Cloudflare on sites like Upwork.
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
                await self.browser.context.add_cookies([cookie])
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
                    url=self.browser.url if hasattr(self.browser, 'url') else ""
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
                    url=self.browser.url if hasattr(self.browser, 'url') else ""
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
            # Fallback
            await self.page.mouse.wheel(0, self.rng.randint(200, 400))
            await asyncio.sleep(1.5)


    async def load_cookies_from_file(self, cookies_path: str) -> Dict[str, Any]:
        """Load cookies using the resilient CookieManager."""
        if not self.browser:
            raise RuntimeError("Browser not launched. Call launch() first.")

        self.cookie_manager = CookieManager(self.browser)
        result = await self.cookie_manager.load_cookies(cookies_path)

        if result.get("status") == "success":
            # Also initialize session orchestrator
            self.session_orchestrator = SessionOrchestrator()

        return result

    async def get_cookie_health(self) -> Dict[str, Any]:
        """Check health of current cookies."""
        if not self.cookie_manager:
            return {"status": "no_manager", "message": "No cookie manager initialized"}

        return await self.cookie_manager.get_cookie_health()

    async def close(self):
        if self.browser:
            await self.browser.close()
