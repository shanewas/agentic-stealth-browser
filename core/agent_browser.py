"""
Agentic Browser - Main class
Combines stealth, human behavior, and session management
"""

import asyncio
import enum
import random
import time
import os  # for env vars in launch (also used by other methods)
import atexit  # #161 graceful shutdown on process exit
import threading
import weakref
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import urlparse
import json
import urllib.request
from playwright.async_api import async_playwright, BrowserContext, Browser

from stealth.advanced_stealth import get_stealth_script, check_stealth_compatibility
from stealth.tls_fingerprint import get_tls_manager
from recovery.anti_block_orchestrator import AntiBlockOrchestrator
from behavior.human_behavior import HumanBehavior
from behavior.orchestration import BehaviorOrchestrator
from sessions.session_manager import SessionManager
from proxy.proxy_manager import ProxyManager

# P3: New module integrations
from core.account_health import AccountHealth
from core.account_warming import AccountWarmer
from core.connection_pool import ConnectionPool
from behavior.adaptive_tuner import BehaviorTuner
from stealth.headers import get_extra_http_headers
from audit.logger import AuditLogger
from scraping.scraper import StealthScraper
from ai.ai_hooks import AIHooks
from sessions.cookie_manager import CookieManager, SessionOrchestrator
from production.rate_limiter import AccountRateLimiter, ToolRateLimiter
from production.metrics import MetricsCollector

# Persona system scaffolding (#109) - foundation only. Canonical in stealth/profiles.py
from stealth.profiles import Persona, DEFAULT_PERSONA


def robots_allows(robots_txt: str, url: str, user_agent: str = "*") -> bool:
    """Return True if robots_txt permits user_agent to fetch url. Empty/unparseable => allowed."""
    from urllib.robotparser import RobotFileParser

    rp = RobotFileParser()
    try:
        rp.parse((robots_txt or "").splitlines())
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True


# Lightweight library-specific exception hierarchy for #249 DX improvement.
# Users can now do: from core.agent_browser import StealthBrowserError, LaunchError, ...
# Base catches all library errors; specific ones for targeted handling.
# Existing raw Playwright/RuntimeError paths remain for compat; new code prefers these.
class StealthBrowserError(Exception):
    """Base exception for all Agentic Stealth Browser library errors (DX #249)."""

    pass


class TeardownMode(enum.Enum):
    """State machine for how close() should release resources (#439).

    Set by launch() / launch_pooled() / attach_over_cdp() exactly once.
    Read by close() exactly once.

    Lifecycle:
        __init__ → None (no browser)
        launch() → LAUNCHED
        launch() with use_pooled_context=True → POOLED
        attach_over_cdp(new_context=True) → ATTACHED_OWNED_CTX
        attach_over_cdp(adopt existing) → ATTACHED_ADOPTED_CTX
        close() → dispatches on this value, then None
    """

    LAUNCHED = "launched"  # Owns the browser process — close it
    POOLED = "pooled"  # Borrowed a context from _BrowserPool — release, don't kill
    ATTACHED_OWNED_CTX = "attached_owned_ctx"  # Attached + created a new context
    ATTACHED_ADOPTED_CTX = "attached_adopted_ctx"  # Attached + adopted user's context


class LaunchError(StealthBrowserError):
    """Raised when browser launch or context creation fails (stealth, proxy, etc.)."""

    pass


class RecoveryError(StealthBrowserError):
    """Raised or catchable during anti-block recovery orchestration."""

    pass


class BlockDetectedError(StealthBrowserError):
    """Explicit signal that a block/challenge was detected (for user catch blocks)."""

    def __init__(
        self,
        block_type: Optional[str] = None,
        platform: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.block_type = block_type
        self.platform = platform
        self.details = details or {}
        msg = (
            f"Block detected: {block_type or 'unknown'} on {platform or 'unknown site'}"
        )
        super().__init__(msg)


class RateLimitError(StealthBrowserError):
    """Raised when rate limiter enforces a wait or limit (informational subclass)."""

    pass


class _BrowserPool:
    """
    Internal minimal optional shared Browser + Context pool (P1 #57/#48/#47).
    Opt-in via AgentBrowser(use_pooled_context=True) or launch(..., use_pooled_context=True).

    Reuses ONE Playwright Browser process + cheap browser.new_context() calls.
    Avoids repeated launch_persistent_context (expensive: full Chromium spawn + profile + stealth injection per instance).

    - When proxy rotation NOT needed (or even when it is, for speed): massive win on startup/memory for 10-50+ concurrent agents.
    - Pooled contexts are lightweight and isolated (own cookies/storage/proxy/viewport per context).
    - NO automatic disk user_data persistence (unlike launch_persistent_context).
      Use cookie load/save, storage_state(), or stick with default (pooled=False) for full profile persistence.
    - Rotation paths in recovery still work: they release old ctx and obtain fresh one from pool.
    - Shared browser stays alive until explicit pool shutdown or process exit.
    - Fully backward compatible: default=False preserves exact prior behavior and persistence.

    Single-process singleton pool (simple, no extra deps).
    """

    _instance: Optional["_BrowserPool"] = None
    _init_lock = threading.Lock()  # thread-safe singleton creation

    def __new__(cls) -> "_BrowserPool":
        with cls._init_lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._pw = None
                cls._instance._browser: Optional[Browser] = None
                cls._instance._lock = asyncio.Lock()
                cls._instance._active_contexts: weakref.WeakSet = weakref.WeakSet()
                cls._instance._headless = True
                cls._instance._launch_args: list = []
        return cls._instance

    async def ensure_browser(
        self, headless: bool = True, args: Optional[list] = None
    ) -> Browser:
        async with self._lock:
            if self._browser is None:
                if self._pw is None:
                    self._pw = await async_playwright().start()
                self._headless = headless
                self._launch_args = args or []
                self._browser = await self._pw.chromium.launch(
                    headless=headless,
                    args=self._launch_args,
                    # proxy not at browser level; per-context below
                )
            return self._browser

    async def create_context(self, **context_options) -> BrowserContext:
        """Create (or conceptually obtain) a fresh isolated context on the shared browser."""
        browser = await self.ensure_browser(
            headless=getattr(self, "_headless", True),
            args=getattr(self, "_launch_args", None),
        )
        # new_context is the cheap/fast path (vs launch_persistent_context)
        ctx = await browser.new_context(**context_options)
        self._active_contexts.add(ctx)  # WeakSet tracks context objects directly
        return ctx

    async def release_context(self, ctx: BrowserContext) -> None:
        """Release a context back (close it; browser stays for reuse)."""
        if ctx in self._active_contexts:
            self._active_contexts.discard(ctx)
        try:
            await ctx.close()
        except Exception:
            pass

    async def shutdown(self) -> None:
        """Full shutdown of shared browser + playwright (call on app exit if using pool)."""
        async with self._lock:
            # close any remaining contexts (WeakSet — already GC'd ones auto-removed)
            for ctx in list(self._active_contexts):
                try:
                    await ctx.close()
                except Exception:
                    pass
            self._active_contexts.clear()
            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._pw:
                try:
                    await self._pw.stop()
                except Exception:
                    pass
                self._pw = None


class AgentBrowser:
    """
    High-undetectability browser for autonomous agents.
    Supports multiple isolated sessions and deep human mimicry.

    P1 #79/#87: Each instance now carries its own rate_limiter and metrics (isolated by default).
    Pass shared AccountRateLimiter/MetricsCollector to constructor for coordinated "fleet" use.
    light_mode (#174/#113): reduces launch/warm-up cost/latency when True (skips heavy warm-ups + auto light downgrade in warm_up_before_work).

    Scalability P1 #57/#48/#47: Optional use_pooled_context=True reuses a shared Browser process + cheap new_context()
    instead of repeated launch_persistent_context. Ideal when proxy/session rotation is not (or rarely) needed.
    Backward compatible: default False keeps full per-instance persistent contexts + disk profiles.
    """

    def __init__(
        self,
        session_name: Optional[str] = None,
        anonymous: bool = False,
        ephemeral: bool = False,  # P2/P3 MVP: throwaway session (auto-tagged + prunable)
        persona: Optional[Persona] = None,
        rate_limiter: Optional[AccountRateLimiter] = None,
        metrics_collector: Optional[MetricsCollector] = None,
        light_mode: bool = False,
        use_pooled_context: bool = False,  # P1 #57/#48/#47: opt-in for shared Browser + new_context reuse (when rotation not required)
        rate_limits: Optional[
            dict
        ] = None,  # #136: tool rate-limit config (e.g. {"tool_calls_per_minute": 30, "total_calls_cap": 600})
        preset: Optional[str] = None,  # #457: forward to implicit launch for CLI etc
        region: Optional[str] = None,
    ):
        self.session_manager = SessionManager()
        self.session = self.session_manager.create_session(
            session_name, anonymous, ephemeral=ephemeral
        )
        self.proxy_manager = ProxyManager()
        self.human = None
        self.orchestrator = None
        self.logger = None
        self.scraper = None
        self.ai = None
        self.recovery = None
        self.cookie_manager = None
        self.session_orchestrator = None
        self.context: Optional[BrowserContext] = (
            None  # Deprecated alias for self.browser (#93). Removed in v2.1.0. Prefer self.browser.
        )
        self.browser_context: Optional[BrowserContext] = (
            None  # Canonical browser context reference (v2.0.0+).
        )
        self.browser = None  # Playwright BrowserContext (persistent or pooled) — see launch() docstring
        self.page = None  # Playwright Page (main) — use this for most page actions
        self._owns_page: bool = (
            False  # #451: do not close user-owned/adopted pages on teardown
        )
        self.rng = (
            random.Random()
        )  # for warm_up, profile, screenshots, fallbacks (BUG-01 fix)
        self.persona = persona or DEFAULT_PERSONA  # Persona foundation integration

        # P1 #79/#87 (global singletons + multi-instance isolation):
        # Each AgentBrowser gets private rate limiting + metrics by default.
        # This prevents cross-talk between concurrent independent sessions/agents.
        # Advanced: pass the *same* limiter/metrics to multiple browsers for shared policy.
        # P2 #97: MetricsCollector is now properly initialized with session_name and correlation_id.
        self.rate_limiter: AccountRateLimiter = rate_limiter or AccountRateLimiter()
        self.metrics: MetricsCollector = metrics_collector or MetricsCollector(
            session_name=session_name or "default"
        )
        self.account_id: Optional[str] = None
        self.light_mode: bool = light_mode  # #174/#113/#92/#84 perf P1 final closer: light_mode now auto-wires to recovery so True reduces expensive content() calls + heavy detection
        self.use_pooled_context: bool = use_pooled_context  # #57/#48/#47 scalability: when True, launch uses shared browser pool instead of per-instance launch_persistent_context
        self._using_pool: bool = False
        self._pooled_ctx_id: Optional[int] = None  # track for release
        self._browser_process = None  # set after launch for PID tracking

        # #439: TeardownMode state machine — None means "no browser to tear down"
        self._teardown_mode: Optional["TeardownMode"] = None

        # #136: Tool-level rate limiter for public API surface (MCP tool calls)
        if rate_limits is not None:
            self._rate_limiter: Optional[ToolRateLimiter] = ToolRateLimiter(
                **rate_limits
            )
        else:
            self._rate_limiter = None

        # P2/P3 DX & Observability (#281, #265, #288): health/status, debug, presets
        self.debug_mode: bool = False
        self.debug_cdp: bool = (
            False  # #377: opt-in CDP remote debugging (localhost-only WS endpoint)
        )
        self.current_preset: Optional[str] = preset
        self.current_region: str = region or "global"
        self.tls_manager: Optional[Any] = None
        self.debug_reporter: Optional[Any] = None
        self._launch_options: Dict[
            str, Any
        ] = {}  # for rotation relaunch preservation (incl. debug/preset/region)
        self._custom_launch_options: Dict[str, Any] = {}  # #143: custom PW launch opts

        # P2 #182: pluggable page_getter for internal decoupling and extensibility (overridable for multi-page, testing, custom routing)
        self._page_getter: Optional[callable] = None

        # #161 P2: graceful shutdown support (atexit + signal friendly)
        self._atexit_registered = False
        self._register_atexit_shutdown()

        # P3: New module integrations
        self.account_health = AccountHealth(account_id=session_name or "default")
        self.account_warming = AccountWarmer(account_id=session_name or "default")
        self.connection_pool = ConnectionPool(max_contexts=5, ttl=300.0)
        self.adaptive_tuner = BehaviorTuner(rng=self.rng)

    @property
    def page_getter(self):
        """Pluggable page acquisition for decoupling (#182, builds on Phase 7 BUG-04).

        Recommended access pattern for extension code, recovery, and internal methods:
            p = browser.page_getter()
            if p:
                await p.goto(...)

        Default: returns self.page (the primary page).
        Can be overridden via assignment or subclass for multi-page workflows (#176),
        mock pages in tests, or custom page routing.

        See docs in launch() and multi-page methods. All new internal call sites use this.
        """
        if self._page_getter is not None:
            return self._page_getter

        def _default():
            return getattr(self, "page", None)

        return _default

    @page_getter.setter
    def page_getter(self, getter):
        """Allow setting custom page_getter callable (must be zero-arg returning page or None)."""
        if getter is not None and not callable(getter):
            raise TypeError("page_getter must be callable or None")
        self._page_getter = getter

    def _register_atexit_shutdown(self):
        """#161: Register atexit handler for graceful close on process exit.

            Uses sync wrapper around async close(). WARNING: atexit is a best-effort
            fallback. Production code MUST use `async with AgentBrowser()` to guarantee
            cleanup. The atexit handler cannot reliably await async cleanup in all
            scenarios (e.g. when a running loop exists, the task is scheduled but not
        awaited before interpreter shutdown).
        """
        if self._atexit_registered:
            return

        def _atexit_cleanup_sync():
            try:
                # If there's a running loop, we cannot safely run async close in it.
                # Best-effort: try to run in a fresh loop. If that fails, log a warning.
                loop = None
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    pass  # no running loop — good, we can create one

                if loop and not loop.is_closed():
                    # There IS a running loop. We can't call asyncio.run() inside it.
                    # Schedule close and log that it may not complete.
                    import logging

                    logger = logging.getLogger("agent_browser.atexit")
                    logger.warning(
                        "atexit: running loop detected — close() scheduled but NOT awaited. "
                        "Use `async with AgentBrowser()` for guaranteed cleanup."
                    )
                    asyncio.create_task(self.close())
                    return

                # No running loop — safe to create one and run close() synchronously.
                try:
                    asyncio.run(self.close())
                except RuntimeError as e:
                    import logging

                    logging.getLogger("agent_browser.atexit").warning(
                        "atexit: asyncio.run(close) failed: %s", e
                    )
                except Exception as e:
                    import logging

                    logging.getLogger("agent_browser.atexit").warning(
                        "atexit: close() failed: %s", e
                    )
            except Exception as e:
                import logging

                logging.getLogger("agent_browser.atexit").warning(
                    "atexit: unexpected error: %s", e
                )

        try:
            atexit.register(_atexit_cleanup_sync)
            self._atexit_registered = True
        except Exception as e:
            import logging

            logging.getLogger("agent_browser.atexit").warning(
                "atexit: registration failed: %s", e
            )

    async def launch(
        self,
        headless: bool = True,
        slow_mo: int = 0,
        headed: bool = False,
        persona: Optional[Persona] = None,
        light_mode: Optional[bool] = None,
        use_pooled_context: Optional[bool] = None,
        resume: bool = False,  # P2: lighter warm-up when resuming from saved sessions
        debug: bool = False,  # P2/P3 DX: enable DebugReporter (#265)
        debug_cdp: bool = False,  # #377: optional CDP attach (remote-debugging on localhost: random-port only; security: never 0.0.0.0)
        preset: Optional[str] = None,  # P2/P3: platform preset (#288)
        region: Optional[str] = None,  # P2/P3: TLS region override
        launch_options: Optional[
            Dict[str, Any]
        ] = None,  # #143: custom Playwright launch_persistent_context / context opts (merged safely, e.g. ignore_default_args, extra args)
    ):  # combined: #57/#48/#47 pooled + P2 resume + #351 health/debug/preset/region
        """Launch browser with full stealth + human behavior.

        IMPORTANT NAMING (to avoid integration bugs like BUG-02/BUG-03):
            - self.browser  -> Playwright BrowserContext (persistent context)
            - self.page     -> Playwright Page (main page created after launch)
            - self.context  -> alias for self.browser (for clarity in some paths)

        Consumers (including MCP wrappers) must use self.page for page methods
        (goto, content, inner_text, click, etc.). Never call them on self.browser.

        P2 Core cluster (#134 #143 #155 #161 #176 #182): use page_getter() for decoupled access,
        launch(..., launch_options={...}) for custom PW opts, switch_region(), new_page()/get_pages(),
        async with + atexit for graceful, CookieManager consolidation.

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
            persona: Override persona.
            use_pooled_context: If True, use shared _BrowserPool + new_context() for scalability (P1 #57/#48/#47).
                Only effective when proxy rotation is not required (or handled by creating fresh pooled ctxs).
                Default False for full backward compat + per-session disk persistence via launch_persistent_context.
            resume: Opt-in P2: when True, forces light_mode for faster resume from saved sessions (less rigid warm-up).
            debug: Enable debug mode (#265) - populates DebugReporter for fingerprint/headers/patches.
            debug_cdp: Opt-in for #377 CDP remote debugging WS endpoint (binds strictly to 127.0.0.1, random port via =0). Returns via stealth_get_cdp_endpoint or get_cdp_endpoint(). Explicit security warning in responses. Disabled by default for safety.
            preset: Platform preset e.g. "linkedin_2026" (#288) - sets region, behavior, recovery tuning.
            region: TLS region override ("us", "eu", "japan", "korea", "global").
            launch_options: Dict of extra kwargs passed to Playwright's launch_persistent_context (or context opts in pooled).
                Merged safely after our derived args/headers/etc. Examples: ignore_default_args=["--disable-..."], channel="chrome", etc. (#143)
            Proxy support: configure via self.proxy_manager.create_decodo_config(...) *before* calling launch()
            (or pass preconfigured ProxyManager in advanced usage); it is now wired into launch_persistent_context (#14, #29).
        """
        if persona is not None:
            self.persona = persona
        if light_mode is not None:
            self.light_mode = light_mode
        if use_pooled_context is not None:
            self.use_pooled_context = use_pooled_context
            self._using_pool = False  # reset; will set true if we take the pooled path

        if resume:
            self._resume = True
            if not getattr(self, "light_mode", False):
                self.light_mode = True  # P2: resume=True forces light warm-up (less rigid on session restore)

        # Support documented STEALTH_* environment variables (#34)
        # These are set in Dockerfile / docker-compose and referenced in README.
        env_headless = os.getenv("STEALTH_HEADLESS")
        if env_headless is not None:
            headless = str(env_headless).lower() not in ("0", "false", "no", "")

        env_region = os.getenv("STEALTH_REGION")
        if env_region:
            # TLS manager will be (re)created below; store for selection
            self._env_region = env_region.lower()

        # P2/P3 DX wiring (#281 health, #265 debug, #288 preset)
        self.debug_mode = bool(debug)
        self.debug_cdp = bool(debug_cdp)  # #377
        if preset:
            self.current_preset = preset
            try:
                from stealth.presets import get_preset

                p = get_preset(preset)
                # derive region from preset if not explicitly passed
                if not region and hasattr(p, "tls_region"):
                    reg = p.tls_region
                    region = reg.value if hasattr(reg, "value") else str(reg)
            except Exception:
                pass
        if region:
            self.current_region = str(region).lower()
        self._custom_launch_options = launch_options or {}  # #143
        # store for rotation relaunch
        self._launch_options = {
            "headless": headless,
            "slow_mo": slow_mo,
            "headed": headed,
            "light_mode": light_mode,
            "use_pooled_context": use_pooled_context,
            "debug": self.debug_mode,
            "debug_cdp": self.debug_cdp,
            "preset": self.current_preset,
            "region": self.current_region,
            "resume": resume,
            "launch_options": launch_options,  # #143 preserve custom for rotation relaunch
        }
        # P1 #57/#48/#47: optional pooled path (shared browser + new_context) vs classic per-instance persistent
        extra_headers = get_extra_http_headers()

        # TLS Fingerprint spoofing (region-aware) - now respects preset/region/debug (#281)
        tls_region = self.current_region or "global"
        self.tls_manager = get_tls_manager(tls_region, self.session.get("name"))
        self.tls_manager.log_fingerprint_choice()
        tls_args = self.tls_manager.get_launch_args()

        base_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--no-sandbox",
            "--headless=new",  # Chrome 112+ new headless: uses real rendering pipeline, much better fingerprint than old headless
        ]
        all_args = list(set(base_args + tls_args))

        # #377: CDP remote debugging opt-in (localhost-only for security). Applied to browser args in classic path.
        # (Pooled path uses shared browser launch in _BrowserPool; CDP debug sessions should use default non-pooled for now - minimal surface change.)
        if getattr(self, "debug_cdp", False):
            cdp_flags = [
                "--remote-debugging-address=127.0.0.1",
                "--remote-debugging-port=0",
            ]
            all_args = list(
                dict.fromkeys(all_args + cdp_flags)
            )  # dedupe preserving order

        # Persona integration hook (foundation only for #109)
        # Uses dataclass overrides for consistent fingerprint. No other side effects yet.
        p_over = (
            getattr(self, "persona", None).to_launch_overrides()
            if getattr(self, "persona", None)
            else {}
        )
        vp = p_over.get("viewport", {"width": 1366, "height": 768})
        ua = p_over.get(
            "user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        loc = p_over.get("locale", "en-US")
        tz = p_over.get("timezone_id", "America/New_York")

        # P2: persona power-correlated hardware for deviceMemory / hardwareConcurrency in stealth script
        persona_obj = getattr(self, "persona", None)
        hw_fingerprint = (
            persona_obj.device.get_hardware_fingerprint()
            if persona_obj and hasattr(persona_obj, "device")
            else {"hardwareConcurrency": 8, "deviceMemory": 8}
        )
        # #124 #198: persona screen profile for viewport+screen/DPR/orient variety & consistency
        screen_profile = (
            persona_obj.device.get_screen_profile()
            if persona_obj
            and hasattr(persona_obj, "device")
            and hasattr(persona_obj.device, "get_screen_profile")
            else {
                "width": 1920,
                "height": 1080,
                "availWidth": 1920,
                "availHeight": 1055,
                "colorDepth": 24,
                "pixelDepth": 24,
                "devicePixelRatio": 1.0,
                "orientation": "landscape-primary",
            }
        )

        # #279 future-proofing: detect PW version + new signals, warn gracefully (no hard fail)
        try:
            compat = check_stealth_compatibility()
            if compat.get("warning") and getattr(self, "debug_reporter", None):
                self.debug_reporter.record_patch("playwright_compat_warning", compat)
            elif compat.get("warning"):
                # minimal: could use logger but avoid new dep; record via audit if possible
                pass
        except Exception:
            pass

        # Proxy wiring (#14, #29): if caller pre-configured ProxyManager (e.g. create_decodo_config before launch),
        # pass the Playwright proxy dict (socks5 supported) so real traffic uses residential proxy.
        # Foundation for rotation (#38/#16). get_playwright_proxy_args is no longer dead code.
        proxy_args = getattr(
            self.proxy_manager, "get_playwright_proxy_args", lambda: {}
        )()
        launch_proxy = proxy_args if proxy_args else None

        self._using_pool = bool(getattr(self, "use_pooled_context", False))
        if self._using_pool:
            # #439: pooled path borrows a context from the shared pool.
            self._teardown_mode = TeardownMode.POOLED
            # Scalability path: single shared Chromium + many cheap contexts. No per-instance user_data persistence.
            user_data = Path(self.session["user_data_dir"])
            user_data.mkdir(
                parents=True, exist_ok=True
            )  # keep dir for meta/cookies consistency
            pool = _BrowserPool()
            self._pool = pool
            context_opts = {
                "viewport": vp,
                "user_agent": ua,
                "locale": loc,
                "timezone_id": tz,
                "extra_http_headers": extra_headers,
                "proxy": launch_proxy,
                # headless is NOT set here — it's applied via --headless=new in all_args
                # at shared browser launch time (see _BrowserPool.ensure_browser).
                # Adding headless=True to context_opts here would be a layering error.
            }
            # #143: merge user-provided custom launch/context options safely (non-overriding critical keys)
            custom = getattr(self, "_custom_launch_options", {}) or {}
            for k, v in (custom or {}).items():
                if k not in (
                    "user_data_dir",
                    "headless",
                    "slow_mo",
                ):  # protect launch-time ones for pooled path
                    context_opts[k] = v
            self.browser = await pool.create_context(**context_opts)
            self.browser_context = self.browser
        else:
            # Classic (default, fully backward compatible): per-instance persistent context + own playwright
            pw = await async_playwright().start()
            self._pw = pw
            user_data = Path(self.session["user_data_dir"])
            user_data.mkdir(parents=True, exist_ok=True)
            # #143 support: build kwargs dict then merge custom options
            lp_kwargs = {
                "user_data_dir": str(user_data),
                "headless": not headed if headed else headless,
                "slow_mo": slow_mo,
                "viewport": vp,
                "user_agent": ua,
                "locale": loc,
                "timezone_id": tz,
                "extra_http_headers": extra_headers,
                "args": all_args,
                "proxy": launch_proxy,
            }
            custom = getattr(self, "_custom_launch_options", {}) or {}
            for k, v in (custom or {}).items():
                if k not in ("user_data_dir",):  # never override critical
                    lp_kwargs[k] = v
            self.browser = await pw.chromium.launch_persistent_context(**lp_kwargs)
            self.browser_context = self.browser

            # Capture browser subprocess PID for external lifecycle management
            try:
                pw_browser_obj = self.browser.browser  # BrowserContext -> Browser
                if pw_browser_obj is not None:
                    self._browser_process = pw_browser_obj.process
            except Exception:
                self._browser_process = None

            # #377: discover CDP WS endpoint if enabled (uses Chrome's DevToolsActivePort + /json/version; stdlib only)
            if getattr(self, "debug_cdp", False):
                try:
                    udir = Path(str(user_data))
                    port_file = udir / "DevToolsActivePort"
                    if port_file.exists():
                        port_text = (
                            port_file.read_text().strip().splitlines()[0].strip()
                        )
                        port = int(port_text)
                        probe_url = f"http://127.0.0.1:{port}/json/version"
                        with urllib.request.urlopen(probe_url, timeout=3) as r:
                            ver = json.loads(r.read().decode("utf-8", errors="replace"))
                        self._cdp_ws_endpoint = ver.get("webSocketDebuggerUrl")
                        self._cdp_port = port
                        self._cdp_browser_version = ver.get("Browser", "unknown")
                    else:
                        self._cdp_ws_endpoint = None
                        self._cdp_port = None
                except Exception:
                    self._cdp_ws_endpoint = None
                    self._cdp_port = None
                    self._cdp_browser_version = None

        # Per-session stable fingerprint seed (canvas/WebGL noise + fonts) for consistency across reloads
        # and variation between sessions. Addresses #150 (re-apply), #94, #210 etc.
        session_name = (self.session or {}).get("name", "default-session")
        fp_seed = f"agentic-{session_name}-canvas-v4"

        # Inject on *context* (not page) so init script runs for:
        # - the initial page, all subsequently created pages (new_page etc.)
        # - every navigation, reload, and subframe
        # This ensures stealth patches (canvas/Offscreen/WebGL/font) are re-applied after nav/reload (#150)
        # and use the per-session seed for stable but unique fp.
        stealth_script = get_stealth_script(
            fingerprint_seed=fp_seed, hardware=hw_fingerprint, screen=screen_profile
        )
        await self.browser.add_init_script(stealth_script)
        if getattr(self, "debug_reporter", None):
            try:
                self.debug_reporter.record_patch(
                    "stealth_init_script",
                    {
                        "seed": fp_seed,
                        "hardware": bool(hw_fingerprint),
                        "screen": bool(screen_profile),
                        "length": len(stealth_script)
                        if isinstance(stealth_script, str)
                        else "n/a",
                    },
                )
            except Exception:
                pass

        # Create main page (critical fix)
        self.page = await self.browser.new_page()
        self._owns_page = True
        self.context = self.browser  # alias for clarity (BUG-03 naming hygiene)

        # #182: initialize default page_getter (overridable); recovery and internal now prefer via getter
        self._page_getter = None  # ensures property falls back to self.page

        # Create human behavior controller + orchestrator
        # #222 fix: pass self.rng so helpers use the per-AgentBrowser rng instance instead of global random (reproducible when seeded in future)
        # Pass persona.device for device-aware scroll + future behavior (#244 P2)
        self.human = HumanBehavior(
            self.page,
            rng=self.rng,
            device_profile=getattr(self.persona, "device", None),
        )
        self.orchestrator = BehaviorOrchestrator(self.human, rng=self.rng)

        # Seed JS mouse tracker from Python last_pos for continuity (#24 #101).
        # Must be after add_init_script + page ready. Safe best-effort.
        try:
            await self.human.initialize_mouse_tracker()
        except Exception:
            pass

        # Initialize audit logging
        # P2 #128: Pass correlation_id from metrics to logger for consistent tracing
        self.logger = AuditLogger(
            self.session["name"], correlation_id=self.metrics.get_correlation_id()
        )

        # P2/P3 DX: enable debug reporter for fingerprint/headers/patches when debug=True (#265, supports health + MCP debug_report)
        if getattr(self, "debug_mode", False):
            try:
                if hasattr(self.logger, "enable_debug_mode"):
                    self.logger.enable_debug_mode()
            except Exception:
                pass
            try:
                from audit.logger import DebugReporter

                extra_h = get_extra_http_headers()
                self.debug_reporter = DebugReporter(
                    self.logger, self.tls_manager, extra_h
                )
                if self.tls_manager and hasattr(self.debug_reporter, "record_patch"):
                    try:
                        self.debug_reporter.record_patch(
                            "tls_profile_launch", self.tls_manager.get_profile()
                        )
                    except Exception:
                        pass
            except Exception:
                self.debug_reporter = None

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
            page_getter=self.page_getter,  # #182: use the (overridable) page_getter for better decoupling
            light_mode=getattr(
                self, "light_mode", None
            ),  # ultra-narrow absolute final: light_mode on AgentBrowser automatically reduces expensive recovery detection (content calls, heavy path) for #92/#84 + #174
            rng=self.rng,  # #222: wire the AgentBrowser rng to recovery (for backoff jitter etc, eliminates its global random usage)
        )

        # Wire active session for #90 P1: auto cookie/session cleanup on ACCOUNT_RESTRICTION
        if self.recovery:
            self.recovery.set_current_session_name(
                self.session.get("name") if self.session else None
            )

        # Rotation relaunch hook wiring (#38, #16): recovery can now actually change the live browser/proxy/session
        # by calling this after deciding to rotate + sleeping. Hook is async, updates self.page etc dynamically
        # so that the next execute_with_recovery iteration'\''s _navigate func sees fresh context. Safe, no reentrancy on recovery itself.
        if self.recovery:
            self.recovery._rotation_relaunch_hook = self._perform_rotation_relaunch
            self.recovery.metrics = self.metrics

        # Store playwright instance for proper cleanup (only in non-pooled classic path)
        if not getattr(self, "_using_pool", False):
            # pw is defined only in else branch
            if "pw" in locals():
                self._pw = pw

        # P2 #97: Record launch in metrics
        self.metrics.increment("launches_total")
        self.metrics.set_gauge("browser_launched", 1)
        self.logger.log_action(
            "browser_launched",
            {
                "preset": getattr(self, "current_preset", None),
                "region": getattr(self, "current_region", None),
            },
        )

        return self.browser

    async def _perform_rotation_relaunch(
        self,
        new_session_meta: Optional[Dict] = None,
        new_proxy_name: Optional[str] = None,
    ) -> None:
        """
        Rotation hook implementation for #38/#16 (and #14 follow-on).
        Called by AntiBlockOrchestrator.recover after proxy/session rotation + backoff.
        Closes the old persistent context, relaunches a fresh one using:
          - updated proxy from self.proxy_manager (now with new sticky session)
          - new user_data_dir from rotated session (if provided)
        Re-wires page, human behavior, scraper, stealth, and recovery references.
        The next retry of _navigate / func in execute_with_recovery will use the fresh live browser.
        Safety: does not recreate recovery (avoids reentrancy), preserves light_mode/persona/rate_limiter.
        Only called on recovery paths; headless defaults to True for recovery relaunches.
        """
        # Updated guard for pooled mode (#57 etc): allow rotation if we have browser (pooled uses _pool not _pw)
        has_launcher = bool(getattr(self, "browser", None)) and (
            bool(getattr(self, "_pw", None))
            or bool(getattr(self, "_pool", None))
            or getattr(self, "_using_pool", False)
        )
        if not has_launcher:
            return

        log = getattr(self, "logger", None)
        try:
            # 1. Close old page + context (for pooled: release via pool to keep shared browser alive)
            if getattr(self, "page", None):
                try:
                    await self.page.close()
                except Exception:
                    pass
                self.page = None
                self._owns_page = False
            if getattr(self, "browser", None):
                try:
                    if getattr(self, "_using_pool", False) and getattr(
                        self, "_pool", None
                    ):
                        await self._pool.release_context(self.browser)
                    else:
                        await self.browser.close()
                except Exception:
                    pass
                self.browser = None
                self.browser_context = None

            # 2. Adopt rotated session (provides fresh user_data_dir + name)
            if new_session_meta and isinstance(new_session_meta, dict):
                self.session = new_session_meta
                if self.recovery:
                    self.recovery.set_current_session_name(self.session.get("name"))

            # 3. Recompute everything needed (mirrors launch logic)
            user_data = Path(self.session["user_data_dir"])
            user_data.mkdir(parents=True, exist_ok=True)

            extra_headers = get_extra_http_headers()

            # P2/P3: preserve current_region / preset for health/status continuity on rotation
            tls_region = getattr(self, "current_region", "global") or "global"
            self.tls_manager = get_tls_manager(tls_region, self.session.get("name"))
            self.tls_manager.log_fingerprint_choice()
            tls_args = self.tls_manager.get_launch_args()

            base_args = [
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--no-sandbox",
            ]
            all_args = list(set(base_args + tls_args))

            # #377: CDP flags on rotation relaunch (if debug_cdp was set on original launch)
            if getattr(self, "debug_cdp", False):
                cdp_flags = [
                    "--remote-debugging-address=127.0.0.1",
                    "--remote-debugging-port=0",
                ]
                all_args = list(dict.fromkeys(all_args + cdp_flags))

            p_over = (
                getattr(self, "persona", None).to_launch_overrides()
                if getattr(self, "persona", None)
                else {}
            )
            vp = p_over.get("viewport", {"width": 1366, "height": 768})
            ua = p_over.get(
                "user_agent",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            )
            loc = p_over.get("locale", "en-US")
            tz = p_over.get("timezone_id", "America/New_York")

            # P2: persona power-correlated hardware (re-apply on rotation too)
            persona_obj = getattr(self, "persona", None)
            hw_fingerprint = (
                persona_obj.device.get_hardware_fingerprint()
                if persona_obj and hasattr(persona_obj, "device")
                else {"hardwareConcurrency": 8, "deviceMemory": 8}
            )

            # Proxy now reflects the rotated config (from recovery's create_decodo or rotate_proxy)
            proxy_args = getattr(
                self.proxy_manager, "get_playwright_proxy_args", lambda: {}
            )()
            launch_proxy = proxy_args if proxy_args else None

            # 4. Relaunch: use pooled create_context if in pool mode, else classic persistent (using stored _pw)
            opts = getattr(
                self,
                "_launch_options",
                {"headless": True, "slow_mo": 0, "headed": False},
            )
            h = opts.get("headless", True)
            sm = opts.get("slow_mo", 0)
            hd = opts.get("headed", False)
            self._custom_launch_options = (
                opts.get("launch_options")
                or getattr(self, "_custom_launch_options", {})
                or {}
            )  # #143 preserve across rotation
            if getattr(self, "_using_pool", False) and getattr(self, "_pool", None):
                context_opts = {
                    "viewport": vp,
                    "user_agent": ua,
                    "locale": loc,
                    "timezone_id": tz,
                    "extra_http_headers": extra_headers,
                    "proxy": launch_proxy,
                }
                # #143 merge custom in rotation too
                custom = getattr(self, "_custom_launch_options", {}) or {}
                for k, v in (custom or {}).items():
                    if k not in ("user_data_dir", "headless", "slow_mo"):
                        context_opts[k] = v
                self.browser = await self._pool.create_context(**context_opts)
                self.browser_context = self.browser
            else:
                # #143: build + merge custom in rotation relaunch
                lp_kwargs = {
                    "user_data_dir": str(user_data),
                    "headless": not hd if hd else h,
                    "slow_mo": sm,
                    "viewport": vp,
                    "user_agent": ua,
                    "locale": loc,
                    "timezone_id": tz,
                    "extra_http_headers": extra_headers,
                    "args": all_args,
                    "proxy": launch_proxy,
                }
                custom = getattr(self, "_custom_launch_options", {}) or {}
                for k, v in (custom or {}).items():
                    if k not in ("user_data_dir",):
                        lp_kwargs[k] = v
                # #439: mark teardown mode BEFORE the actual launch so any
                # partial-failure cleanup in close() knows what to do.
                self._teardown_mode = TeardownMode.LAUNCHED
                self.browser = await self._pw.chromium.launch_persistent_context(
                    **lp_kwargs
                )
                self.browser_context = self.browser

                # #377 rediscover after rotation relaunch (classic path)
                if getattr(self, "debug_cdp", False):
                    try:
                        udir = Path(str(user_data))
                        port_file = udir / "DevToolsActivePort"
                        if port_file.exists():
                            port_text = (
                                port_file.read_text().strip().splitlines()[0].strip()
                            )
                            port = int(port_text)
                            probe_url = f"http://127.0.0.1:{port}/json/version"
                            with urllib.request.urlopen(probe_url, timeout=3) as r:
                                ver = json.loads(
                                    r.read().decode("utf-8", errors="replace")
                                )
                            self._cdp_ws_endpoint = ver.get("webSocketDebuggerUrl")
                            self._cdp_port = port
                            self._cdp_browser_version = ver.get("Browser", "unknown")
                        else:
                            self._cdp_ws_endpoint = None
                            self._cdp_port = None
                    except Exception:
                        self._cdp_ws_endpoint = None
                        self._cdp_port = None
                        self._cdp_browser_version = None

            self.page = await self.browser.new_page()
            self._owns_page = True
            self.context = self.browser

            # 5. Re-apply stealth init script on context + fp seed
            session_name = (self.session or {}).get("name", "default-session")
            fp_seed = f"agentic-{session_name}-canvas-v4"
            # Apply screen profile from persona (rotation must preserve this, matching launch())
            screen_profile = p_over.get(
                "screen",
                p_over.get("viewport", {"width": vp["width"], "height": vp["height"]}),
            )
            await self.browser.add_init_script(
                get_stealth_script(
                    fingerprint_seed=fp_seed,
                    hardware=hw_fingerprint,
                    screen=screen_profile,
                )
            )

            # 5b. Re-check stealth compatibility after relaunch (matching launch())
            try:
                check_stealth_compatibility(hw_fingerprint)
            except Exception:
                pass

            # 6. Re-wire human/orchestrator/scraper for the *new* page (so clicks/scrolls etc work post-rotation)
            # Pass device for consistent scroll physics across rotation (#244)
            # Use a fresh RNG seeded from session name for independence from pre-rotation state
            rotation_rng = random.Random(session_name)
            self.human = HumanBehavior(
                self.page,
                rng=rotation_rng,
                device_profile=getattr(self.persona, "device", None),
            )
            self.orchestrator = BehaviorOrchestrator(self.human, rng=rotation_rng)
            self.scraper = StealthScraper(self.page, self.human, self.orchestrator)

            # Re-init mouse tracker post-rotation for position continuity (#18 related)
            try:
                await self.human.initialize_mouse_tracker()
            except Exception:
                pass

            # 7. Update recovery's browser ref and page_getter (#182: now delegates to AgentBrowser.page_getter for pluggability)
            if self.recovery:
                self.recovery.browser = self.browser
                self.recovery._get_page = (
                    self.page_getter
                )  # uses the overridable getter (defaults to current self.page)

            if log:
                log.log_action(
                    "rotation_relaunch_succeeded",
                    {
                        "session": (self.session or {}).get("name"),
                        "proxy_rotated": bool(launch_proxy),
                        "new_proxy": new_proxy_name,
                    },
                )
        except Exception as e:
            if log:
                log.log_error(
                    "rotation_relaunch_failed", str(e), {"proxy": new_proxy_name}
                )
            # Do not raise: let the recovery retry path surface the failure naturally (max_retries etc)
            # The old context is already closed, but browser may be in partial state; next operation will raise appropriately.

    async def goto(
        self,
        url: str,
        warm_up: bool = True,
        max_retries: int = 3,
        platform: str = "unknown",
    ):
        """Navigate with session warming and basic error recovery.

        P3 #5: When recovery orchestrator is available, delegates to safe_goto()
        for full anti-block protection. Falls back to basic retry logic otherwise.

        Respects self.light_mode (#174/#113) to skip warm-up costs/latency.
        """
        # P3 #5: Delegate to safe_goto when recovery is available (default path)
        if self.recovery:
            return await self.safe_goto(url, warm_up=warm_up, platform=platform)

        # #136: tool-level rate limit check
        if self._rate_limiter:
            await self._rate_limiter.check_and_wait("goto")

        if not self.browser:
            raise RuntimeError("Browser not launched. Call launch() first.")

        for attempt in range(max_retries):
            try:
                # Safe LinkedIn warm-up heuristic (fixes CodeQL py/incomplete-url-substring-sanitization)
                # Only trigger for actual linkedin.com / *.linkedin.com hosts, not arbitrary substrings in attacker-controlled URLs
                _is_linkedin = False
                try:
                    _netloc = urlparse(url).netloc.lower()
                    _is_linkedin = _netloc == "linkedin.com" or _netloc.endswith(
                        ".linkedin.com"
                    )
                except Exception:
                    _is_linkedin = False
                if (
                    warm_up
                    and _is_linkedin
                    and attempt == 0
                    and not getattr(self, "light_mode", False)
                ):  # ultra-narrow absolute final closer for ONLY #174 and #113: legacy goto path now skips warm-up cost/latency under light_mode (matches safe_goto + class/launch doc promises for launch/warm-up perf)
                    # Natural session warming
                    await self.page.goto(
                        "https://www.linkedin.com/feed/", wait_until="domcontentloaded"
                    )
                    await self.human.scroll_naturally(280)
                    await self.human.think(900, 1600)

                await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
                if not getattr(
                    self, "light_mode", False
                ):  # absolute final polish for #174/#113 launch/warm-up cost: also skip post-goto think delay in legacy goto (now fully matches safe_goto light_mode behavior)
                    await self.human.think(500, 1200)
                return True

            except Exception as e:
                if attempt == max_retries - 1:
                    raise e
                if not getattr(
                    self, "light_mode", False
                ):  # ultra-narrow absolute final closer for ONLY #174 and #113: skip retry think latency cost too in legacy goto under light_mode (completes full launch/warm-up cost reduction, no artificial delays remain)
                    await self.human.think(2000, 4000)  # Wait before retry
                continue

        return False

    async def safe_goto(
        self,
        url: str,
        warm_up: bool = True,
        platform: str = "unknown",
        rate_limit: bool = True,
        domain: str = None,
        account: str = None,
        respect_robots: bool = False,
    ):
        """
        Navigate with full anti-block recovery.
        Uses the AntiBlockOrchestrator for intelligent detection and recovery.
        Recommended for production / high-reliability use.
        Respects self.light_mode to skip warm-ups per #174.

        P0 #20: Rate limiting is now the default (rate_limit=True).
        Set rate_limit=False to opt-out for specific calls.

        P3: Integrated with AccountHealth, AccountWarmer, ConnectionPool, and AdaptiveTuner.
        """
        # #136: tool-level rate limit check
        if self._rate_limiter:
            await self._rate_limiter.check_and_wait("safe_goto")

        # Extract domain for all checks
        if domain is None:
            try:
                from urllib.parse import urlparse

                domain = urlparse(url).netloc
            except Exception:
                domain = "unknown"

        # ponytail: robots fetched per-call, no cache; add lru_cache/TTL if it becomes a hot path
        if respect_robots:
            try:
                import aiohttp
                from urllib.parse import urljoin

                robots_url = urljoin(url, "/robots.txt")
                async with aiohttp.ClientSession() as _s:
                    async with _s.get(
                        robots_url, timeout=aiohttp.ClientTimeout(total=10)
                    ) as _r:
                        _txt = await _r.text() if _r.status == 200 else ""
                if not robots_allows(_txt, url):
                    if getattr(self, "logger", None):
                        self.logger.log_action(
                            "navigate_blocked_by_robots", {"url": url}, level="warning"
                        )
                    return False
            except Exception:
                pass

        # P3: Account warming check - stop session if limits exceeded
        if self.account_warming.days_elapsed > 0:
            self.account_warming.start_session()
            if self.account_warming.should_stop_session():
                reason = self.account_warming.get_reason_to_stop()
                self.account_health.record_event(
                    "warming_limit", severity=0.1, details={"reason": reason}
                )
                raise RuntimeError(f"Account warming limit reached: {reason}")

        # P3: Account health check - enforce cooling off
        if self.account_health.is_cooling_off:
            remaining = self.account_health.cooling_off_remaining
            raise RuntimeError(f"Account is cooling off. {remaining:.0f}s remaining.")

        # P3: Connection pool reuse check
        if self.connection_pool.should_reuse(url):
            self.connection_pool.record_navigation(url)

        # P0 #20: Domain/account rate limiting (default enabled)
        if rate_limit:
            effective_account = (
                account
                or self.account_id
                or (self.session.get("name") if self.session else None)
                or "default"
            )
            rl = self.rate_limiter
            wait_time = await rl.wait_if_needed(effective_account, domain)
            if wait_time > 0:
                print(f"[Rate Limit] Waited {wait_time:.1f}s for {domain}")

        self.metrics.increment("requests_total")

        if not self.browser:
            raise RuntimeError("Browser not launched. Call launch() first.")

        if not self.recovery:
            # Fallback to normal goto if recovery not initialized
            return await self.goto(url, warm_up=warm_up)

        async def _navigate():
            # Safe LinkedIn warm-up heuristic (fixes CodeQL py/incomplete-url-substring-sanitization)
            # Only trigger for actual linkedin.com / *.linkedin.com hosts, not arbitrary substrings in attacker-controlled URLs
            _is_linkedin = False
            try:
                _netloc = urlparse(url).netloc.lower()
                _is_linkedin = _netloc == "linkedin.com" or _netloc.endswith(
                    ".linkedin.com"
                )
            except Exception:
                _is_linkedin = False
            if (
                warm_up and _is_linkedin and not getattr(self, "light_mode", False)
            ):  # ultra-narrow absolute final closer for ONLY #174 and #113: safe_goto now skips linkedin warm-up cost/latency under light_mode (matches legacy goto + doc promises for launch/warm-up perf)
                await self.page.goto(
                    "https://www.linkedin.com/feed/", wait_until="domcontentloaded"
                )
                await self.human.scroll_naturally(280)
                await self.human.think(900, 1600)

            response = await self.page.goto(
                url, wait_until="domcontentloaded", timeout=45000
            )
            if not getattr(
                self, "light_mode", False
            ):  # ultra-narrow absolute final closer for ONLY #174 and #113: safe_goto skips post-goto think under light_mode completing full warm-up cost reduction for launch perf (#174 #113)
                await self.human.think(500, 1200)
            return response

        try:
            await self.recovery.execute_with_recovery(
                func=_navigate, platform=platform, url=url
            )
            # P3: Record success to all tracking systems
            self.account_health.record_success()
            self.account_health.record_action()
            if self.account_warming.days_elapsed > 0:
                self.account_warming.record_action()
                self.account_warming.record_page_visit(url)
            self.connection_pool.release_context(domain)
            self.adaptive_tuner.record_feedback(blocked=False, platform=platform)
            self.logger.log_action(
                "navigate_succeeded",
                {"url": url, "platform": platform, "domain": domain},
            )
            self.metrics.increment("requests_success")
            return True
        except Exception as e:
            # P3: Record failure to all tracking systems
            self.account_health.record_event(
                "navigation_failed", severity=0.2, details={"url": url, "error": str(e)}
            )
            self.adaptive_tuner.record_feedback(
                blocked=True, block_type="navigation_error", platform=platform
            )
            self.logger.log_error(
                "safe_goto_failed", str(e), {"url": url, "platform": platform}
            )
            self.metrics.increment("requests_failed")
            self.metrics.record_error("navigation", str(e))
            return False

    async def load_cookies(self, cookies_path: str):
        """
        [DEPRECATED] Legacy cookie loader.
        Use load_cookies_from_file(..., encryption_key=...) + CookieManager for resilient + secure (#82) loading. Supports #270 rotation via list keys.
        Kept for backward compatibility; now delegates to consolidated CookieManager (resolves #134 duplication).
        """
        if not self.browser:
            raise RuntimeError("Browser not launched. Call launch() first.")
        # Delegate to the single implementation in CookieManager (no duplicated json/sameSite/add logic)
        # sameSite normalization now handled inside modern load path or by Playwright.
        return await self.load_cookies_from_file(cookies_path, encryption_key=None)

    async def safe_click(self, selector: str, platform: str = "unknown"):
        """Click with recovery logic."""
        # #136: tool-level rate limit check
        if self._rate_limiter:
            await self._rate_limiter.check_and_wait("safe_click")

        if not self.browser:
            raise RuntimeError("Browser not launched.")

        async def _click():
            # P2 thinking pause before the click action itself (#251)
            if self.human:
                await self.human.think_before_action(
                    "critical"
                    if any(
                        k in selector.lower()
                        for k in [
                            "submit",
                            "login",
                            "send",
                            "save",
                            "post",
                            "confirm",
                            "button",
                        ]
                    )
                    else "normal"
                )
                # occasional distraction before committing (#178)
                if (
                    getattr(self.human, "_fatigue_factor", lambda: 0)() > 0.15
                    or self.rng.random() < 0.09
                ):
                    await self.human.simulate_distraction(0.35)
            await self.page.click(selector, timeout=10000)
            await self.human.think(300, 800) if self.human else asyncio.sleep(0.3)

        try:
            if self.recovery:
                await self.recovery.execute_with_recovery(
                    func=_click,
                    platform=platform,
                    url=getattr(self.page, "url", "") if self.page else "",
                )
            else:
                await _click()
            return True
        except Exception as e:
            self.logger.log_error("safe_click_failed", str(e), {"selector": selector})
            return False

    async def safe_type(self, selector: str, text: str, platform: str = "unknown"):
        """Type with human-like behavior and recovery."""
        # #136: tool-level rate limit check
        if self._rate_limiter:
            await self._rate_limiter.check_and_wait("safe_type")

        if not self.browser:
            raise RuntimeError("Browser not launched.")

        async def _type():
            if self.human:
                await self.human.think_before_action(
                    "normal"
                )  # deliberate before committing text (#251)
            await self.human.type_like_human(selector, text)

        try:
            if self.recovery:
                await self.recovery.execute_with_recovery(
                    func=_type,
                    platform=platform,
                    url=getattr(self.page, "url", "") if self.page else "",
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
            # #182: page_getter usage
            p = self.page_getter()
            if p:
                await p.mouse.wheel(0, self.rng.randint(200, 400))
            await asyncio.sleep(1.5)

    async def load_cookies_from_file(
        self, cookies_path: str, encryption_key: Any = None
    ) -> Dict[str, Any]:
        """Load cookies using the resilient CookieManager.

        Supports encryption_key (str or list[str] for #270 key rotation) for P1 #82 secure (encrypted) cookie loads.
        Pass the same secret used with save_cookies_to_file(encrypt=True).
        """
        if not self.browser:
            raise RuntimeError("Browser not launched. Call launch() first.")

        self.cookie_manager = CookieManager(self.browser)
        result = await self.cookie_manager.load_cookies(
            cookies_path, encryption_key=encryption_key
        )

        if result.get("status") == "success":
            # Also initialize session orchestrator
            self.session_orchestrator = SessionOrchestrator()
            if getattr(self, "logger", None):
                self.logger.log_action(
                    "cookies_loaded",
                    {"path": cookies_path, "count": result.get("count")},
                )

        return result

    async def get_cookie_health(self) -> Dict[str, Any]:
        """Check health of current cookies."""
        if not self.cookie_manager:
            return {"status": "no_manager", "message": "No cookie manager initialized"}

        return await self.cookie_manager.get_cookie_health()

    async def save_cookies_to_file(
        self, cookies_path: str, encrypt: bool = False, encryption_key: Any = None
    ) -> Dict[str, Any]:
        """Save cookies to file (plain or encrypted) via CookieManager.

        P1 #82: Use encrypt=True + any secret key for at-rest Fernet encryption + integrity protection.
        encryption_key may be str or list[str] (#270 rotation: first for encrypt).
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
        P2 #146: for pooled contexts (#166) or light jobs, prefer intensity=light or set light_mode=True
        to keep warm-up short (avoids serial blocking feel for concurrent agents). Warm-up remains
        intentionally human-paced for realism on real work; use quick paths for one-off scrapes.
        Now uses profile_action around mouse/click/hover/scroll actions for timing + visibility (#169).
        Best-effort: sub-failures logged (via profile + AuditLogger) but do not silently claim full success
        if critical warm-up gestures all failed. Returns partial/degraded status when needed.

        P4 #146: Now supports non-blocking mode via warm_up_before_work(..., background=True)
        which returns immediately and runs warm-up steps concurrently.
        """
        if not self.human:
            return {"status": "error", "message": "Human behavior not initialized"}

        attempted = 0
        succeeded = 0
        errors = []

        def _should_profile(act_name: str) -> bool:
            # profile the ones that involve clicks/hovers/mouse moves (core of #169 complaint)
            return any(
                k in act_name.lower()
                for k in (
                    "mouse",
                    "click",
                    "hover",
                    "micro",
                    "scroll",
                    "idle",
                    "read",
                    "search",
                    "jitter",
                )
            )

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
                        self.logger.log_error(
                            "warm_up_step_failed",
                            str(e),
                            {"step": name, "intensity": intensity},
                        )
                    except Exception:
                        pass
                # best-effort: continue; profile already logged the failure visibly
                return None

        try:
            if getattr(self, "light_mode", False):
                intensity = "light"

            if intensity == "light":
                await _run_step(
                    "scroll_light", lambda: self.human.scroll_naturally(200)
                )
                await _run_step("think_light", lambda: self.human.think(800, 1500))

            elif intensity == "medium":
                await _run_step("scroll_med", lambda: self.human.scroll_naturally(350))
                await _run_step("think_med", lambda: self.human.think(1200, 2200))
                await _run_step(
                    "micro_move", lambda: self.human.micro_movement_while_waiting(600)
                )
                if self.rng.random() < 0.4:
                    await _run_step(
                        "random_idle", lambda: self.human.random_idle_behavior(3.0)
                    )

            elif intensity == "heavy":
                await _run_step(
                    "simulate_reading",
                    lambda: self.human.simulate_reading(6.0, content_factor=1.3),
                )  # P2 #131 variable read time
                await _run_step(
                    "viewport_jitter", lambda: self.human.apply_viewport_jitter()
                )
                if self.rng.random() < 0.5:
                    await _run_step(
                        "fake_search", lambda: self.human.fake_search_action()
                    )
                await _run_step(
                    "random_idle_heavy", lambda: self.human.random_idle_behavior(4.0)
                )

            status = "success"
            if attempted > 0 and succeeded == 0:
                status = "degraded"  # all critical steps (esp mouse/click profile ones) failed; do not pretend warmed (#169)
            elif attempted > 0 and succeeded < attempted:
                status = "partial"

            result = {
                "status": status,
                "intensity": intensity,
                "steps_attempted": attempted,
                "steps_succeeded": succeeded,
            }
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
                    self.logger.log_error(
                        "warm_up_failed", str(e), {"intensity": intensity}
                    )
                except Exception:
                    pass
            return {
                "status": "error",
                "message": str(e),
                "steps_attempted": attempted,
                "steps_succeeded": succeeded,
            }

    async def warm_up_before_work_background(
        self, intensity: str = "medium"
    ) -> asyncio.Task:
        """P4 #146: Non-blocking warm-up that runs in the background.

        Returns an asyncio.Task that can be awaited later if needed.
        Allows other work to proceed while warm-up runs concurrently.

        Usage:
            task = await browser.warm_up_before_work_background("medium")
            # ... do other work ...
            result = await task  # wait for warm-up to complete
        """

        async def _run_warmup():
            return await self.warm_up_before_work(intensity=intensity)

        task = asyncio.create_task(_run_warmup())
        return task

    async def ensure_cookies_fresh(self, max_age_hours: int = 8) -> Dict[str, Any]:
        """Ensure cookies are fresh before long operations."""
        if not self.cookie_manager:
            return {"status": "no_manager"}
        return await self.cookie_manager.refresh_cookies_if_needed(max_age_hours)

    async def cleanup_compromised_session(
        self, remove_dir: bool = False
    ) -> Dict[str, Any]:
        """#90 P1: Invalidate current session cookies + mark as compromised.

        Call this after ACCOUNT_RESTRICTION (or any detected compromise) to avoid
        reusing tainted cookies. High-impact security/recovery hygiene.
        """
        name = None
        result = {"status": "noop"}
        if self.session:
            name = self.session.get("name")
            if self.session_manager:
                result = self.session_manager.cleanup_session(
                    name, remove_dir=remove_dir
                )

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
        """Take screenshot on error for visual debugging.
        #149 fix: always log failure reason (via logger if available), fixed time.time() call, best-effort.
        #182: uses page_getter() internally (decoupled access).
        """
        # #136: tool-level rate limit check
        if self._rate_limiter:
            await self._rate_limiter.check_and_wait("screenshot_on_error")

        p = self.page_getter()
        if not p:
            return None
        try:
            import os

            os.makedirs("screenshots", exist_ok=True)
            filename = f"screenshots/{name}_{int(time.time())}.png"
            await p.screenshot(path=filename, full_page=True)
            return filename
        except Exception as e:
            # #149: never silent - log the exact failure (print fallback if no logger yet)
            msg = f"Screenshot failed: {e}"
            if getattr(self, "logger", None):
                try:
                    self.logger.log_error(
                        "screenshot_on_error_failed", str(e), {"name": name}
                    )
                except Exception:
                    print(msg)
            else:
                print(msg)
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
                    self.logger.log_error(
                        "profile_action_failed",
                        str(e),
                        {"name": name, "duration": duration},
                    )
                except Exception:
                    pass
            raise

    async def safe_goto_with_rate_limit(
        self, url: str, domain: str = None, account: str = None, **kwargs
    ):
        """Navigate with rate limiting protection (now per-instance for #79/#87 isolation).
        Deprecated: safe_goto now has rate_limit=True by default (#20).
        This method is kept for backward compatibility.
        """
        return await self.safe_goto(
            url, rate_limit=True, domain=domain, account=account, **kwargs
        )

    def set_rate_limit(
        self,
        domain: str,
        requests_per_minute: int = 8,
        cooldown_seconds: int = 60,
        account: Optional[str] = None,
    ):
        """Configure custom rate limit for a domain (applied to this instance's limiter)."""
        from production.rate_limiter import RateLimitConfig

        config = RateLimitConfig(
            requests_per_minute=requests_per_minute, cooldown_seconds=cooldown_seconds
        )
        # Per-instance: target the sub-limiter for the given (or default) account
        dl = self.rate_limiter.get_limiter(account or "default")
        dl.set_limit(domain, config)

    # --- P2/P3 DX / Observability methods (#281 health/status, #265 debug, #288 presets) ---

    async def get_health_status(self) -> Dict[str, Any]:
        """#281 High-value DX: Rich health & status snapshot (proxy usage, account state, block rate, etc).

        Powers CLI `health`/`status` commands + MCP `stealth_health()` / `stealth_status()`.
        Includes launched state, preset, TLS profile/region, current URL, cookie health,
        recovery stats, approximate block rate, proxy info, account hints, metrics.
        """
        if not getattr(self, "browser", None) or not getattr(self, "page", None):
            return {
                "status": "not_launched",
                "launched": False,
                "preset": getattr(self, "current_preset", None),
                "region": getattr(self, "current_region", "global"),
                "message": "Browser not launched. Use launch() or async with AgentBrowser()",
            }

        # Current URL (best effort)
        current_url = "unknown"
        try:
            p = self.page_getter()
            if p:
                current_url = getattr(p, "url", "unknown")
        except Exception:
            pass

        # Cookie health
        cookie_health = {"status": "no_manager"}
        try:
            cookie_health = await self.get_cookie_health()
        except Exception:
            pass

        # TLS / fingerprint snapshot
        tls_info = {"region": getattr(self, "current_region", "global")}
        if self.tls_manager and hasattr(self.tls_manager, "get_profile"):
            try:
                prof = self.tls_manager.get_profile()
                tls_info = {
                    "region": getattr(self.tls_manager, "region", None),
                    "name": prof.get("name") if isinstance(prof, dict) else None,
                    "description": prof.get("description")
                    if isinstance(prof, dict)
                    else None,
                }
            except Exception:
                pass

        # Proxy usage / state
        proxy_info = {"status": "unconfigured"}
        try:
            if hasattr(self.proxy_manager, "get_current_proxy_info"):
                proxy_info = self.proxy_manager.get_current_proxy_info() or proxy_info
            elif hasattr(self.proxy_manager, "current_config"):
                cfg = self.proxy_manager.current_config
                proxy_info = {
                    "provider": getattr(cfg, "provider", None),
                    "host": getattr(cfg, "host", None),
                }
        except Exception:
            pass

        # Recovery / block stats (critical for block rate, account state)
        recovery_info: Dict[str, Any] = {"available": bool(self.recovery)}
        block_count = 0
        try:
            if self.recovery:
                fc = getattr(self.recovery, "failure_counts", {}) or {}
                recovery_info["failure_counts"] = fc
                block_count = (
                    sum(fc.values())
                    if fc
                    else getattr(self.recovery, "block_count", 0) or 0
                )
                last_block = getattr(self.recovery, "last_block_type", None)
                if last_block:
                    recovery_info["last_block"] = str(last_block)
        except Exception:
            pass

        # Block rate from metrics + recovery (observability win)
        block_rate = 0.0
        requests = 0
        try:
            if hasattr(self.metrics, "counters"):
                requests = self.metrics.counters.get("requests_total", 0) or 0
            if requests > 0 and block_count > 0:
                block_rate = round((block_count / max(requests, 1)) * 100, 2)
            elif block_count > 0:
                block_rate = 100.0  # degenerate but informative
        except Exception:
            pass

        account_state = "healthy"
        if recovery_info.get("last_block"):
            account_state = f"degraded_after_{recovery_info['last_block']}"

        return {
            "status": "ok",
            "launched": True,
            "current_url": current_url,
            "preset": getattr(self, "current_preset", None),
            "region": getattr(self, "current_region", "global"),
            "tls_profile": tls_info,
            "proxy": proxy_info,
            "cookies": cookie_health,
            "recovery": recovery_info,
            "block_rate_pct": block_rate,
            "account_state": account_state,
            "debug_mode": getattr(self, "debug_mode", False),
            "metrics_sample": {
                "requests_total": requests,
                "blocks_observed": block_count,
            },
            "stealth_score": self.get_stealth_score(),
            "replay_preview": self.get_replay_sequence(5),
            "timestamp": time.time(),
        }

    async def debug_report(
        self,
        print_report: bool = False,
        limit: Optional[int] = None,
        cursor: Optional[str] = None,
        since_ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        """#265: Full debug dump of TLS fingerprint, headers, stealth patches. Supports health flows too.
        #381: limit/cursor/since_ts forwarded to control recent_audit pagination in report.
        """
        if not self.debug_reporter:
            try:
                from audit.logger import DebugReporter
                from stealth.headers import get_extra_http_headers

                self.debug_reporter = DebugReporter(
                    getattr(self, "logger", None),
                    getattr(self, "tls_manager", None),
                    get_extra_http_headers(),
                )
            except Exception as e:
                return {"status": "error", "message": f"DebugReporter unavailable: {e}"}

        report = self.debug_reporter.full_debug_report(
            include_recent_logs=True,
            recent_limit=limit,
            cursor=cursor,
            since_ts=since_ts,
        )
        if print_report:
            try:
                self.debug_reporter.print_human_report(report)
            except Exception:
                print(report)
        return {"status": "success", "report": report}

    async def get_cdp_endpoint(self) -> Dict[str, Any]:
        """#377: Return CDP WS endpoint + metadata ONLY if debug_cdp was enabled on launch (opt-in).
        When disabled (default for security): clear {"status": "disabled", ...} response.
        Binds exclusively to localhost (127.0.0.1) + random port. Explicit warnings included.
        """
        if not getattr(self, "debug_cdp", False):
            return {
                "status": "disabled",
                "message": "CDP attach is disabled (default). Launch with debug_cdp=True (or the MCP flag) to opt-in. This is an explicit security boundary: the endpoint binds ONLY to 127.0.0.1 and is never exposed on the network.",
                "security_note": "Remote debugging ports on non-localhost are a common attack vector; opt-in only in trusted local dev environments.",
            }

        # Lazy discovery (in case called before post-launch probe, or after some event)
        if not getattr(self, "_cdp_ws_endpoint", None):
            try:
                # best-effort re-probe using last known user_data if available (from _launch_options or session)
                udir = (
                    Path(self.session.get("user_data_dir", ""))
                    if getattr(self, "session", None)
                    else None
                )
                if udir and udir.exists():
                    port_file = udir / "DevToolsActivePort"
                    if port_file.exists():
                        port_text = (
                            port_file.read_text().strip().splitlines()[0].strip()
                        )
                        port = int(port_text)
                        probe_url = f"http://127.0.0.1:{port}/json/version"
                        with urllib.request.urlopen(probe_url, timeout=3) as r:
                            ver = json.loads(r.read().decode("utf-8", errors="replace"))
                        self._cdp_ws_endpoint = ver.get("webSocketDebuggerUrl")
                        self._cdp_port = port
                        self._cdp_browser_version = ver.get("Browser", "unknown")
            except Exception:
                pass

        ws = getattr(self, "_cdp_ws_endpoint", None)
        if not ws:
            return {
                "status": "error",
                "message": "CDP was enabled but endpoint not discoverable (browser may still be starting, or DevToolsActivePort file absent). Retry after launch settles.",
                "debug_cdp": True,
            }

        return {
            "status": "enabled",
            "ws_endpoint": ws,
            "port": getattr(self, "_cdp_port", None),
            "browser": getattr(self, "_cdp_browser_version", "unknown"),
            "warning": "SECURITY: CDP endpoint is bound to localhost (127.0.0.1) ONLY. Do not forward or expose this port. CDP attach grants full browser control bypassing some MCP/stealth layers. Use exclusively for local debugging/observability in trusted environments. This was explicitly opted-in via debug_cdp=True.",
            "how_to_attach": "Use the ws_endpoint with Chrome DevTools, Playwright connectOverCDP, puppeteer, etc. Example: playwright.chromium.connect_over_cdp(ws_endpoint)",
        }

    async def apply_preset(self, name: str) -> Dict[str, Any]:
        """#288: Runtime apply of platform preset (tunes recovery/behavior notes; TLS best on (re)launch)."""
        try:
            from stealth.presets import get_preset, list_presets

            available = list_presets()
            if name not in available:
                return {
                    "status": "error",
                    "available": available,
                    "message": f"Unknown preset '{name}'",
                }
            preset = get_preset(name)
            self.current_preset = name
            if hasattr(preset, "tls_region"):
                reg = preset.tls_region
                self.current_region = reg.value if hasattr(reg, "value") else str(reg)
            # Tune recovery tunables if exposed (non-breaking)
            if self.recovery:
                for attr, val in [
                    ("max_retries", getattr(preset, "recovery_max_retries", None)),
                    ("base_backoff_ms", getattr(preset, "recovery_base_backoff", None)),
                ]:
                    if val is not None and hasattr(self.recovery, attr):
                        setattr(self.recovery, attr, val)
            return {
                "status": "success",
                "preset": name,
                "description": getattr(preset, "description", ""),
                "notes": (getattr(preset, "notes", "") or "")[:300],
                "tls_region": self.current_region,
                "hint": "For full TLS effect on preset change, re-launch the browser instance.",
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def switch_region(
        self, new_region: str, relaunch: bool = False
    ) -> Dict[str, Any]:
        """P2 #155: Switch TLS/region profile mid-session.

        Updates current_region, tls_manager, and relevant headers/patches.
        Where possible without restart (headers, health, future rotation metadata, some stealth).

        For full effect on launch-time TLS fingerprint args (e.g. client hello), set relaunch=True
        (performs internal _perform_rotation_relaunch style refresh using current session/proxy).
        Or call after and let recovery rotate if needed.

        Returns status + note on limitations.
        """
        if not new_region:
            return {"status": "error", "message": "region required"}
        old_region = getattr(self, "current_region", "global")
        new_r = str(new_region).lower()
        self.current_region = new_r
        try:
            self.tls_manager = get_tls_manager(new_r, (self.session or {}).get("name"))
            if hasattr(self.tls_manager, "log_fingerprint_choice"):
                self.tls_manager.log_fingerprint_choice()
        except Exception:
            pass
        # preserve for rotations / health
        if hasattr(self, "_launch_options"):
            self._launch_options["region"] = new_r
        # update extra headers? (global fn may pick region? but for now metadata only)
        result = {
            "status": "success",
            "old_region": old_region,
            "new_region": new_r,
            "relaunch_performed": False,
            "note": "Partial update applied (headers/health/rotation metadata). Full TLS client profile change requires relaunch or new context.",
        }
        if relaunch and hasattr(self, "_perform_rotation_relaunch"):
            try:
                await self._perform_rotation_relaunch()
                result["relaunch_performed"] = True
                result["note"] = "Relaunch performed for full region/TLS effect."
            except Exception as e:
                result["relaunch_error"] = str(e)
        if getattr(self, "logger", None):
            self.logger.log_action(
                "region_switched", {"relaunch": result.get("relaunch_performed", False)}
            )
        return result

    def get_stealth_score(self) -> Dict[str, Any]:
        """#269 configuration-based stealth readiness hint.

        WARNING: This is NOT an empirical detection-resistance measurement.
        It is a lightweight heuristic based on launch configuration (preset, light_mode).
        Do not use this score to decide whether it's safe to scrape — it only reflects
        which config options are active. For actual stealth testing, use a detection test page.
        """
        score = 62
        p = str(getattr(self, "current_preset", "")).lower()
        if "light" in p or "minimal" in p:
            score -= 5
        elif p:
            score += 8
        if getattr(self, "light_mode", False):
            score -= 6
        score = max(28, min(94, score))
        return {
            "config_hint": score,
            "detectability_risk_pct": 100 - score,
            "note": "This is a config-based heuristic, NOT an empirical stealth measurement. "
            "Use a detection test page for actual results.",
            "advice": "launched config score",
        }

    # Backward compat alias — old name still works
    get_config_hint = get_stealth_score

    def get_replay_sequence(
        self,
        limit: int = 30,
        cursor: Optional[str] = None,
        since_ts: Optional[str] = None,
    ) -> Dict[str, Any]:
        """#253 basic replay from AuditLogger. Supports #381 pagination params (forwarded; cursor treated as 'before' for older pages)."""
        if not getattr(self, "logger", None):
            return {"status": "no_logger", "sequence": []}
        try:
            replay_fn = getattr(
                self.logger,
                "replay_sequence",
                lambda limit_, cursor_=None, since_ts_=None: [],
            )
            return {
                "status": "ok",
                "sequence": replay_fn(limit, cursor, since_ts),
                "count": 0,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    # --- Multi-page / multi-tab support (P2 #176) ---
    async def new_page(self, make_current: bool = False) -> Any:
        """Create an additional concurrent page/tab within the same browser context.

        Supports #176: users can now do multi-tab workflows.
        All pages inherit the context's stealth init scripts automatically.

        Args:
            make_current: If True, wire the new page as self.page + re-init human/orchestrator/scraper
                          (for seamless switch; old page remains open unless user closes it).

        Returns:
            The new Playwright Page object. Caller can keep reference for background tabs.
        """
        if not self.browser:
            raise RuntimeError("Browser not launched. Call launch() first.")
        new_p = await self.browser.new_page()
        if make_current:
            self.page = new_p
            self._owns_page = True
            # re-wire for convenience (human etc now target the new current page)
            self.human = HumanBehavior(
                new_p,
                rng=self.rng,
                device_profile=getattr(self.persona, "device", None),
            )
            self.orchestrator = BehaviorOrchestrator(self.human, rng=self.rng)
            self.scraper = StealthScraper(new_p, self.human, self.orchestrator)
            # update recovery page_getter via our pluggable one
            if self.recovery:
                self.recovery._get_page = self.page_getter
            # note: user responsible for closing old_p if desired
        return new_p

    def get_pages(self) -> list:
        """Return list of all open pages in the browser context (if launched).

        Useful for #176 multi-tab management. Primary is self.page or via page_getter().
        """
        if self.browser and hasattr(self.browser, "pages"):
            try:
                return list(
                    self.browser.pages
                )  # Playwright BrowserContext exposes .pages
            except Exception:
                pass
        return [self.page] if self.page else []

    async def switch_to_page(self, page: Any) -> bool:
        """Switch the 'current' page to the provided one (from get_pages or new_page).

        Re-wires human behavior etc. Does not close the previous current page.
        Returns True on success. For #176 multi-tab support.
        """
        if not self.browser or not page:
            return False
        try:
            # validate it belongs? best effort
            if self.browser and page not in (getattr(self.browser, "pages", []) or []):
                # still allow, user may have external
                pass
            self.page = page
            self._owns_page = (
                True  # current page we are driving is now "ours" to manage
            )
            self.human = HumanBehavior(
                page, rng=self.rng, device_profile=getattr(self.persona, "device", None)
            )
            self.orchestrator = BehaviorOrchestrator(self.human, rng=self.rng)
            self.scraper = StealthScraper(page, self.human, self.orchestrator)
            if self.recovery:
                self.recovery._get_page = self.page_getter
            return True
        except Exception:
            return False

    async def attach_over_cdp(
        self,
        cdp_url: str,
        *,
        new_context: bool = False,
        context_index: int = 0,
        apply_stealth: bool = True,
        context_options: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Attach to an already-running browser exposing a CDP endpoint.

        Complement to ``debug_cdp=True`` on launch (which *exposes* a CDP endpoint):
        this method lets AgentBrowser *consume* an existing endpoint instead of
        spawning its own Chromium. Primary use case: drive the user's real
        desktop browser (e.g. Chrome on the Windows host from inside WSL) while
        still getting the runtime stealth layer.

        Args:
            cdp_url: HTTP or WS URL of the remote Chrome DevTools endpoint.
                Examples: ``http://127.0.0.1:9222``, ``http://192.168.1.10:9222``,
                ``ws://host:9222/devtools/browser/<id>``. Plain ``host:port`` is
                accepted and normalised to ``http://host:port``.
            new_context: If True, create a fresh empty BrowserContext on the
                attached browser instead of adopting an existing one. Recommended
                when you do NOT want to disturb the user's open tabs/cookies.
            context_index: Which existing context to adopt when ``new_context``
                is False. Defaults to 0 (the user's primary context).
            apply_stealth: When True (default) inject the init-script stealth
                layer on the chosen context so subsequently created pages get
                navigator/canvas/WebGL/audio patches. Existing already-open
                pages will only receive patches on their next navigation.
            context_options: Extra kwargs forwarded to ``browser.new_context``
                when ``new_context=True``. Ignored otherwise.

        Returns:
            Dict with attach metadata: cdp_url, browser_version, context_count,
            adopted_context_index (or ``"new"``), stealth_applied, and a
            ``degradation`` list enumerating which stealth layers do NOT apply
            in attach mode (TLS/JA3 fingerprint, launch-time process args,
            persistent user-data-dir profile, regional preset) — these are
            tied to *launching* the browser process and cannot be retrofitted
            onto an external Chrome.

        Security: attach mode grants full control over the target browser,
        including the user's cookies and authenticated sessions when adopting
        an existing context. Only point at trusted endpoints you own; never
        expose a remote-debugging port to the public internet.

        Teardown: ``close()`` will NOT terminate the externally-launched
        browser. It only closes the context (if created by us) and releases
        the Playwright connection.
        """
        if self.browser is not None:
            raise RuntimeError(
                "AgentBrowser already has an active browser/context. "
                "Call close() before attach_over_cdp(), or use a fresh instance."
            )
        if not cdp_url or not isinstance(cdp_url, str):
            raise ValueError("cdp_url must be a non-empty string")

        # Normalise bare host:port to http:// form (Playwright accepts http or ws)
        normalised = cdp_url.strip()
        if not normalised.startswith(("http://", "https://", "ws://", "wss://")):
            normalised = f"http://{normalised}"

        if getattr(self, "_pw", None) is None:
            self._pw = await async_playwright().start()

        # Connect — Playwright will resolve the WS endpoint from /json/version
        # automatically when given an http:// base URL.
        try:
            remote_browser = await self._pw.chromium.connect_over_cdp(normalised)
        except Exception as e:
            # Best-effort PW cleanup so a retry on the same instance works.
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None
            raise RuntimeError(
                f"attach_over_cdp: failed to connect to {normalised}: {e}"
            ) from e

        self._remote_browser = remote_browser
        self._attached_cdp_url = normalised
        self._attached = True
        # #439: attach path — will be refined to OWNED or ADOPTED below.

        # #452: wrap post-connect steps so that ctx creation, page creation, or stealth
        # failures roll back _pw / _remote_browser / any owned ctx we created, and reset
        # attach state for clean retry on same instance. Never close adopted user resources.
        try:
            # Pick or create the context we will drive.
            existing_contexts = list(remote_browser.contexts)
            adopted_index: Any
            if new_context or not existing_contexts:
                ctx_opts = dict(context_options or {})
                ctx = await remote_browser.new_context(**ctx_opts)
                self._attached_context_is_ours = True
                # #439: we own the context, but not the browser process
                self._teardown_mode = TeardownMode.ATTACHED_OWNED_CTX
                adopted_index = "new"
            else:
                if context_index < 0 or context_index >= len(existing_contexts):
                    raise IndexError(
                        f"context_index {context_index} out of range "
                        f"(remote browser has {len(existing_contexts)} contexts)"
                    )
                ctx = existing_contexts[context_index]
                self._attached_context_is_ours = False
                # #439: we adopted a user-owned context — do NOT close it on teardown
                self._teardown_mode = TeardownMode.ATTACHED_ADOPTED_CTX
                adopted_index = context_index

            self.browser = ctx  # AgentBrowser treats `browser` as the active context
            self.browser_context = ctx
            self.context = ctx

            # Stealth layer: init scripts apply to future pages (and re-apply on every
            # navigation in existing pages). Launch-time tricks are unavailable.
            stealth_installed = False
            stealth_error: Optional[str] = None
            if apply_stealth:
                session_name = (self.session or {}).get("name", "default-session")
                fp_seed = f"agentic-{session_name}-canvas-v4"
                stealth_script = get_stealth_script(
                    fingerprint_seed=fp_seed, attach_mode=True
                )
                try:
                    await ctx.add_init_script(stealth_script)
                    stealth_installed = True
                except Exception as e:
                    # Non-fatal: caller still gets a working attached context, but
                    # the failure is surfaced in the return payload so callers
                    # can log/alert rather than silently believing stealth is on.
                    stealth_error = f"{type(e).__name__}: {e}"
                    _logger = getattr(self, "logger", None)
                    if _logger is not None:
                        try:
                            _logger.warning(
                                "attach_over_cdp: stealth init script install failed: %s",
                                stealth_error,
                            )
                        except Exception:
                            pass

            # Reuse the first existing page when adopting, else open a fresh one.
            # #451: for adopted existing pages (new_context=False and pages present) we do not own
            # the tab and must leave it open on close() to honor the attach contract.
            try:
                pages = list(ctx.pages)
                if pages and not new_context:
                    self.page = pages[0]
                    self._owns_page = False
                else:
                    self.page = await ctx.new_page()
                    self._owns_page = True
            except Exception:
                self.page = await ctx.new_page()
                self._owns_page = True

            # #453: initialize runtime helpers (human, logger, scraper, recovery) so that
            # documented safe_goto/safe_click/safe_type and MCP stealth_scrape work on
            # attached sessions. Launch-only deep stealth (TLS etc) remain in degradation list.
            self.human = HumanBehavior(
                self.page,
                rng=self.rng,
                device_profile=getattr(self.persona, "device", None),
            )
            self.orchestrator = BehaviorOrchestrator(self.human, rng=self.rng)
            try:
                await self.human.initialize_mouse_tracker()
            except Exception:
                pass
            self.logger = AuditLogger(
                (self.session or {}).get("name", "attached-session"),
                correlation_id=getattr(
                    getattr(self, "metrics", None), "get_correlation_id", lambda: None
                )(),
            )
            self.scraper = StealthScraper(self.page, self.human, self.orchestrator)
            self.ai = AIHooks(provider="none")
            try:
                self.recovery = AntiBlockOrchestrator(
                    browser=self.browser,
                    session_manager=getattr(self, "session_manager", None),
                    proxy_manager=getattr(self, "proxy_manager", None),
                    page_getter=getattr(self, "page_getter", None)
                    or (lambda: self.page),
                    light_mode=getattr(self, "light_mode", None),
                    rng=self.rng,
                )
            except Exception:
                self.recovery = None
            if self.recovery:
                self.recovery.metrics = self.metrics

            # Best-effort version probe (non-fatal)
            browser_version = "unknown"
            try:
                browser_version = remote_browser.version  # property on PW Browser
            except Exception:
                pass

            return {
                "cdp_url": normalised,
                "browser_version": browser_version,
                "context_count": len(existing_contexts),
                "adopted_context_index": adopted_index,
                "stealth_applied": stealth_installed,
                "stealth_requested": bool(apply_stealth),
                "stealth_error": stealth_error,
                "degradation": [
                    "tls_ja3_ja4_fingerprint_not_applied (process-level)",
                    "launch_args_and_user_data_dir_not_applied (process-level)",
                    "regional_preset_tls_profile_not_applied (process-level)",
                    "already_open_pages_only_patched_on_next_navigation",
                ],
                "warning": (
                    "SECURITY: attach_over_cdp grants full control of the remote "
                    "browser including any authenticated user sessions. Only attach "
                    "to endpoints you own. Never expose the remote-debugging port "
                    "to untrusted networks."
                ),
            }
        except Exception as e:
            # #452: best-effort rollback of anything we allocated after successful connect.
            # Close only our created ctx (never adopted user ctxs or the external browser).
            try:
                if getattr(self, "_attached_context_is_ours", False) and getattr(
                    self, "browser", None
                ):
                    await self.browser.close()
            except Exception:
                pass
            self.browser = None
            self.browser_context = None
            self.context = None
            try:
                remote = getattr(self, "_remote_browser", None)
                if remote is not None:
                    await remote.close()
            except Exception:
                pass
            self._remote_browser = None
            if getattr(self, "_pw", None):
                try:
                    await self._pw.stop()
                except Exception:
                    pass
                self._pw = None
            self._attached = False
            self._attached_cdp_url = None
            self._attached_context_is_ours = False
            self._teardown_mode = None
            self.page = None
            self._owns_page = False
            raise RuntimeError(
                f"attach_over_cdp: post-connect failure (ctx/page/stealth) for {normalised}: {e}"
            ) from e

    async def close(self):
        """Close the browser, page, and underlying Playwright instance.

        This method is idempotent and safe to call multiple times.

        Attach mode (after ``attach_over_cdp``): the externally-launched browser
        process is preserved. Only contexts/pages created by this AgentBrowser
        are closed; adopted user contexts are left untouched.
        """
        try:
            if self.page and getattr(self, "_owns_page", True):
                # #451: only close pages we created/own; adopted user tabs and externally
                # supplied pages via switch_to_page(new) must survive our close().
                try:
                    await self.page.close()
                except Exception:
                    pass
                self.page = None
            else:
                # adopted or non-owned page: clear ref but leave the tab alive
                self.page = None

            if self.browser:
                try:
                    # #439: dispatch on TeardownMode enum instead of scattered
                    # getattr flag checks. Each branch is responsible for
                    # exactly the teardown it owns.
                    mode = self._teardown_mode
                    if mode == TeardownMode.ATTACHED_OWNED_CTX:
                        # We created the context → close it.
                        try:
                            await self.browser.close()
                        except Exception:
                            pass
                        # Then disconnect from the remote browser without killing it.
                        remote = getattr(self, "_remote_browser", None)
                        if remote is not None:
                            try:
                                await remote.close()
                            except Exception:
                                pass
                            self._remote_browser = None
                    elif mode == TeardownMode.ATTACHED_ADOPTED_CTX:
                        # Adopted user context → NEVER close it. Just disconnect.
                        remote = getattr(self, "_remote_browser", None)
                        if remote is not None:
                            try:
                                await remote.close()
                            except Exception:
                                pass
                            self._remote_browser = None
                    elif mode == TeardownMode.POOLED and getattr(self, "_pool", None):
                        # Borrowed a context from the pool → release it back.
                        await self._pool.release_context(self.browser)
                    elif mode == TeardownMode.LAUNCHED:
                        # We launched the browser process → close it.
                        await self.browser.close()
                    # mode is None → no browser was ever set up; no-op
                except Exception:
                    pass
                self.browser = None
                self.browser_context = None
                self.context = None
                self._pooled_ctx_id = None
                self._teardown_mode = None  # reset for potential re-use

            if getattr(self, "_using_pool", False):
                # do not shutdown shared pool here; individual close only releases its ctx
                # full shutdown via _pool.shutdown() on app exit if desired
                pass
            elif hasattr(self, "_pw") and self._pw:
                try:
                    await self._pw.stop()
                except Exception:
                    pass
                self._pw = None

            # Best-effort cleanup of other resources
            self.human = None
            self.orchestrator = None
            self.recovery = None
            self._owns_page = False
            if getattr(self, "logger", None):
                try:
                    self.logger.log_action("browser_closed", {})
                except Exception:
                    pass
                try:
                    self.logger.close()
                except Exception:
                    pass
                self.logger = None
        except Exception:
            # Never let close() itself raise — we want reliable cleanup
            pass

    async def __aenter__(self):
        """Support for `async with AgentBrowser(...) as browser:` usage.

        This implements GitHub issue #292 (proper context manager for reliable cleanup).
        """
        if not self.browser:
            # Default launch parameters — callers can still call launch() explicitly first
            try:
                await self.launch(
                    light_mode=getattr(self, "light_mode", None),
                    use_pooled_context=getattr(
                        self, "use_pooled_context", None
                    ),  # #57 etc: preserve pooled opt-in on contextmanager implicit launch
                    resume=getattr(self, "_resume", False),  # P2 resume preservation
                    launch_options=getattr(
                        self, "_custom_launch_options", None
                    ),  # #143: preserve custom opts on implicit launch
                    preset=getattr(
                        self, "current_preset", None
                    ),  # #457: support preset/region via ctor + implicit aenter for CLI
                    region=getattr(self, "current_region", None),
                )
            except Exception:
                await self.close()
                raise
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Guarantee cleanup even if an exception occurs inside the `async with` block."""
        await self.close()
        return False  # do not suppress exceptions
