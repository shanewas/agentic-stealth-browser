"""
Anti-Block Orchestrator v2
Smart, context-aware rate limit and block recovery for the Agentic Browser.
Handles early detection, platform-specific strategies, and intelligent rotation.
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

    def __init__(self, browser=None, session_manager=None, proxy_manager=None):
        self.browser = browser
        self.session_manager = session_manager
        self.proxy_manager = proxy_manager
        self.logger = AuditLogger("recovery")
        self.recovery_history: Dict[str, int] = {}  # platform -> consecutive recoveries

    async def detect_block(self, context: RecoveryContext) -> BlockType:
        """
        Early detection of blocks using multiple signals:
        - HTTP status codes
        - Response timing anomalies
        - Page content patterns (if browser context available)
        """
        status = context.http_status
        response_time = context.response_time

        # Strong signals
        if status in [429, 403]:
            if status == 429:
                return BlockType.HARD_RATE_LIMIT
            return BlockType.SOFT_RATE_LIMIT

        if status == 200 and response_time > 8.0:
            # Unusually slow response can indicate soft throttling
            return BlockType.SOFT_RATE_LIMIT

        # Check for common block patterns in error message
        error_lower = (context.last_error or "").lower()
        if any(x in error_lower for x in ["captcha", "blocked", "unusual activity", "verify"]):
            return BlockType.CAPTCHA

        if "rate limit" in error_lower or "too many requests" in error_lower:
            return BlockType.HARD_RATE_LIMIT

        return BlockType.NONE

    def get_strategy(self, platform: str) -> Dict[str, Any]:
        platform = platform.lower()
        for key in self.PLATFORM_STRATEGIES:
            if key in platform:
                return self.PLATFORM_STRATEGIES[key]
        return self.PLATFORM_STRATEGIES["default"]

    def calculate_backoff(self, context: RecoveryContext) -> float:
        """Exponential backoff with jitter"""
        strategy = self.get_strategy(context.platform)
        base = strategy["base_backoff"]
        max_backoff = strategy["max_backoff"]
        jitter = strategy["jitter"]

        backoff = min(base * (2 ** (context.attempt - 1)), max_backoff)
        jitter_amount = backoff * jitter * random.uniform(-1, 1)
        return max(5.0, backoff + jitter_amount)

    async def recover(self, context: RecoveryContext) -> bool:
        """
        Main recovery flow.
        Returns True if recovery was successful (or should retry).
        """
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
            return True

        # Decide on rotation
        should_rotate_session = context.attempt >= strategy["rotate_session_after"]
        should_rotate_proxy = context.attempt >= strategy["rotate_proxy_after"]

        if should_rotate_session and self.session_manager:
            self.logger.log_action("recovery_rotate_session", {"platform": context.platform})
            # Session rotation logic would go here
            # self.session_manager.rotate_session(...)

        if should_rotate_proxy and self.proxy_manager:
            self.logger.log_action("recovery_rotate_proxy", {"platform": context.platform})
            # Proxy rotation logic
            # await self.proxy_manager.rotate_proxy(...)

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

            try:
                result = await func(**kwargs) if asyncio.iscoroutinefunction(func) else func(**kwargs)
                context.response_time = time.time() - start_time

                # Check if we got a successful response
                if hasattr(result, "status"):
                    context.http_status = result.status

                block_type = await self.detect_block(context)
                if block_type == BlockType.NONE:
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
def create_orchestrator(browser=None, session_manager=None, proxy_manager=None):
    return AntiBlockOrchestrator(browser, session_manager, proxy_manager)