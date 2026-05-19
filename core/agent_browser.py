"""
Agentic Browser - Main class
Combines stealth, human behavior, and session management
"""

import asyncio
from pathlib import Path
from typing import Optional
from playwright.async_api import async_playwright, BrowserContext

from stealth.advanced_stealth import get_stealth_script, StealthConfig
from behavior.human_behavior import HumanBehavior
from behavior.orchestration import BehaviorOrchestrator
from sessions.session_manager import SessionManager
from proxy.proxy_manager import ProxyManager


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
        self.context: Optional[BrowserContext] = None
        self.browser = None
    
    async def launch(self, headless: bool = True, slow_mo: int = 0):
        """Launch browser with full stealth + human behavior"""
        pw = await async_playwright().start()
        
        user_data = Path(self.session["user_data_dir"])
        user_data.mkdir(parents=True, exist_ok=True)
        
        self.browser = await pw.chromium.launch_persistent_context(
            user_data_dir=str(user_data),
            headless=headless,
            slow_mo=slow_mo,
            viewport={"width": 1366, "height": 768},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="Asia/Tokyo",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
            ],
        )
        
        # Inject advanced stealth
        await self.browser.add_init_script(get_stealth_script())
        
        # Create human behavior controller + orchestrator
        self.human = HumanBehavior(self.browser)
        self.orchestrator = BehaviorOrchestrator(self.human)
        
        return self.browser
    
    async def goto(self, url: str, warm_up: bool = True):
        """Navigate with optional session warming"""
        if not self.browser:
            raise RuntimeError("Browser not launched. Call launch() first.")
        
        if warm_up and "linkedin.com" in url:
            # Warm up session naturally
            await self.browser.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
            await self.human.scroll_naturally(300)
            await self.human.think(800, 1800)
        
        await self.browser.goto(url, wait_until="domcontentloaded")
        await self.human.think(600, 1500)
    
    async def close(self):
        if self.browser:
            await self.browser.close()
