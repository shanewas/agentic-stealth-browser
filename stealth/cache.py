"""
Stealth Script & Profile Caching
Addresses #72/#63: Cache generated stealth scripts and device profiles.

Provides LRU caching for stealth scripts keyed by profile configuration,
with invalidation when parameters change.
"""

import hashlib
import json
import time
import threading
from typing import Optional, Dict, Any, Tuple
from collections import OrderedDict


class StealthCache:
    """Thread-safe LRU cache for stealth scripts and profiles.

    Usage:
        cache = StealthCache(maxsize=16, ttl=3600)
        script = cache.get_or_generate(
            key=("windows_laptop", "seed123"),
            generator=lambda: generate_expensive_script(...),
        )
    """

    def __init__(self, maxsize: int = 16, ttl: float = 3600.0):
        self.maxsize = maxsize
        self.ttl = ttl  # Time-to-live in seconds
        self._cache: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: str) -> Optional[Any]:
        """Get cached value if exists and not expired."""
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None

            value, timestamp = self._cache[key]
            if time.time() - timestamp > self.ttl:
                # Expired
                del self._cache[key]
                self._misses += 1
                return None

            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._hits += 1
            return value

    def put(self, key: str, value: Any):
        """Cache a value."""
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
            self._cache[key] = (value, time.time())

            # Evict oldest if over capacity
            while len(self._cache) > self.maxsize:
                self._cache.popitem(last=False)

    def get_or_generate(self, key: str, generator) -> Any:
        """Get cached value or generate and cache new one."""
        value = self.get(key)
        if value is not None:
            return value

        value = generator()
        self.put(key, value)
        return value

    def invalidate(self, key: str):
        """Remove a specific entry."""
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        """Clear all cached entries."""
        with self._lock:
            self._cache.clear()

    @property
    def size(self) -> int:
        return len(self._cache)

    @property
    def hit_rate(self) -> float:
        total = self._hits + self._misses
        if total == 0:
            return 0.0
        return self._hits / total

    def get_stats(self) -> Dict[str, Any]:
        return {
            "size": self.size,
            "maxsize": self.maxsize,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": self.hit_rate,
            "ttl": self.ttl,
        }


def make_cache_key(
    profile: str,
    fingerprint_seed: Optional[str] = None,
    hardware: Optional[Dict] = None,
    screen: Optional[Dict] = None,
) -> str:
    """Create a deterministic cache key from parameters."""
    parts = [profile, fingerprint_seed or ""]
    if hardware:
        parts.append(json.dumps(hardware, sort_keys=True))
    if screen:
        parts.append(json.dumps(screen, sort_keys=True))
    key_str = "|".join(parts)
    return hashlib.sha256(key_str.encode()).hexdigest()[:16]


# Global cache instance (shared across imports)
_script_cache = StealthCache(maxsize=32, ttl=7200.0)  # 2 hour TTL
_profile_cache = StealthCache(maxsize=64, ttl=86400.0)  # 24 hour TTL


def get_cached_script(
    profile: str,
    fingerprint_seed: Optional[str] = None,
    hardware: Optional[Dict] = None,
    screen: Optional[Dict] = None,
    generator=None,
) -> str:
    """Get stealth script from cache or generate and cache it.

    Args:
        profile: Stealth profile name
        fingerprint_seed: Per-session seed for canvas/WebGL noise
        hardware: Hardware fingerprint dict
        screen: Screen profile dict
        generator: Function to generate script if not cached

    Returns:
        Cached or newly generated stealth script
    """
    key = make_cache_key(profile, fingerprint_seed, hardware, screen)
    return _script_cache.get_or_generate(key, generator)


def get_cached_profile(profile_name: str, generator=None) -> Any:
    """Get device profile from cache or generate and cache it."""
    return _profile_cache.get_or_generate(profile_name, generator)


def get_cache_stats() -> Dict[str, Dict[str, Any]]:
    """Get stats for all caches."""
    return {
        "scripts": _script_cache.get_stats(),
        "profiles": _profile_cache.get_stats(),
    }


def clear_all_caches():
    """Clear all caches (useful for testing)."""
    _script_cache.clear()
    _profile_cache.clear()
