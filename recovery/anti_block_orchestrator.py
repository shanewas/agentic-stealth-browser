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
- #90 P1: automatic session/cookie cleanup on ACCOUNT_RESTRICTION detection
- #92/#84 final: simple guards + lighter signals (title before content) + light_mode tie-in

P2 Recovery Cluster (#112 #139 #151 #157 #171 #184):
- Full error taxonomy: BlockType + ErrorSeverity + RecoveryAction enums
- Safe mode / fail-fast config (never rotate proxies to protect pool)
- Platform-aware decisions + preferred actions in strategies
- Custom recovery strategy registry for extensibility per platform
- Learning from history: per-account/domain action success rates
- Explicit transient network error distinction (light treatment, no rotation)
- RNG wiring support + rotation hook invocation for end-to-end functional recovery
"""

import asyncio
import time
import random
import uuid
from typing import Dict, Any, Optional, Callable
from enum import Enum
from dataclasses import dataclass, field

from audit.logger import AuditLogger


class BlockType(Enum):
    """Error taxonomy for blocks and failures (#112).

    Expanded with TRANSIENT_ERROR to distinguish from real blocks (#171).
    Used consistently with RecoveryAction and ErrorSeverity for policy decisions.
    """

    NONE = "none"
    SOFT_RATE_LIMIT = "soft_rate_limit"
    HARD_RATE_LIMIT = "hard_rate_limit"
    CAPTCHA = "captcha"
    ACCOUNT_RESTRICTION = "account_restriction"
    PROXY_BLOCK = "proxy_block"
    UNKNOWN = "unknown"
    TRANSIENT_ERROR = "transient_error"  # network/timeout/DNS etc - do not trigger heavy rotation (#171)


class ErrorSeverity(Enum):
    """Severity levels in the error taxonomy (#112)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class MaxRetriesExceeded(Exception):
    """Raised when execute_with_recovery exceeds its maximum retry count.

    Attributes:
        platform: The platform/domain being accessed.
        max_retries: The retry limit that was exceeded.
        last_error: The error string from the final attempt.
    """

    def __init__(
        self,
        message: str,
        platform: str = "",
        max_retries: int = 0,
        last_error: str | None = None,
    ):
        super().__init__(message)
        self.platform = platform
        self.max_retries = max_retries
        self.last_error = last_error


class RecoveryAction(Enum):
    """Structured, actionable recovery decisions (#112, #139, #157, #171, #184).

    Enables consistent policy, logging, and custom strategy plugins (#151).
    """

    RETRY = "retry"
    BACKOFF = "backoff_and_retry"
    ROTATE_SESSION_ONLY = "rotate_session"
    ROTATE_PROXY_ONLY = "rotate_proxy"
    ROTATE_BOTH = "rotate_both"
    FAIL_FAST = "fail_fast"
    NOOP = "noop"
    CUSTOM = "custom"


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
    session_name: Optional[str] = None  # for #90 cleanup wiring
    error_severity: ErrorSeverity = ErrorSeverity.MEDIUM
    recovery_action: Optional[RecoveryAction] = None
    account_hint: Optional[str] = None


class AntiBlockOrchestrator:
    """
    Central coordinator for detecting and recovering from blocks/rate limits.
    Much more aggressive and intelligent than basic try/except.

    Phase 8 improvements focus on performance (avoid content() spam) and resilience (circuit breaker).
    """

    # Platform-specific recovery strategies
    # Enhanced for platform-aware recovery (#139): preferred_first_action, transient tuning etc.
    PLATFORM_STRATEGIES = {
        "linkedin": {
            "max_retries": 5,
            "base_backoff": 45,  # seconds
            "max_backoff": 300,
            "jitter": 0.3,
            "rotate_session_after": 3,
            "rotate_proxy_after": 4,
            "preferred_first_action": "rotate_session",  # account restrictions often session/cookie related
            "transient_backoff_multiplier": 0.6,
        },
        "amazon": {
            "max_retries": 4,
            "base_backoff": 30,
            "max_backoff": 180,
            "jitter": 0.4,
            "rotate_session_after": 2,
            "rotate_proxy_after": 3,
            "preferred_first_action": "rotate_proxy",  # proxy reputation heavy for amazon
            "transient_backoff_multiplier": 0.7,
        },
        "google": {
            # ponytail: no content-detector for google strategy, falls back to defaults
            "max_retries": 3,
            "base_backoff": 20,
            "max_backoff": 120,
            "jitter": 0.35,
            "rotate_session_after": 2,
            "rotate_proxy_after": 2,
            "preferred_first_action": "backoff_and_retry",
            "transient_backoff_multiplier": 0.5,
        },
        "default": {
            "max_retries": 4,
            "base_backoff": 25,
            "max_backoff": 180,
            "jitter": 0.3,
            "rotate_session_after": 3,
            "rotate_proxy_after": 3,
            "preferred_first_action": "backoff_and_retry",
            "transient_backoff_multiplier": 0.8,
        },
    }

    def __init__(
        self,
        browser=None,
        session_manager=None,
        proxy_manager=None,
        page_getter=None,
        light_detection: bool = True,
        light_mode: Optional[bool] = None,
        rng: Optional[Any] = None,
        safe_mode: bool = False,
        recovery_mode: str = "aggressive",
    ):
        self.browser = browser  # usually the BrowserContext (for future use)
        self.metrics = None  # set by AgentBrowser; None-safe
        self.session_manager = session_manager
        self.proxy_manager = proxy_manager
        self._get_page = page_getter  # callable that returns current Playwright Page (for content checks)
        self.logger = AuditLogger("recovery")
        # Enhanced recovery history for learning from past successes/failures (#157)
        # Keyed by "platform:account:domain" -> stats with per-action success/fail rates + preferred
        self.recovery_history: Dict[str, Dict[str, Any]] = {}
        self._max_history_size = 500  # LRU cap to prevent unbounded memory growth
        self.custom_strategies: Dict[
            str, Callable[[RecoveryContext, BlockType], RecoveryAction]
        ] = {}  # #151 plugin registry

        # Support per-instance RNG for jitter (fixes wiring from AgentBrowser #222)
        self.rng = rng if rng is not None else random

        # Safe mode / recovery mode for #184: fail_fast or safe never burns proxies
        self.safe_mode = bool(safe_mode)
        self.recovery_mode = (recovery_mode or "aggressive").lower()

        # === Phase 8 Performance & Resilience ===
        # Tie into light_mode if present (for #84/#92 callers using alternate naming)
        if light_mode is not None:
            light_detection = bool(light_mode)
        self.light_detection = light_detection  # default True -> huge perf win (skips content() most times)
        self.circuit_breaker_threshold = 5
        self.circuit_cooldown = 300  # seconds (5 min)
        self.failure_counts: Dict[str, int] = {}
        self.circuit_open_until: Dict[str, float] = {}
        self.cost_tracker: Dict[str, float] = {}  # stub for #252 cost awareness

        # #90 P1 cookie cleanup support
        self.current_session_name: Optional[str] = None

        # Taxonomy severity map (#112)
        self.block_type_to_severity: Dict[BlockType, ErrorSeverity] = {
            BlockType.TRANSIENT_ERROR: ErrorSeverity.LOW,
            BlockType.NONE: ErrorSeverity.LOW,
            BlockType.SOFT_RATE_LIMIT: ErrorSeverity.MEDIUM,
            BlockType.PROXY_BLOCK: ErrorSeverity.MEDIUM,
            BlockType.HARD_RATE_LIMIT: ErrorSeverity.HIGH,
            BlockType.CAPTCHA: ErrorSeverity.HIGH,
            BlockType.ACCOUNT_RESTRICTION: ErrorSeverity.CRITICAL,
            BlockType.UNKNOWN: ErrorSeverity.MEDIUM,
        }

    def set_current_session_name(self, name: Optional[str]) -> None:
        """Allow AgentBrowser to wire the active session for #90 auto-cleanup on restriction."""
        self.current_session_name = name

    def register_recovery_strategy(
        self,
        platform: str,
        strategy_func: Callable[[RecoveryContext, BlockType], RecoveryAction],
    ) -> None:
        """Register a custom recovery decision function for a platform (#151).

        The func receives (RecoveryContext, BlockType) and must return a RecoveryAction (or raise to fallback).
        Enables site-specific logic without forking the orchestrator.
        """
        if not platform or not callable(strategy_func):
            raise ValueError("platform and callable strategy_func required")
        self.custom_strategies[platform.lower()] = strategy_func
        self.logger.log_action("custom_strategy_registered", {"platform": platform})

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
            self.logger.log_action(
                "circuit_breaker_opened",
                {
                    "key": key,
                    "cooldown_sec": self.circuit_cooldown,
                    "failures": self.failure_counts[key],
                    "cost": self.cost_tracker.get(key),
                },
            )
            # reset count after opening to allow eventual retry
            self.failure_counts[key] = 0

    def _reset_circuit(self, key: str) -> None:
        self.failure_counts[key] = 0
        if key in self.circuit_open_until:
            del self.circuit_open_until[key]

    def _get_history_key(self, context: RecoveryContext) -> str:
        """Per-account/domain history key for learning (#157)."""
        platform = (context.platform or "unknown").lower()
        acct = (
            context.account_hint
            or context.metadata.get("account")
            or context.session_name
            or context.metadata.get("new_session")
            or "default"
        )
        if isinstance(acct, dict):
            acct = acct.get("name", "default")
        try:
            from urllib.parse import urlparse

            domain = (urlparse(context.url or "").netloc or "unknown").lower()
        except Exception:
            domain = "unknown"
        return f"{platform}:{str(acct).lower()}:{domain}"

    def _update_recovery_history(
        self, context: RecoveryContext, action: RecoveryAction, success: bool
    ) -> None:
        """Lightweight per-key success rate tracking for future decisions (#157 learning from history).

        Includes LRU eviction: when history exceeds _max_history_size entries,
        the oldest (lowest total_attempts) entries are pruned to prevent unbounded memory growth.
        """
        key = self._get_history_key(context)
        if key not in self.recovery_history:
            self.recovery_history[key] = {
                "action_success": {},
                "last_successful_action": None,
                "total_attempts": 0,
                "platforms": context.platform,
            }
        h = self.recovery_history[key]
        h["total_attempts"] = h.get("total_attempts", 0) + 1
        act_str = action.value if isinstance(action, RecoveryAction) else str(action)
        if "action_success" not in h:
            h["action_success"] = {}
        stats = h["action_success"].setdefault(act_str, {"success": 0, "fail": 0})
        if success:
            stats["success"] = stats.get("success", 0) + 1
            h["last_successful_action"] = act_str
        else:
            stats["fail"] = stats.get("fail", 0) + 1

        # Evict oldest entries when history exceeds size cap
        if len(self.recovery_history) > self._max_history_size:
            # Sort by total_attempts ascending — prune least-used entries first
            sorted_keys = sorted(
                self.recovery_history.keys(),
                key=lambda k: self.recovery_history[k].get("total_attempts", 0),
            )
            # Remove the oldest 20% (or at least 1)
            to_remove = max(1, len(sorted_keys) // 5)
            for old_key in sorted_keys[:to_remove]:
                del self.recovery_history[old_key]

    def _decide_recovery_action(
        self, context: RecoveryContext, block_type: BlockType
    ) -> RecoveryAction:
        """Core decision engine: platform-aware (#139), history-learned (#157), safe-mode aware (#184),
        taxonomy-driven (#112), transient-aware (#171), and supports custom plugins (#151).
        """
        platform = (context.platform or "default").lower()
        if block_type == BlockType.TRANSIENT_ERROR:
            return RecoveryAction.BACKOFF
        if block_type == BlockType.NONE:
            return RecoveryAction.NOOP

        # Safe mode / fail-fast (#184): never rotate, fail fast to protect proxy pool
        if self.safe_mode or self.recovery_mode in ("safe", "fail_fast"):
            if context.attempt >= 2 or block_type in (
                BlockType.ACCOUNT_RESTRICTION,
                BlockType.CAPTCHA,
                BlockType.HARD_RATE_LIMIT,
            ):
                return RecoveryAction.FAIL_FAST
            return RecoveryAction.BACKOFF

        # Custom registered strategy (#151)
        if platform in self.custom_strategies:
            try:
                custom_action = self.custom_strategies[platform](context, block_type)
                if isinstance(custom_action, RecoveryAction):
                    return custom_action
            except Exception as e:
                self.logger.log_error(
                    "custom_strategy_failed", str(e), {"platform": platform}
                )

        # History learning (#157): prefer previously successful action for this exact platform/account/domain
        hist_key = self._get_history_key(context)
        history = self.recovery_history.get(hist_key, {})
        action_stats = history.get("action_success", {})
        last_good = history.get("last_successful_action")
        if action_stats:
            best_action = None
            best_rate = -1.0
            for a_str, stats in action_stats.items():
                tot = stats.get("success", 0) + stats.get("fail", 0)
                if tot >= 2:  # only trust after some evidence
                    rate = stats.get("success", 0) / max(tot, 1)
                    if rate > best_rate:
                        best_rate = rate
                        best_action = a_str
            if best_action and best_rate >= 0.5:
                try:
                    return RecoveryAction(best_action)
                except ValueError:
                    pass
        if last_good:
            try:
                return RecoveryAction(last_good)
            except ValueError:
                pass

        # Platform-aware preferred action from strategy (#139)
        strategy = self.get_strategy(context.platform)
        pref = strategy.get("preferred_first_action")
        if pref:
            try:
                # map string like "rotate_session" to enum
                if pref == "rotate_session":
                    return RecoveryAction.ROTATE_SESSION_ONLY
                if pref == "rotate_proxy":
                    return RecoveryAction.ROTATE_PROXY_ONLY
                if "backoff" in pref:
                    return RecoveryAction.BACKOFF
                return (
                    RecoveryAction(pref)
                    if pref in [e.value for e in RecoveryAction]
                    else RecoveryAction.BACKOFF
                )
            except Exception:
                pass

        # Fallback taxonomy + attempt based
        if block_type in (BlockType.ACCOUNT_RESTRICTION, BlockType.CAPTCHA):
            return (
                RecoveryAction.ROTATE_SESSION_ONLY
                if context.attempt % 2 == 1
                else RecoveryAction.ROTATE_BOTH
            )
        if block_type == BlockType.PROXY_BLOCK:
            return RecoveryAction.ROTATE_PROXY_ONLY
        if block_type in (BlockType.HARD_RATE_LIMIT, BlockType.SOFT_RATE_LIMIT):
            if context.attempt >= strategy.get("rotate_proxy_after", 3):
                return (
                    RecoveryAction.ROTATE_BOTH
                    if context.attempt >= strategy.get("rotate_session_after", 3)
                    else RecoveryAction.ROTATE_SESSION_ONLY
                )
            return RecoveryAction.BACKOFF
        return RecoveryAction.BACKOFF

    async def detect_block(
        self, context: RecoveryContext, force_heavy: bool = False
    ) -> BlockType:
        """
        Early detection of blocks using multiple signals:
        - HTTP status codes
        - Response timing anomalies
        - Page content patterns (HEAVY - only when not light_detection or force_heavy)  # perf fixes
        - Platform-specific heuristics

        light_detection=True (default) avoids the expensive await page.content() on hot paths.
        Recovery paths always prefer cheap context signals first.
        """
        status = context.http_status
        response_time = context.response_time
        error_lower = (context.last_error or "").lower()
        platform = (context.platform or "default").lower()

        # #171: Distinguish transient network errors (timeouts, DNS, conn resets) from real blocks.
        # Transient: short backoff only, no rotation, no circuit trip, no proxy burn.
        transient_patterns = [
            "timeout",
            "timed out",
            "connection reset",
            "econnreset",
            "econnrefused",
            "dns",
            "name or service not known",
            "getaddrinfo",
            "network is unreachable",
            "connect call failed",
            "socket hang up",
            "connection refused",
            "connection error",
            "read timeout",
            "write timeout",
            "clientconnectorerror",
            "errno 110",
            "errno 111",
        ]
        if any(p in error_lower for p in transient_patterns):
            if status not in (
                403,
                429,
                503,
            ):  # explicit block statuses override transient guess
                context.block_type = BlockType.TRANSIENT_ERROR
                context.error_severity = ErrorSeverity.LOW
                return BlockType.TRANSIENT_ERROR

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
        captcha_keywords = [
            "captcha",
            "challenge",
            "verify",
            "security check",
            "robot check",
        ]
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
                "unusual activity",
                "security verification",
                "verify your identity",
                "temporarily restricted",
                "account restricted",
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
        # #84/#92: simple guard + lighter signals (title/url) before any full content()
        do_heavy = force_heavy or (not getattr(self, "light_detection", True))
        if self._get_page and do_heavy:
            try:
                page = self._get_page()
                content_lower = ""
                if page:
                    # Use lighter signals first (title is cheap vs full HTML) to avoid unnecessary page.content()
                    try:
                        title = (await page.title() or "").lower()
                        if any(
                            x in title
                            for x in [
                                "just a moment",
                                "checking your browser",
                                "attention required",
                                "verify you are human",
                                "security check",
                            ]
                        ):
                            return BlockType.CAPTCHA

                        # LinkedIn specific from title (common on challenges)
                        if "linkedin" in platform:
                            if any(
                                x in title
                                for x in [
                                    "security verification",
                                    "unusual activity detected",
                                    "account restricted",
                                ]
                            ):
                                return BlockType.ACCOUNT_RESTRICTION

                        # Amazon specific from title
                        if "amazon" in platform:
                            if any(
                                x in title
                                for x in [
                                    "enter the characters",
                                    "sorry, we just need to make sure",
                                    "robot",
                                ]
                            ):
                                return BlockType.CAPTCHA
                    except Exception:
                        pass  # lighter signal failed; fall through to content only if needed

                    # Full content() only as fallback after lighter signals (#84 #92 guard)
                    try:
                        page_content = await page.content()
                        content_lower = page_content.lower()[:3000]
                    except Exception:
                        content_lower = ""

                if content_lower:
                    # Cloudflare / generic challenge pages
                    if any(
                        x in content_lower
                        for x in [
                            "checking your browser",
                            "just a moment",
                            "cf-challenge",
                        ]
                    ):
                        return BlockType.CAPTCHA

                    # LinkedIn specific content
                    if "linkedin" in platform:
                        if any(
                            x in content_lower
                            for x in [
                                "security verification",
                                "unusual activity detected",
                            ]
                        ):
                            return BlockType.ACCOUNT_RESTRICTION

                    # Amazon specific
                    if "amazon" in platform:
                        if any(
                            x in content_lower
                            for x in [
                                "enter the characters",
                                "sorry, we just need to make sure",
                            ]
                        ):
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
        """Exponential backoff with jitter (duplicate return removed).
        Uses instance rng for #222. Applies platform transient multiplier when relevant (#171).
        """
        strategy = self.get_strategy(context.platform)
        base = strategy["base_backoff"]
        max_backoff = strategy["max_backoff"]
        jitter = strategy["jitter"]
        mult = 1.0
        if getattr(context, "block_type", None) == BlockType.TRANSIENT_ERROR:
            mult = strategy.get("transient_backoff_multiplier", 0.6)

        backoff = min(base * (2 ** (context.attempt - 1)), max_backoff) * mult
        rng = getattr(self, "rng", random)
        jitter_amount = backoff * jitter * rng.uniform(-1, 1)
        return max(3.0, min(max_backoff, backoff + jitter_amount))

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
        Recovery paths delegate to detect_block which prefers light signals first.
        Fully implements:
        - Error taxonomy + RecoveryAction decisions (#112)
        - Platform-aware + custom registry (#139, #151)
        - History learning for success rates (#157)
        - Transient vs real block distinction (#171)
        - Safe mode / fail-fast (#184)
        - Invokes rotation relaunch hook when needed (makes rotation actually effective)
        """
        key = (context.platform or "default").lower()

        # Circuit breaker guard (prevents hammering on hopeless cases) - skip for transient
        if self._check_circuit_breaker(key):
            self.logger.log_action(
                "circuit_breaker_blocked_recovery",
                {"platform": context.platform, "attempt": context.attempt},
            )
            return False

        block_type = await self.detect_block(context)
        context.block_type = block_type
        # Set taxonomy severity (#112)
        context.error_severity = self.block_type_to_severity.get(
            block_type, ErrorSeverity.MEDIUM
        )

        strategy = self.get_strategy(context.platform)

        self.logger.log_action(
            "block_detected",
            {
                "platform": context.platform,
                "block_type": block_type.value,
                "severity": context.error_severity.value,
                "attempt": context.attempt,
                "url": context.url,
                "http_status": context.http_status,
            },
        )

        if block_type == BlockType.NONE:
            self._reset_circuit(key)  # success path clears circuit
            return True

        if getattr(self, "metrics", None):
            self.metrics.increment("blocks_total")
            if block_type == BlockType.CAPTCHA:
                self.metrics.increment("captcha_total")

        # Decide structured action using full decision engine (all P2 features)
        action = self._decide_recovery_action(context, block_type)
        context.recovery_action = action

        self.logger.log_action(
            "recovery_action_decided",
            {
                "platform": context.platform,
                "block_type": block_type.value,
                "action": action.value,
                "attempt": context.attempt,
                "safe_mode": self.safe_mode,
                "recovery_mode": self.recovery_mode,
            },
        )

        # Record failure for circuit (but lighter / skip for transient #171)
        if block_type != BlockType.TRANSIENT_ERROR:
            cost = 1.0 + (
                0.5
                if block_type
                in (BlockType.HARD_RATE_LIMIT, BlockType.ACCOUNT_RESTRICTION)
                else 0
            )
            self._record_failure(key, cost=cost)
        else:
            self.logger.log_action(
                "transient_error_ignored_for_circuit",
                {"platform": context.platform, "attempt": context.attempt},
            )

        # #90 P1: Immediately mark compromised session for cookie cleanup on ACCOUNT_RESTRICTION.
        if (
            block_type == BlockType.ACCOUNT_RESTRICTION
            and self.session_manager
            and self.current_session_name
        ):
            try:
                cleanup_res = self.session_manager.cleanup_session(
                    self.current_session_name
                )
                self.logger.log_action(
                    "account_restriction_session_cleanup",
                    {
                        "session": self.current_session_name,
                        "result": cleanup_res.get("status")
                        if isinstance(cleanup_res, dict)
                        else str(cleanup_res),
                    },
                )
            except Exception as e:
                self.logger.log_error(
                    "account_restriction_cleanup_failed",
                    str(e),
                    {"session": self.current_session_name},
                )

        # === Rotation logic driven by decided action (respects safe_mode, platform, history) ===
        should_rotate_session = action in (
            RecoveryAction.ROTATE_SESSION_ONLY,
            RecoveryAction.ROTATE_BOTH,
        )
        should_rotate_proxy = action in (
            RecoveryAction.ROTATE_PROXY_ONLY,
            RecoveryAction.ROTATE_BOTH,
        )

        if self.safe_mode or self.recovery_mode in ("safe", "fail_fast"):
            should_rotate_session = False
            should_rotate_proxy = False

        if getattr(self, "metrics", None) and (
            should_rotate_session or should_rotate_proxy
        ):
            self.metrics.increment("rotations_total")

        if action == RecoveryAction.FAIL_FAST:
            self._update_recovery_history(context, action, success=False)
            return False

        if should_rotate_session and self.session_manager:
            try:
                self.logger.log_action(
                    "recovery_rotate_session",
                    {
                        "platform": context.platform,
                        "attempt": context.attempt,
                        "action": action.value,
                    },
                )
                # Create a fresh session
                new_session = self.session_manager.create_session(
                    session_name=f"recovery-{context.platform}-{context.attempt}-{uuid.uuid4().hex[:8]}",
                    anonymous=True,
                )
                # Store as dict for hook compatibility + name for metadata
                if isinstance(new_session, dict):
                    context.metadata["new_session"] = new_session
                    context.metadata["new_session_name"] = new_session.get("name")
                else:
                    context.metadata["new_session"] = {"name": str(new_session)}
                    context.metadata["new_session_name"] = str(new_session)
            except Exception as e:
                self.logger.log_error("session_rotation_failed", str(e))
                # If session rotation was the chosen action and failed, recovery failed
                if action in (
                    RecoveryAction.ROTATE_SESSION_ONLY,
                    RecoveryAction.ROTATE_BOTH,
                ):
                    self._update_recovery_history(context, action, success=False)
                    return False

        if should_rotate_proxy and self.proxy_manager:
            try:
                self.logger.log_action(
                    "recovery_rotate_proxy",
                    {
                        "platform": context.platform,
                        "attempt": context.attempt,
                        "action": action.value,
                    },
                )
                # Generate new sticky session (robust, #99/#10)
                if getattr(self.proxy_manager, "current_config", None):
                    cfg = self.proxy_manager.current_config
                    base_user = self._safe_extract_base_user(
                        getattr(cfg, "username", None)
                    )
                    pwd = getattr(cfg, "password", "")
                    ctry = getattr(cfg, "country", "jp")
                    new_config = self.proxy_manager.create_decodo_config(
                        user=base_user,
                        password=pwd,
                        country=ctry,
                        session_name=f"recovery-{context.attempt}-{uuid.uuid4().hex[:8]}",
                        duration_minutes=30,  # shorter duration for recovery
                    )
                    # ponytail: global mutation, add per-domain lock if orchestrator drives multiple domains concurrently
                    # Ensure manager state is updated for future use
                    self.proxy_manager.current_config = new_config
                    context.metadata["new_proxy"] = new_config.session_name
                    # Use to_safe_dict() to avoid leaking credentials into logs/history
                    context.metadata["new_proxy_config"] = new_config.to_safe_dict()
            except Exception as e:
                self.logger.log_error("proxy_rotation_failed", str(e))
                # If proxy rotation was the chosen action and failed, recovery failed
                if action in (
                    RecoveryAction.ROTATE_PROXY_ONLY,
                    RecoveryAction.ROTATE_BOTH,
                ):
                    self._update_recovery_history(context, action, success=False)
                    return False

        # Invoke wired rotation relaunch hook (from AgentBrowser) so that proxy/session rotation actually takes effect on live browser/page
        # This completes the recovery rotation loop for #38/#16 etc.
        if (
            (should_rotate_session or should_rotate_proxy)
            and hasattr(self, "_rotation_relaunch_hook")
            and callable(getattr(self, "_rotation_relaunch_hook", None))
        ):
            try:
                sess_meta = (
                    context.metadata.get("new_session")
                    if isinstance(context.metadata.get("new_session"), dict)
                    else None
                )
                prx_name = context.metadata.get("new_proxy")
                hook = self._rotation_relaunch_hook
                res = hook(sess_meta, prx_name)
                if asyncio.iscoroutine(res):
                    await res
                self.logger.log_action(
                    "rotation_relaunch_hook_called",
                    {"had_session": bool(sess_meta), "had_proxy": bool(prx_name)},
                )
            except Exception as e:
                self.logger.log_error("rotation_relaunch_hook_failed", str(e))

        # Calculate and apply backoff (uses rng + transient multiplier)
        delay = self.calculate_backoff(context)
        self.logger.log_action(
            "recovery_backoff",
            {
                "platform": context.platform,
                "delay_seconds": round(delay, 1),
                "attempt": context.attempt,
                "action": action.value,
            },
        )

        await asyncio.sleep(delay)

        return context.attempt < strategy.get("max_retries", 4)

    async def execute_with_recovery(
        self,
        func: Callable,
        platform: str,
        url: str,
        max_retries: Optional[int] = None,
        **kwargs,
    ):
        """
        Wrapper that runs a function with full recovery logic.
        Recovery paths use detect_block (light signals first, content avoided by default).
        """
        context = RecoveryContext(platform=platform, url=url)
        strategy = self.get_strategy(platform)
        max_retries = max_retries or strategy["max_retries"]
        circuit_breaker_hit = False

        for attempt in range(1, max_retries + 1):
            context.attempt = attempt
            start_time = time.time()

            key = platform.lower()
            if self._check_circuit_breaker(key):
                self.logger.log_action(
                    "circuit_breaker_blocked_execute", {"platform": platform}
                )
                circuit_breaker_hit = True
                break

            try:
                result = (
                    await func(**kwargs)
                    if asyncio.iscoroutinefunction(func)
                    else func(**kwargs)
                )
                context.response_time = time.time() - start_time

                # Check if we got a successful response
                if hasattr(result, "status"):
                    context.http_status = result.status

                block_type = await self.detect_block(context)
                if block_type == BlockType.NONE:
                    self._reset_circuit(key)
                    # Record with actual recovery action if one was taken, else NOOP
                    recorded_action = (
                        context.recovery_action
                        if context.recovery_action
                        else RecoveryAction.NOOP
                    )
                    self._update_recovery_history(
                        context, recorded_action, success=True
                    )
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

        if circuit_breaker_hit:
            raise MaxRetriesExceeded(
                f"Circuit breaker open for {platform}",
                platform=platform,
                max_retries=max_retries,
                last_error="circuit_breaker_open",
            ) from None
        raise MaxRetriesExceeded(
            f"Max retries exceeded for {platform} after {max_retries} attempts",
            platform=platform,
            max_retries=max_retries,
            last_error=context.last_error,
        ) from None


# Convenience function
def create_orchestrator(
    browser=None,
    session_manager=None,
    proxy_manager=None,
    page_getter=None,
    light_detection: bool = True,
    light_mode: Optional[bool] = None,
    rng: Optional[Any] = None,
    safe_mode: bool = False,
    recovery_mode: str = "aggressive",
):
    # Tie light_mode if present (compat for #84/#92 paths)
    if light_mode is not None:
        light_detection = bool(light_mode)
    return AntiBlockOrchestrator(
        browser,
        session_manager,
        proxy_manager,
        page_getter=page_getter,
        light_detection=light_detection,
        rng=rng,
        safe_mode=safe_mode,
        recovery_mode=recovery_mode,
    )
