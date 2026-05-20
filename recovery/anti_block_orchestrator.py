"""
Anti-Block Orchestrator v2
Smart, context-aware rate limit and block recovery for the Agentic Browser.
Handles early detection, platform-specific strategies, and intelligent rotation.

Phase 8 fixes:
- Circuit breaker for rapid repeated failures per platform/domain (#130 P1)
- Light detection mode (default) to avoid expensive page.content() calls on every check (#52, #53, #76, #84, #92, #174 P1/P2 performance)
- Throttled / conditional heavy content analysis (only when light=False or force_heavy)
- Deduped duplicate return in calculate_backoff
- Cost awareness stub + escalation hooks for future (#252, #276, #283)
- Better failure tracking and logging
"""

import asyncio
import time
import random
from typing import Dict, Any, Optional, Callable
from enum import Enum
from dataclasses import dataclass, field

from audit.logger import AuditLogger


class BlockType(Enum):
    NONE = "none"
    SOFT_RATE_LIMIT = "soft_rate_limit"
    HARD_RATE_LIMIT = "hard_rate_limit"
    CAPTCHA = "captcha"
    ACCOUNT_RESTRICTION = "account_restriction"
    PROXY_BLOCK = "proxy_block"
    UNKNOWN = "unknown"


@dataclass
class RecoveryContext:
    platform: str
    url: str
    attempt: int = 1
    last_error: Optional[str] = None
    block_type: BlockType = BlockType.NONE
    response_time: float = 0.0
    http_status: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class AntiBlockOrchestrator:
    """
    Central coordinator for detecting and recovering from blocks/rate limits.
    Much more aggressive and intelligent than basic try/except.

    Phase 8 improvements focus on performance (avoid content() spam) and resilience (circuit breaker).
    """

    # Platform-specific recovery strategies
    PLATFORM_STRATEGIES = {
        "linkedin": {
            "max_retries": 5,
            "base_backoff": 45,          # seconds
            "max_backoff": 300,
            "jitter": 0.3,
            "rotate_session_after": 3,
            "rotate_proxy_after": 4,
        },
        "amazon": {
            "max_retries": 4,
            "base_backoff": 30,
            "max_backoff": 180,
            "jitter": 0.4,
            "rotate_session_after": 2,
            "rotate_proxy_after": 3,
        },
        "google": {
            "max_retries": 3,
            "base_backoff": 20,
            "max_backoff": 120,
            "jitter": 0.35,
            "rotate_session_after": 2,
            "rotate_proxy_after": 2,
        },
        "default": {
            "max_retries": 4,
            "base_backoff": 25,
            "max_backoff": 180,
            "jitter": 0.3,
            "rotate_session_after": 3,
            "rotate_proxy_after": 3,
        }
    }

    def __init__(self, browser=None, session_manager=None, proxy_manager=None, page_getter=None, light_detection: bool = True):
        self.browser = browser          # usually the BrowserContext (for future use)
        self.session_manager = session_manager
        self.proxy_manager = proxy_manager
        self._get_page = page_getter    # callable that returns current Playwright Page (for content checks)
        self.logger = AuditLogger("recovery")
        self.recovery_history: Dict[str, int] = {}  # platform -> consecutive recoveries

        # === Phase 8 Performance & Resilience ===
        self.light_detection = light_detection  # default True -> huge perf win (skips content() most times)
        self.circuit_breaker_threshold = 5
        self.circuit_cooldown = 300  # seconds (5 min)
        self.failure_counts: Dict[str, int] = {}
        self.circuit_open_until: Dict[str, float] = {}
        self.cost_tracker: Dict[str, float] = {}  # stub for #252 cost awareness

    def _check_circuit_breaker(self, key: str) -> bool:
        """Return True if circuit is currently open for this key (platform/domain). Addresses #130."""
        now = time.time()
        until = self.circuit_open_until.get(key, 0)
        if now < until:
            return True
        return False

    def _record_failure(self, key: str, cost: float = 1.0) -> None:
        """Record failure and possibly trip circuit breaker."""
        self.failure_counts[key] = self.failure_counts.get(key, 0) + 1
        self.cost_tracker[key] = self.cost_tracker.get(key, 0.0) + cost
        if self.failure_counts[key] >= self.circuit_breaker_threshold:
            self.circuit_open_until[key] = time.time() + self.circuit_cooldown
            self.logger.log_action("circuit_breaker_opened", {
                "key": key,
                "cooldown_sec": self.circuit_cooldown,
                "failures": self.failure_counts[key],
                "cost": self.cost_tracker.get(key)
            })
            # reset count after opening to allow eventual retry
            self.failure_counts[key] = 0

    def _reset_circuit(self, key: str) -> None:
        self.failure_counts[key] = 0
        if key in self.circuit_open_until:
            del self.circuit_open_until[key]

    async def detect_block(self, context: RecoveryContext, force_heavy: bool = False) -> BlockType:
        """
        Early detection of blocks using multiple signals:
        - HTTP status codes
        - Response timing anomalies
        - Page content patterns (HEAVY - only when not light_detection or force_heavy)  # perf fixes
        - Platform-specific heuristics

        light_detection=True (default) avoids the expensive await page.content() on hot paths.
        """
        status = context.http_status
        response_time = context.response_time
        error_lower = (context.last_error or "").lower()
        platform = context.platform.lower()

        # === Strong HTTP signals ===
        if status == 429:
            return BlockType.HARD_RATE_LIMIT
        if status == 403:
            return BlockType.SOFT_RATE_LIMIT
        if status in [503, 502]:
            return BlockType.PROXY_BLOCK

        # === Timing anomalies ===
        if status == 200 and response_time > 12.0:
            return BlockType.SOFT_RATE_LIMIT

        # === Error message patterns ===
        captcha_keywords = ["captcha", "challenge", "verify", "security check", "robot check"]
        if any(kw in error_lower for kw in captcha_keywords):
            return BlockType.CAPTCHA

        if "rate limit" in error_lower or "too many requests" in error_lower:
            return BlockType.HARD_RATE_LIMIT

        if "blocked" in error_lower or "access denied" in error_lower:
            if "amazon" in platform or "proxy" in error_lower:
                return BlockType.PROXY_BLOCK
            return BlockType.SOFT_RATE_LIMIT

        # === Platform-specific detection ===
        if "linkedin" in platform:
            linkedin_blocks = [
                "unusual activity", "security verification", "verify your identity",
                "temporarily restricted", "account restricted"
            ]
            if any(kw in error_lower for kw in linkedin_blocks):
                return BlockType.ACCOUNT_RESTRICTION
            if "rate limit" in error_lower:
                return BlockType.HARD_RATE_LIMIT

        if "amazon" in platform:
            amazon_blocks = ["sorry", "robot", "unusual activity", "captcha"]
            if any(kw in error_lower for kw in amazon_blocks):
                return BlockType.CAPTCHA

        # === Browser content analysis (EXPENSIVE - gated by light_detection) ===
        # Phase 8 perf fix: content() is called far too often in recovery paths.
        # Only run when light_detection=False or explicitly forced (for deep debug / #273 explain).
        do_heavy = force_heavy or (not getattr(self, 'light_detection', True))
        if self._get_page and do_heavy:
            try:
                page = self._get_page()
                content_lower = ""
                if page:
                    page_content = await page.content()
                    content_lower = page_content.lower()[:3000]

                if content_lower:
                    # Cloudflare / generic challenge pages
                    if any(x in content_lower for x in ["checking your browser", "just a moment", "cf-challenge"]):
                        return BlockType.CAPTCHA

                    # LinkedIn specific content
                    if "linkedin" in platform:
                        if any(x in content_lower for x in ["security verification", "unusual activity detected"]):
                            return BlockType.ACCOUNT_RESTRICTION

                    # Amazon specific
                    if "amazon" in platform:
                        if any(x in content_lower for x in ["enter the characters", "sorry, we just need to make sure"]):
                            return BlockType.CAPTCHA

            except Exception:
                pass  # Browser content check failed, continue with other signals

        return BlockType.NONE

    def get_strategy(self, platform: str) -> Dict[str, Any]:
        platform = platform.lower()
        for key in self.PLATFORM_STRATEGIES:
            if key in platform:
                return self.PLATFORM_STRATEGIES[key]
        return self.PLATFORM_STRATEGIES["default"]

    def calculate_backoff(self, context: RecoveryContext) -> float:
        """Exponential backoff with jitter (duplicate return removed)"""
        strategy = self.get_strategy(context.platform)
        base = strategy["base_backoff"]
        max_backoff = strategy["max_backoff"]
        jitter = strategy["jitter"]

        backoff = min(base * (2 ** (context.attempt - 1)), max_backoff)
        jitter_amount = backoff * jitter * random.uniform(-1, 1)
        return max(5.0, backoff + jitter_amount)

    def _safe_extract_base_user(self, proxy_username: str) -> str:
        """Robustly extract the base 'user' part from Decodo proxy username string.
        Format is typically 'user-REALUSER-country-...-session-...'.
        Never crashes recovery; falls back to 'default'.
        Addresses #99, #10.
        """
        if not proxy_username or not isinstance(proxy_username, str):
            return "default"
        try:
            parts = proxy_username.split("-")
            # Common: ['user', 'REALUSER', 'country', ...]
            if len(parts) > 1 and parts[0].lower() == "user":
                return parts[1]
            # Fallback search for first non-empty token after initial 'user-'
            if proxy_username.lower().startswith("user-"):
                after = proxy_username[5:]
                if "-" in after:
                    return after.split("-", 1)[0]
                if after:
                    return after
        except Exception:
            pass
        return "default"

    async def recover(self, context: RecoveryContext) -> bool:
        """
        Main recovery flow with actual proxy/session rotation.
        Returns True if we should continue retrying.
        Now includes circuit breaker check (P1 #130).
        """
        key = context.platform.lower()

        # Circuit breaker guard (prevents hammering on hopeless cases)
        if self._check_circuit_breaker(key):
            self.logger.log_action("circuit_breaker_blocked_recovery", {
                "platform": context.platform,
                "attempt": context.attempt
            })
            return False

        block_type = await self.detect_block(context)
        context.block_type = block_type

        strategy = self.get_strategy(context.platform)

        self.logger.log_action(
            "block_detected",
            {
                "platform": context.platform,
                "block_type": block_type.value,
                "attempt": context.attempt,
                "url": context.url,
                "http_status": context.http_status,
            }
        )

        if block_type == BlockType.NONE:
            self._reset_circuit(key)  # success path clears circuit
            return True

        # Record failure for circuit breaker and cost tracking
        self._record_failure(key, cost=1.0 + (0.5 if block_type in (BlockType.HARD_RATE_LIMIT, BlockType.ACCOUNT_RESTRICTION) else 0))

        # === Actual rotation logic ===
        should_rotate_session = context.attempt >= strategy.get("rotate_session_after", 3)
        should_rotate_proxy = context.attempt >= strategy.get("rotate_proxy_after", 3)

        if should_rotate_session and self.session_manager:
            try:
                self.logger.log_action("recovery_rotate_session", {
                    "platform": context.platform,
                    "attempt": context.attempt
                })
                # Create a fresh session
                new_session = self.session_manager.create_session(
                    session_name=f"recovery-{context.platform}-{context.attempt}",
                    anonymous=True
                )
                context.metadata["new_session"] = new_session.get("name")
            except Exception as e:
                self.logger.log_error("session_rotation_failed", str(e))

        if should_rotate_proxy and self.proxy_manager:
            try:
                self.logger.log_action("recovery_rotate_proxy", {
                    "platform": context.platform,
                    "attempt": context.attempt
                })
                # Generate new sticky session (robust, #99/#10)
                if getattr(self.proxy_manager, 'current_config', None):
                    cfg = self.proxy_manager.current_config
                    base_user = self._safe_extract_base_user(getattr(cfg, 'username', None))
                    pwd = getattr(cfg, 'password', "")
                    ctry = getattr(cfg, 'country', "jp")
                    new_config = self.proxy_manager.create_decodo_config(
                        user=base_user,
                        password=pwd,
                        country=ctry,
                        session_name=f"recovery-{context.attempt}",
                        duration_minutes=30  # shorter duration for recovery
                    )
                    # Ensure manager state is updated for future use
                    self.proxy_manager.current_config = new_config
                    context.metadata["new_proxy"] = new_config.session_name
                    context.metadata["new_proxy_config"] = {
                        "session_name": new_config.session_name,
                        "country": ctry
                    }
            except Exception as e:
                self.logger.log_error("proxy_rotation_failed", str(e))

        # Calculate and apply backoff
        delay = self.calculate_backoff(context)
        self.logger.log_action(
            "recovery_backoff",
            {"platform": context.platform, "delay_seconds": round(delay, 1), "attempt": context.attempt}
        )

        await asyncio.sleep(delay)

        # Update history
        self.recovery_history[context.platform] = self.recovery_history.get(context.platform, 0) + 1

        return context.attempt < strategy["max_retries"]

    async def execute_with_recovery(
        self,
        func: Callable,
        platform: str,
        url: str,
        max_retries: Optional[int] = None,
        **kwargs
    ):
        """
        Wrapper that runs a function with full recovery logic.
        """
        context = RecoveryContext(platform=platform, url=url)
        strategy = self.get_strategy(platform)
        max_retries = max_retries or strategy["max_retries"]

        for attempt in range(1, max_retries + 1):
            context.attempt = attempt
            start_time = time.time()

            key = platform.lower()
            if self._check_circuit_breaker(key):
                self.logger.log_action("circuit_breaker_blocked_execute", {"platform": platform})
                break

            try:
                result = await func(**kwargs) if asyncio.iscoroutinefunction(func) else func(**kwargs)
                context.response_time = time.time() - start_time

                # Check if we got a successful response
                if hasattr(result, "status"):
                    context.http_status = result.status

                block_type = await self.detect_block(context)
                if block_type == BlockType.NONE:
                    self._reset_circuit(key)
                    return result

                # If we detect a block even on "success", treat it as failure
                context.last_error = f"Detected {block_type.value}"
                should_continue = await self.recover(context)
                if not should_continue:
                    break

            except Exception as e:
                context.last_error = str(e)
                context.response_time = time.time() - start_time
                should_continue = await self.recover(context)
                if not should_continue:
                    raise

        raise RuntimeError(f"Max retries exceeded for {platform} after {max_retries} attempts")


# Convenience function
def create_orchestrator(browser=None, session_manager=None, proxy_manager=None, page_getter=None, light_detection: bool = True):
    return AntiBlockOrchestrator(
        browser, session_manager, proxy_manager, page_getter=page_getter, light_detection=light_detection
    )
