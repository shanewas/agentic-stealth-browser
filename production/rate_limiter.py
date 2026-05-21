from collections import defaultdict
import logging
"""
Rate Limiting per Domain/Account
Prevents getting blocked by enforcing per-domain and per-account limits.

*** STRONG MULTI-INSTANCE ISOLATION WARNING (#87 Scalability P1) ***

In-process isolation improvements (per-AgentBrowser AccountRateLimiter + MetricsCollector,
plus namespace= support in the limiter classes) mitigate shared globals *within one process*.

CRITICAL LIMITATIONS REMAIN:
- No cross-process, cross-container, or cross-host coordination. Each Python interpreter / docker
  replica maintains fully independent rate windows and counters.
- Launching multiple replicas (for load, parallelism, or HA) multiplies your effective request rate
  against sites unless accounts, sessions, and limits are explicitly partitioned.
- Global singletons (domain_limiter, account_limiter) and direct imports continue to exist for
  backward compat and tests; they are NOT isolated.
- This is fundamentally a per-process facility. True fleet-scale rate limiting requires an
  external shared store (Redis, database, or centralized service) or account sharding.

Basic usage guidance:
- Default AgentBrowser() now gives you an isolated limiter instance (recommended).
- For explicit coordination inside one process, share the same AccountRateLimiter object or use
  namespace= when calling the low-level wait_if_needed.
- For production multi-instance deploys: one logical agent/account-group per container/process,
  or accept reduced per-replica limits + external orchestration.

Session disk isolation (via SessionManager) is orthogonal and generally safe to share across
instances as long as session names are unique.

See AgentBrowser class docs + README "Multi-Instance & Scalability (#87)" section.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from dataclasses import dataclass, field


@dataclass
class RateLimitConfig:
    """Configuration for rate limiting."""
    requests_per_minute: int = 8
    requests_per_hour: int = 40
    cooldown_seconds: int = 60
    max_retries: int = 3


class DomainRateLimiter:
    """Rate limiter per domain.
    Supports optional namespace for multi-instance / fleet isolation (#87).
    See module docstring for strong caveats on cross-process limits.
    """

    def __init__(self):
        self.configs: Dict[str, RateLimitConfig] = {}
        self.request_times: Dict[str, list] = defaultdict(list)
        self.last_request: Dict[str, datetime] = {}

    def set_limit(self, domain: str, config: RateLimitConfig, namespace: Optional[str] = None):
        """Set custom rate limit for a domain (namespaced if provided)."""
        key = self._key(domain, namespace)
        self.configs[key] = config

    def _key(self, domain: str, namespace: Optional[str] = None) -> str:
        return f"{namespace}:{domain}" if namespace else domain

    def _get_config(self, domain: str, namespace: Optional[str] = None) -> RateLimitConfig:
        """Get config for domain or return default (namespaced lookup first)."""
        key = self._key(domain, namespace)
        return self.configs.get(key, self.configs.get(domain, RateLimitConfig()))

    async def wait_if_needed(self, domain: str, namespace: Optional[str] = None) -> float:
        """Wait if rate limit would be exceeded. Returns wait time in seconds.
        Pass namespace for isolated multi-agent usage (#87 P1).
        P2 deprecation/compat fix (#104, #67, #58): timezone-aware utc datetimes.
        """

        now = datetime.now(timezone.utc)  # P2 #104/#67: timezone-aware (no naive/deprecated patterns)
        config = self._get_config(domain, namespace)
        key = self._key(domain, namespace)

        # Clean old requests
        minute_ago = now - timedelta(minutes=1)
        hour_ago = now - timedelta(hours=1)

        self.request_times[key] = [
            t for t in self.request_times[key]
            if t > minute_ago
        ]

        # Check per-minute limit
        if len(self.request_times[key]) >= config.requests_per_minute:
            wait_time = (self.request_times[key][0] + timedelta(minutes=1) - now).total_seconds()
            if wait_time > 0:
                await asyncio.sleep(wait_time)
                now = datetime.now(timezone.utc)  # P2 #104/#67: timezone-aware
                # Re-clean after sleep so the waited request is recorded without off-by-one (expired entries linger otherwise)
                # Fixes #116 while preserving exact namespace isolation and per-account logic
                minute_ago = now - timedelta(minutes=1)
                self.request_times[key] = [
                    t for t in self.request_times[key]
                    if t > minute_ago
                ]
                self.request_times[key].append(now)
                self.last_request[key] = now
                return wait_time

        # Check cooldown
        if key in self.last_request:
            time_since_last = (now - self.last_request[key]).total_seconds()
            if time_since_last < config.cooldown_seconds:
                wait_time = config.cooldown_seconds - time_since_last
                await asyncio.sleep(wait_time)
                now = datetime.now(timezone.utc)  # P2 #104/#67: timezone-aware
                # Re-clean after sleep so the waited request is recorded without off-by-one (expired entries linger otherwise)
                # Fixes #116 while preserving exact namespace isolation and per-account logic
                minute_ago = now - timedelta(minutes=1)
                self.request_times[key] = [
                    t for t in self.request_times[key]
                    if t > minute_ago
                ]
                self.request_times[key].append(now)
                self.last_request[key] = now
                return wait_time

        # Record this request (happy path, no wait)
        self.request_times[key].append(now)
        self.last_request[key] = now

        return 0.0


class AccountRateLimiter:
    """Rate limiter per account/username.
    Supports namespace isolation for scalability (#87).
    See module-level warning for important multi-instance / cross-process limitations.
    """

    def __init__(self):
        self.account_limiters: Dict[str, DomainRateLimiter] = {}

    def get_limiter(self, account: str, namespace: Optional[str] = None) -> DomainRateLimiter:
        """Get or create rate limiter for account (namespaced)."""
        ns_key = f"{namespace}:{account}" if namespace else account
        if ns_key not in self.account_limiters:
            self.account_limiters[ns_key] = DomainRateLimiter()
        return self.account_limiters[ns_key]

    async def wait_if_needed(self, account: str, domain: str, namespace: Optional[str] = None) -> float:
        """Wait if needed for this account + domain (isolated by namespace if given)."""
        limiter = self.get_limiter(account, namespace)
        return await limiter.wait_if_needed(domain, namespace=namespace)


class RateLimitExceeded(Exception):
    """Raised when a tool call exceeds the configured rate limit cap (#136)."""

    def __init__(self, tool_name: str, reason: str = ""):
        self.tool_name = tool_name
        self.reason = reason
        msg = f"Rate limit exceeded for tool '{tool_name}'"
        if reason:
            msg += f": {reason}"
        super().__init__(msg)


class ToolRateLimiter:
    """Rate limiter for MCP tool / public API surface calls (#136).

    Limits both per-tool-name calls (tool_calls_per_minute) and total session
    calls (total_calls_cap per hour).  Emits audit log warnings when limits
    are approached (at 80 % capacity).  Fully async-safe via asyncio.Lock.

    Basic usage::

        limiter = ToolRateLimiter()
        await limiter.check_and_wait("goto")      # returns 0.0 if under limits
        await limiter.check_and_wait("goto")      # may sleep or raise RateLimitExceeded
    """

    def __init__(
        self,
        tool_calls_per_minute: int = 30,
        total_calls_cap: int = 600,
    ):
        self.tool_calls_per_minute = tool_calls_per_minute
        self.total_calls_cap = total_calls_cap  # per hour

        # Per-tool sliding window (tool_name -> list[datetime])
        self._tool_calls: Dict[str, list] = defaultdict(list)
        # Total session sliding window
        self._total_calls: list = []
        # Async lock for thread-/coroutine-safety
        self._lock = asyncio.Lock()
        self._logger = logging.getLogger("production.rate_limiter.ToolRateLimiter")

    async def check_and_wait(self, tool_name: str) -> float:
        """Check rate limits for *tool_name*.  Returns wait time (0 if no wait).

        Raises ``RateLimitExceeded`` when the total session cap is exceeded.
        Emits an audit-warning log at 80 % of the per-tool and total caps.
        """
        async with self._lock:
            now = datetime.now(timezone.utc)
            minute_ago = now - timedelta(minutes=1)
            hour_ago = now - timedelta(hours=1)

            # --- total session cap ---
            self._total_calls = [t for t in self._total_calls if t > hour_ago]
            total_utilization = len(self._total_calls) / self.total_calls_cap if self.total_calls_cap else 0

            if total_utilization >= 0.8:
                self._logger.warning(
                    "Tool rate limiter: %.0f%% of total hourly cap reached (%d/%d) [tool=%s]",
                    total_utilization * 100,
                    len(self._total_calls),
                    self.total_calls_cap,
                    tool_name,
                )

            if len(self._total_calls) >= self.total_calls_cap:
                raise RateLimitExceeded(
                    tool_name,
                    reason=f"total hourly cap reached ({self.total_calls_cap})",
                )

            # --- per-tool limit ---
            self._tool_calls[tool_name] = [
                t for t in self._tool_calls[tool_name] if t > minute_ago
            ]
            tool_utilization = len(self._tool_calls[tool_name]) / self.tool_calls_per_minute if self.tool_calls_per_minute else 0

            if tool_utilization >= 0.8:
                self._logger.warning(
                    "Tool rate limiter: %.0f%% of per-minute cap for '%s' reached (%d/%d)",
                    tool_utilization * 100,
                    tool_name,
                    len(self._tool_calls[tool_name]),
                    self.tool_calls_per_minute,
                )

            wait_time = 0.0
            if len(self._tool_calls[tool_name]) >= self.tool_calls_per_minute:
                # Would exceed per-tool per-minute limit – wait until the oldest call falls off
                oldest = self._tool_calls[tool_name][0]
                wait_time = (oldest + timedelta(minutes=1) - now).total_seconds()
                if wait_time > 0:
                    # Release lock while sleeping so other coroutines aren't blocked
                    pass  # we'll sleep outside the lock
                else:
                    wait_time = 0.0

            # Record this call even if we're going to wait (the wait is
            # accounted for, and the call will proceed after waiting)
            # Actually, don't record yet – we'll record after the wait so
            # the timestamp reflects when the call actually proceeds.
            # But we must record *something* now so concurrent callers
            # also see the limit.  We'll append after the wait below.

            if wait_time > 0:
                # Must release lock before sleeping
                pass
            else:
                # No wait – record immediately under the lock
                self._tool_calls[tool_name].append(now)
                self._total_calls.append(now)

        # Sleep outside the lock so other coroutines can proceed
        if wait_time > 0:
            await asyncio.sleep(wait_time)
            async with self._lock:
                after_wait = datetime.now(timezone.utc)
                self._tool_calls[tool_name].append(after_wait)
                self._total_calls.append(after_wait)

        return wait_time


# Global instances (still work for single-process simple cases and tests)
# For multi-instance safe usage (#87) prefer per-AgentBrowser instances or explicit namespace.
# Direct use of these provides ZERO cross-process isolation or coordination.
domain_limiter = DomainRateLimiter()
account_limiter = AccountRateLimiter()
tool_rate_limiter = ToolRateLimiter()


# P1 #87 scalability: namespaced accessors (additive, non-breaking)
def wait_with_namespace(domain: str, namespace: str = None):
    return domain_limiter.wait_if_needed(domain, namespace=namespace)
