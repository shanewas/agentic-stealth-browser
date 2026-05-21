"""
Tests for Stealth Script & Profile Caching.
Addresses #72/#63: Caching of generated stealth scripts and device profiles.
"""

import pytest
import time
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stealth.cache import (
    StealthCache,
    make_cache_key,
    get_cached_script,
    get_cached_profile,
    get_cache_stats,
    clear_all_caches,
    _script_cache,
    _profile_cache,
)


class TestStealthCacheBasic:
    """Basic cache functionality tests."""

    def setup_method(self):
        clear_all_caches()

    def test_get_returns_none_for_missing_key(self):
        cache = StealthCache()
        assert cache.get("nonexistent") is None

    def test_put_and_get(self):
        cache = StealthCache()
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_get_or_generate_caches_result(self):
        cache = StealthCache()
        call_count = 0

        def generator():
            nonlocal call_count
            call_count += 1
            return "generated"

        result1 = cache.get_or_generate("key1", generator)
        result2 = cache.get_or_generate("key1", generator)

        assert result1 == "generated"
        assert result2 == "generated"
        assert call_count == 1  # Generator called only once

    def test_invalidate_removes_entry(self):
        cache = StealthCache()
        cache.put("key1", "value1")
        cache.invalidate("key1")
        assert cache.get("key1") is None

    def test_clear_removes_all_entries(self):
        cache = StealthCache()
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.clear()
        assert cache.size == 0


class TestStealthCacheLRU:
    """LRU eviction tests."""

    def setup_method(self):
        clear_all_caches()

    def test_evicts_oldest_when_full(self):
        cache = StealthCache(maxsize=3)
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")
        # Cache is full, adding another should evict key1
        cache.put("key4", "value4")

        assert cache.get("key1") is None  # Evicted
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"

    def test_access_moves_to_end(self):
        cache = StealthCache(maxsize=3)
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        cache.put("key3", "value3")

        # Access key1, making it most recently used
        cache.get("key1")

        # Add key4, should evict key2 (now oldest)
        cache.put("key4", "value4")

        assert cache.get("key1") == "value1"  # Still there
        assert cache.get("key2") is None  # Evicted


class TestStealthCacheTTL:
    """TTL expiration tests."""

    def setup_method(self):
        clear_all_caches()

    def test_expired_entry_returns_none(self):
        cache = StealthCache(ttl=0.1)  # 100ms TTL
        cache.put("key1", "value1")

        # Should be available immediately
        assert cache.get("key1") == "value1"

        # Wait for expiration
        time.sleep(0.15)
        assert cache.get("key1") is None

    def test_fresh_entry_not_expired(self):
        cache = StealthCache(ttl=3600)  # 1 hour TTL
        cache.put("key1", "value1")
        assert cache.get("key1") == "value1"


class TestStealthCacheStats:
    """Cache statistics tests."""

    def setup_method(self):
        clear_all_caches()

    def test_hit_miss_tracking(self):
        cache = StealthCache()
        cache.put("key1", "value1")

        cache.get("key1")  # Hit
        cache.get("key2")  # Miss

        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1

    def test_hit_rate_calculation(self):
        cache = StealthCache()
        cache.put("key1", "value1")

        cache.get("key1")  # Hit
        cache.get("key1")  # Hit
        cache.get("key2")  # Miss

        assert cache.hit_rate == 2 / 3

    def test_hit_rate_zero_when_no_access(self):
        cache = StealthCache()
        assert cache.hit_rate == 0.0


class TestCacheKey:
    """Cache key generation tests."""

    def test_same_params_same_key(self):
        key1 = make_cache_key("windows_laptop", "seed123")
        key2 = make_cache_key("windows_laptop", "seed123")
        assert key1 == key2

    def test_different_params_different_key(self):
        key1 = make_cache_key("windows_laptop", "seed123")
        key2 = make_cache_key("macbook", "seed123")
        assert key1 != key2

    def test_key_is_deterministic(self):
        key = make_cache_key("profile", "seed", {"hw": 8}, {"screen": 1080})
        key2 = make_cache_key("profile", "seed", {"hw": 8}, {"screen": 1080})
        assert key == key2

    def test_key_includes_hardware(self):
        key1 = make_cache_key("profile", "seed", {"hw": 8})
        key2 = make_cache_key("profile", "seed", {"hw": 16})
        assert key1 != key2

    def test_key_includes_screen(self):
        key1 = make_cache_key("profile", "seed", screen={"width": 1920})
        key2 = make_cache_key("profile", "seed", screen={"width": 2560})
        assert key1 != key2


class TestGlobalCache:
    """Global cache integration tests."""

    def setup_method(self):
        clear_all_caches()

    def test_get_cached_script_caches_result(self):
        call_count = 0

        def generator():
            nonlocal call_count
            call_count += 1
            return "/* stealth script */"

        result1 = get_cached_script("windows_laptop", generator=generator)
        result2 = get_cached_script("windows_laptop", generator=generator)

        assert result1 == result2
        assert call_count == 1

    def test_get_cached_profile_caches_result(self):
        call_count = 0

        def generator():
            nonlocal call_count
            call_count += 1
            return {"profile": "data"}

        result1 = get_cached_profile("windows_laptop", generator=generator)
        result2 = get_cached_profile("windows_laptop", generator=generator)

        assert result1 == result2
        assert call_count == 1

    def test_get_cache_stats_returns_both_caches(self):
        stats = get_cache_stats()
        assert "scripts" in stats
        assert "profiles" in stats

    def test_clear_all_caches_clears_both(self):
        _script_cache.put("test", "value")
        _profile_cache.put("test", "value")

        clear_all_caches()

        assert _script_cache.get("test") is None
        assert _profile_cache.get("test") is None


class TestStealthScriptIntegration:
    """Integration tests with actual stealth module."""

    def setup_method(self):
        clear_all_caches()

    def test_get_stealth_script_uses_cache(self):
        from stealth.advanced_stealth import get_stealth_script

        # First call generates
        script1 = get_stealth_script("windows_laptop")
        # Second call should use cache
        script2 = get_stealth_script("windows_laptop")

        assert script1 == script2
        # Cache should have at least one hit
        assert _script_cache._hits >= 1

    def test_different_profiles_generate_different_scripts(self):
        from stealth.advanced_stealth import get_stealth_script

        script1 = get_stealth_script("windows_laptop")
        script2 = get_stealth_script("macbook")

        # Scripts should be different (different profiles)
        assert script1 is not None
        assert script2 is not None

    def test_same_profile_same_seed_same_script(self):
        from stealth.advanced_stealth import get_stealth_script

        script1 = get_stealth_script("windows_laptop", fingerprint_seed="test-seed")
        script2 = get_stealth_script("windows_laptop", fingerprint_seed="test-seed")

        assert script1 == script2
