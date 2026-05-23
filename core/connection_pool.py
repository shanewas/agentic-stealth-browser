"""
Domain Navigation History Tracker (Telemetry)

Tracks domain navigation history for telemetry and reuse-pattern analysis.
Provides lightweight records of visited domains with timestamps for
understanding browsing patterns across sessions.
"""

import time
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse
from collections import OrderedDict


class NavigationHistory:
    """Tracks domain navigation history with timestamps for telemetry purposes.

    Usage:
        history = NavigationHistory(max_contexts=5, ttl=300)
        entry = history.record_domain("example.com")
        # ... later ...
        history.touch_domain("example.com")
    """

    def __init__(self, max_contexts: int = 5, ttl: float = 300.0):
        self.max_contexts = max_contexts
        self.ttl = ttl  # Time-to-live for stale records (seconds)
        self._domains: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._domain_history: List[str] = []

    def get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return url.lower()

    def record_domain(self, domain: str) -> Dict[str, Any]:
        """Record a domain visit in navigation history.

        Returns history entry dict with 'created_at' and 'last_used' timestamps.
        """
        domain = domain.lower()

        if domain in self._domains:
            ctx = self._domains[domain]
            ctx["last_used"] = time.time()
            ctx["reuse_count"] = ctx.get("reuse_count", 0) + 1
            self._domains.move_to_end(domain)
            return ctx

        ctx = {
            "domain": domain,
            "created_at": time.time(),
            "last_used": time.time(),
            "reuse_count": 0,
            "navigation_count": 0,
        }
        self._domains[domain] = ctx
        self._domain_history.append(domain)

        while len(self._domains) > self.max_contexts:
            oldest_domain, oldest_ctx = self._domains.popitem(last=False)

        return ctx

    def touch_domain(self, domain: str, context: Optional[Dict] = None):
        """Update last_used timestamp on a domain entry."""
        domain = domain.lower()
        if domain in self._domains:
            self._domains[domain]["last_used"] = time.time()
            self._domains.move_to_end(domain)

    def cleanup_stale(self) -> List[str]:
        """Remove stale domain records. Returns list of removed domains."""
        now = time.time()
        stale = []
        for domain, ctx in list(self._domains.items()):
            if now - ctx["last_used"] > self.ttl:
                stale.append(domain)
                del self._domains[domain]
        return stale

    def get_stats(self) -> Dict[str, Any]:
        """Get navigation history statistics."""
        total_reuses = sum(ctx.get("reuse_count", 0) for ctx in self._domains.values())
        total_navigations = sum(ctx.get("navigation_count", 0) for ctx in self._domains.values())
        return {
            "active_contexts": len(self._domains),
            "max_contexts": self.max_contexts,
            "total_reuses": total_reuses,
            "total_navigations": total_navigations,
            "reuse_rate": total_reuses / max(1, total_navigations + total_reuses),
            "domains": list(self._domains.keys()),
        }

    def clear(self):
        """Clear all history records."""
        self._domains.clear()
        self._domain_history.clear()

    def should_reuse(self, url: str) -> bool:
        """Check if domain has been visited recently."""
        domain = self.get_domain(url)
        return domain in self._domains

    def record_navigation(self, url: str):
        """Record a navigation for tracking."""
        domain = self.get_domain(url)
        if domain in self._domains:
            self._domains[domain]["navigation_count"] = self._domains[domain].get("navigation_count", 0) + 1
