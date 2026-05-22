"""
Tests for Connection Pool.
Addresses #135: Connection/context reuse between sequential navigations.
"""

import pytest
import time
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.connection_pool import ConnectionPool


class TestConnectionPoolBasic:
    """Basic connection pool tests."""

    def test_get_domain_extracts_correctly(self):
        pool = ConnectionPool()
        assert pool.get_domain("https://example.com/page") == "example.com"
        assert pool.get_domain("http://example.com:8080/path") == "example.com:8080"
        assert pool.get_domain("https://sub.example.com") == "sub.example.com"

    def test_get_or_create_context_creates_new(self):
        pool = ConnectionPool()
        ctx = pool.get_or_create_context("example.com")
        assert ctx["domain"] == "example.com"
        assert ctx["reuse_count"] == 0
        assert ctx["navigation_count"] == 0

    def test_get_or_create_context_reuses_existing(self):
        pool = ConnectionPool()
        ctx1 = pool.get_or_create_context("example.com")
        ctx2 = pool.get_or_create_context("example.com")
        assert ctx1 is ctx2  # Same object
        assert ctx2["reuse_count"] == 1

    def test_release_context_updates_timestamp(self):
        pool = ConnectionPool()
        ctx = pool.get_or_create_context("example.com")
        old_time = ctx["last_used"]
        time.sleep(0.01)
        pool.release_context("example.com")
        assert ctx["last_used"] > old_time


class TestConnectionPoolEviction:
    """LRU eviction tests."""

    def test_evicts_oldest_when_full(self):
        pool = ConnectionPool(max_contexts=3)
        pool.get_or_create_context("a.com")
        pool.get_or_create_context("b.com")
        pool.get_or_create_context("c.com")
        # Cache is full, adding another should evict a.com
        pool.get_or_create_context("d.com")

        assert "a.com" not in pool._contexts
        # codeql[py/incomplete-url-substring-sanitization]: test fixture domain key, not URL substring sanitization
        assert "d.com" in pool._contexts

    def test_access_moves_to_end(self):
        pool = ConnectionPool(max_contexts=3)
        pool.get_or_create_context("a.com")
        pool.get_or_create_context("b.com")
        pool.get_or_create_context("c.com")

        # Access a.com, making it most recently used
        pool.get_or_create_context("a.com")

        # Add d.com, should evict b.com (now oldest)
        pool.get_or_create_context("d.com")

        assert "a.com" in pool._contexts
        # codeql[py/incomplete-url-substring-sanitization]: test fixture domain key, not URL substring sanitization
        assert "b.com" not in pool._contexts


class TestConnectionPoolTTL:
    """TTL expiration tests."""

    def test_cleanup_expired_removes_old_contexts(self):
        pool = ConnectionPool(ttl=0.1)  # 100ms TTL
        pool.get_or_create_context("example.com")

        # Should not be expired yet
        assert len(pool.cleanup_expired()) == 0

        # Wait for expiration
        time.sleep(0.15)
        expired = pool.cleanup_expired()
        # codeql[py/incomplete-url-substring-sanitization]: test fixture domain key, not URL substring sanitization
        assert "example.com" in expired
        assert len(pool._contexts) == 0


class TestConnectionPoolStats:
    """Statistics tests."""

    def test_stats_initial_state(self):
        pool = ConnectionPool()
        stats = pool.get_stats()
        assert stats["active_contexts"] == 0
        assert stats["total_reuses"] == 0
        assert stats["reuse_rate"] == 0.0

    def test_stats_after_reuse(self):
        pool = ConnectionPool()
        pool.get_or_create_context("example.com")
        pool.get_or_create_context("example.com")  # Reuse
        pool.get_or_create_context("example.com")  # Reuse again

        stats = pool.get_stats()
        assert stats["active_contexts"] == 1
        assert stats["total_reuses"] == 2

    def test_record_navigation_increases_count(self):
        pool = ConnectionPool()
        pool.get_or_create_context("example.com")
        pool.record_navigation("https://example.com/page1")
        pool.record_navigation("https://example.com/page2")

        ctx = pool._contexts["example.com"]
        assert ctx["navigation_count"] == 2


class TestConnectionPoolShouldReuse:
    """Reuse decision tests."""

    def test_should_reuse_returns_true_for_existing(self):
        pool = ConnectionPool()
        pool.get_or_create_context("example.com")
        assert pool.should_reuse("https://example.com/page") is True

    def test_should_reuse_returns_false_for_new(self):
        pool = ConnectionPool()
        assert pool.should_reuse("https://newsite.com/page") is False

    def test_should_reuse_case_insensitive(self):
        pool = ConnectionPool()
        pool.get_or_create_context("Example.COM")
        assert pool.should_reuse("https://example.com/page") is True


class TestConnectionPoolClear:
    """Clear tests."""

    def test_clear_removes_all_contexts(self):
        pool = ConnectionPool()
        pool.get_or_create_context("a.com")
        pool.get_or_create_context("b.com")
        pool.clear()
        assert len(pool._contexts) == 0
        assert len(pool._domain_history) == 0
