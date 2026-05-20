"""
Rate Limiting per Domain/Account
Prevents getting blocked by enforcing per-domain and per-account limits.
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
    """Rate limiter per domain."""

    def __init__(self):
        self.configs: Dict[str, RateLimitConfig] = {}
        self.request_times: Dict[str, list] = defaultdict(list)
        self.last_request: Dict[str, datetime] = {}

    def set_limit(self, domain: str, config: RateLimitConfig):
        """Set custom rate limit for a domain."""
        self.configs[domain] = config

    def _get_config(self, domain: str) -> RateLimitConfig:
        """Get config for domain or return default."""
        return self.configs.get(domain, RateLimitConfig())

    async def wait_if_needed(self, domain: str) -> float:
        """Wait if rate limit would be exceeded. Returns wait time in seconds."""
        now = datetime.now()
        config = self._get_config(domain)

        # Clean old requests
        minute_ago = now - timedelta(minutes=1)
        hour_ago = now - timedelta(hours=1)

        self.request_times[domain] = [
            t for t in self.request_times[domain]
            if t > minute_ago
        ]

        # Check per-minute limit
        if len(self.request_times[domain]) >= config.requests_per_minute:
            wait_time = (self.request_times[domain][0] + timedelta(minutes=1) - now).total_seconds()
            if wait_time > 0:
                await asyncio.sleep(wait_time)
                return wait_time

        # Check cooldown
        if domain in self.last_request:
            time_since_last = (now - self.last_request[domain]).total_seconds()
            if time_since_last < config.cooldown_seconds:
                wait_time = config.cooldown_seconds - time_since_last
                await asyncio.sleep(wait_time)
                return wait_time

        # Record this request
        self.request_times[domain].append(now)
        self.last_request[domain] = now

        return 0.0


class AccountRateLimiter:
    """Rate limiter per account/username."""

    def __init__(self):
        self.account_limits: Dict[str, DomainRateLimiter] = {}

    def get_limiter(self, account: str) -> DomainRateLimiter:
        """Get or create rate limiter for account."""
        if account not in self.account_limits:
            self.account_limits[account] = DomainRateLimiter()
        return self.account_limits[account]

    async def wait_if_needed(self, account: str, domain: str) -> float:
        """Wait if needed for this account + domain combination."""
        limiter = self.get_limiter(account)
        return await limiter.wait_if_needed(domain)


# Global instances
domain_limiter = DomainRateLimiter()
account_limiter = AccountRateLimiter()
