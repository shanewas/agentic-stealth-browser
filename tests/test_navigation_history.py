"""
Tests for Navigation History.
Tracks domain navigation history for telemetry and reuse-pattern analysis.
"""

import time
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.connection_pool import NavigationHistory


class TestNavigationHistoryBasic:
    """Basic navigation history tests."""

    def test_get_domain_extracts_correctly(self):
        history = NavigationHistory()
        assert history.get_domain("https://example.com/page") == "example.com"
        assert history.get_domain("http://example.com:8080/path") == "example.com:8080"
        assert history.get_domain("https://sub.example.com") == "sub.example.com"

    def test_record_domain_creates_new(self):
        history = NavigationHistory()
        entry = history.record_domain("example.com")
        assert entry["domain"] == "example.com"
        assert entry["reuse_count"] == 0
        assert entry["navigation_count"] == 0

    def test_record_domain_reuses_existing(self):
        history = NavigationHistory()
        entry1 = history.record_domain("example.com")
        entry2 = history.record_domain("example.com")
        assert entry1 is entry2  # Same object
        assert entry2["reuse_count"] == 1

    def test_touch_domain_updates_timestamp(self):
        history = NavigationHistory()
        entry = history.record_domain("example.com")
        old_time = entry["last_used"]
        time.sleep(0.01)
        history.touch_domain("example.com")
        assert entry["last_used"] > old_time


class TestNavigationHistoryEviction:
    """LRU eviction tests."""

    def test_evicts_oldest_when_full(self):
        history = NavigationHistory(max_contexts=3)
        history.record_domain("a.com")
        history.record_domain("b.com")
        history.record_domain("c.com")
        history.record_domain("d.com")

        assert "a.com" not in history._domains
        # codeql[py/incomplete-url-substring-sanitization]: test fixture domain key, not URL substring sanitization
        assert "d.com" in history._domains

    def test_access_moves_to_end(self):
        history = NavigationHistory(max_contexts=3)
        history.record_domain("a.com")
        history.record_domain("b.com")
        history.record_domain("c.com")

        history.record_domain("a.com")

        history.record_domain("d.com")

        assert "a.com" in history._domains
        # codeql[py/incomplete-url-substring-sanitization]: test fixture domain key, not URL substring sanitization
        assert "b.com" not in history._domains


class TestNavigationHistoryTTL:
    """TTL stale record tests."""

    def test_cleanup_stale_removes_old_records(self):
        history = NavigationHistory(ttl=0.1)  # 100ms TTL
        history.record_domain("example.com")

        assert len(history.cleanup_stale()) == 0

        time.sleep(0.15)
        stale = history.cleanup_stale()
        # codeql[py/incomplete-url-substring-sanitization]: test fixture domain key, not URL substring sanitization
        assert "example.com" in stale
        assert len(history._domains) == 0


class TestNavigationHistoryStats:
    """Statistics tests."""

    def test_stats_initial_state(self):
        history = NavigationHistory()
        stats = history.get_stats()
        assert stats["active_contexts"] == 0
        assert stats["total_reuses"] == 0
        assert stats["reuse_rate"] == 0.0

    def test_stats_after_reuse(self):
        history = NavigationHistory()
        history.record_domain("example.com")
        history.record_domain("example.com")  # Revisit
        history.record_domain("example.com")  # Revisit again

        stats = history.get_stats()
        assert stats["active_contexts"] == 1
        assert stats["total_reuses"] == 2

    def test_record_navigation_increases_count(self):
        history = NavigationHistory()
        history.record_domain("example.com")
        history.record_navigation("https://example.com/page1")
        history.record_navigation("https://example.com/page2")

        entry = history._domains["example.com"]
        assert entry["navigation_count"] == 2


class TestNavigationHistoryShouldReuse:
    """Visit recency tests."""

    def test_should_reuse_returns_true_for_existing(self):
        history = NavigationHistory()
        history.record_domain("example.com")
        assert history.should_reuse("https://example.com/page") is True

    def test_should_reuse_returns_false_for_new(self):
        history = NavigationHistory()
        assert history.should_reuse("https://newsite.com/page") is False

    def test_should_reuse_case_insensitive(self):
        history = NavigationHistory()
        history.record_domain("Example.COM")
        assert history.should_reuse("https://example.com/page") is True


class TestNavigationHistoryClear:
    """Clear tests."""

    def test_clear_removes_all_records(self):
        history = NavigationHistory()
        history.record_domain("a.com")
        history.record_domain("b.com")
        history.clear()
        assert len(history._domains) == 0
        assert len(history._domain_history) == 0
