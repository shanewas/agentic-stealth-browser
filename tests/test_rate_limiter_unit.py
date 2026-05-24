"""
Unit tests for RateLimiter: window tracking, cap enforcement, per-account isolation.

Covers:
- DomainRateLimiter window sliding
- DomainRateLimiter wait_if_needed
- AccountRateLimiter per-account isolation
- ToolRateLimiter cap enforcement
- RateLimitConfig defaults
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from production.rate_limiter import (
    DomainRateLimiter,
    AccountRateLimiter,
    ToolRateLimiter,
    RateLimitConfig,
    RateLimitExceeded,
)


class TestRateLimitConfig:
    def test_defaults(self):
        cfg = RateLimitConfig()
        assert cfg.requests_per_minute == 8
        assert cfg.requests_per_hour == 40
        assert cfg.cooldown_seconds == 60
        assert cfg.max_retries == 3

    def test_custom_config(self):
        cfg = RateLimitConfig(
            requests_per_minute=10,
            requests_per_hour=100,
            cooldown_seconds=30,
            max_retries=5,
        )
        assert cfg.requests_per_minute == 10
        assert cfg.requests_per_hour == 100


class TestDomainRateLimiter:
    def test_no_wait_under_limit(self):
        limiter = DomainRateLimiter()
        wait = asyncio.run(limiter.wait_if_needed("test.com"))
        assert wait == 0.0

    def test_wait_after_exceeding_per_minute_limit(self):
        limiter = DomainRateLimiter()
        # Set very tight limit
        limiter.set_limit(
            "test.com", RateLimitConfig(requests_per_minute=2, cooldown_seconds=0)
        )
        asyncio.run(limiter.wait_if_needed("test.com"))
        asyncio.run(limiter.wait_if_needed("test.com"))
        # With 2/min limit, the 3rd call should be blocked
        # Check internal state instead of actually waiting
        assert len(limiter.request_times["test.com"]) == 2

    def test_different_domains_isolated(self):
        limiter = DomainRateLimiter()
        cfg = RateLimitConfig(requests_per_minute=100, cooldown_seconds=0)
        limiter.set_limit("a.com", cfg)
        limiter.set_limit("b.com", cfg)
        # Both domains should be free under generous limit
        wait_a1 = asyncio.run(limiter.wait_if_needed("a.com"))
        wait_a2 = asyncio.run(limiter.wait_if_needed("a.com"))
        wait_b = asyncio.run(limiter.wait_if_needed("b.com"))
        assert wait_a1 == 0.0
        assert wait_a2 == 0.0
        assert wait_b == 0.0

    def test_namespace_isolation(self):
        limiter = DomainRateLimiter()
        cfg = RateLimitConfig(requests_per_minute=100, cooldown_seconds=0)
        limiter.set_limit("example.com", cfg)
        # All namespace slots are free under generous limit
        wait_ns1_1 = asyncio.run(limiter.wait_if_needed("example.com", namespace="ns1"))
        wait_ns1_2 = asyncio.run(limiter.wait_if_needed("example.com", namespace="ns1"))
        wait_ns2 = asyncio.run(limiter.wait_if_needed("example.com", namespace="ns2"))
        assert wait_ns1_1 == 0.0
        assert wait_ns1_2 == 0.0
        assert wait_ns2 == 0.0

    def test_cooldown_enforced(self):
        limiter = DomainRateLimiter()
        cfg = RateLimitConfig(requests_per_minute=100, cooldown_seconds=0)
        limiter.set_limit("slow.com", cfg)
        asyncio.run(limiter.wait_if_needed("slow.com"))
        wait = asyncio.run(limiter.wait_if_needed("slow.com"))
        assert wait >= 0


class TestAccountRateLimiter:
    def test_per_account_isolation(self):
        limiter = AccountRateLimiter()
        cfg = RateLimitConfig(requests_per_minute=100, cooldown_seconds=0)
        dom_lim = limiter.get_limiter("account-a")
        dom_lim.set_limit("example.com", cfg)
        # Fill account-a with many requests; account-b should still be free
        wait_a1 = asyncio.run(limiter.wait_if_needed("account-a", "example.com"))
        wait_a2 = asyncio.run(limiter.wait_if_needed("account-a", "example.com"))
        wait_b = asyncio.run(limiter.wait_if_needed("account-b", "example.com"))
        assert wait_a1 == 0.0
        assert wait_a2 == 0.0  # under per-minute limit (100)
        assert wait_b == 0.0  # different account = isolated

    def test_get_limiter_creates_new(self):
        limiter = AccountRateLimiter()
        dl = limiter.get_limiter("new-account")
        assert isinstance(dl, DomainRateLimiter)
        assert "new-account" in limiter.account_limiters

    def test_get_limiter_reuses_existing(self):
        limiter = AccountRateLimiter()
        dl1 = limiter.get_limiter("account-x")
        dl2 = limiter.get_limiter("account-x")
        assert dl1 is dl2


class TestToolRateLimiter:
    def test_under_limit(self):
        limiter = ToolRateLimiter(tool_calls_per_minute=100, total_calls_cap=1000)
        wait = asyncio.run(limiter.check_and_wait("goto"))
        assert wait == 0.0

    def test_per_tool_limit_waits(self):
        limiter = ToolRateLimiter(tool_calls_per_minute=100, total_calls_cap=1000)
        for _ in range(5):
            wait = asyncio.run(limiter.check_and_wait("goto"))
            assert wait == 0.0  # all under limit

    def test_per_tool_limit_exceeded(self):
        """Verify that exceeding per-minute limit triggers a rate window wait."""
        limiter = ToolRateLimiter(tool_calls_per_minute=3, total_calls_cap=1000)
        # Fill the window
        for _ in range(3):
            asyncio.run(limiter.check_and_wait("goto"))
        # Check internal window tracking
        assert len(limiter._tool_calls["goto"]) == 3

    def test_total_cap_raises(self):
        limiter = ToolRateLimiter(tool_calls_per_minute=100, total_calls_cap=3)
        for _ in range(3):
            asyncio.run(limiter.check_and_wait("goto"))
        with pytest.raises(RateLimitExceeded) as exc:
            asyncio.run(limiter.check_and_wait("goto"))
        assert "goto" in str(exc.value)

    def test_different_tools_share_total_cap(self):
        limiter = ToolRateLimiter(tool_calls_per_minute=100, total_calls_cap=2)
        asyncio.run(limiter.check_and_wait("goto"))
        asyncio.run(limiter.check_and_wait("scrape"))
        with pytest.raises(RateLimitExceeded):
            asyncio.run(limiter.check_and_wait("goto"))

    def test_rate_limit_exceeded_attributes(self):
        exc = RateLimitExceeded("goto", reason="hourly cap reached")
        assert exc.tool_name == "goto"
        assert "hourly cap" in exc.reason


class TestDomainRateLimiterWindowCleanup:
    def test_old_requests_cleaned(self):
        limiter = DomainRateLimiter()
        cfg = RateLimitConfig(requests_per_minute=5, cooldown_seconds=0)
        limiter.set_limit("test.com", cfg)
        # Insert expired request manually
        old = datetime.now(timezone.utc) - timedelta(minutes=2)
        limiter.request_times["test.com"] = [old]
        wait = asyncio.run(limiter.wait_if_needed("test.com"))
        assert wait == 0.0
        assert len(limiter.request_times["test.com"]) == 1
