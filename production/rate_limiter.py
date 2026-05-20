from collections import defaultdict
"""
Rate Limiting per Domain/Account
Prevents getting blocked by enforcing per-domain and per-account limits.

Phase 8 P1 #87 (scalability): added optional namespace / fleet isolation support.
Multiple AgentBrowser instances (or logical agents) can now safely share the
module without cross-contamination of rate state when a namespace is provided.
"""

import asyncio
from datetime import datetime, timedelta
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
        """
        now = datetime.now()
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
                now = datetime.now()
                self.request_times[key].append(now)
                self.last_request[key] = now
                return wait_time

        # Check cooldown
        if key in self.last_request:
            time_since_last = (now - self.last_request[key]).total_seconds()
            if time_since_last < config.cooldown_seconds:
                wait_time = config.cooldown_seconds - time_since_last
                await asyncio.sleep(wait_time)
                now = datetime.now()
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


# Global instances (still work for single-process simple cases)
# For multi-instance safe usage (#87) pass namespace= to wait_if_needed calls.
domain_limiter = DomainRateLimiter()
account_limiter = AccountRateLimiter()


def get_isolated_rate_limiters(namespace: str) -> tuple[DomainRateLimiter, AccountRateLimiter]:
    """Factory for completely isolated limiter pair for a logical agent/fleet member.
    Recommended for #87 scalability when running multiple AgentBrowsers in one process.
    """
    # Each call returns fresh pair (no sharing even with same ns unless you cache)
    # For shared-within-namespace use the global + namespace arg (lighter).
    return DomainRateLimiter(), AccountRateLimiter()
