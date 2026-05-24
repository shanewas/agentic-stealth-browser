"""
Connection & Context Reuse for Sequential Navigations
Addresses #135: No connection or context reuse between sequential navigations on the same domain.

Keeps contexts warm and reuses them intelligently when the domain matches recent activity.
Reduces TLS setup cost and fingerprinting signals from new connections.
"""

import time
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse
from collections import OrderedDict


class ConnectionPool:
    """Manages reusable browser contexts for same-domain sequential navigations.

    Usage:
        pool = ConnectionPool(max_contexts=5, ttl=300)
        context = pool.get_or_create_context("example.com")
        # ... use context ...
        pool.release_context("example.com", context)
    """

    def __init__(self, max_contexts: int = 5, ttl: float = 300.0):
        self.max_contexts = max_contexts
        self.ttl = ttl  # Time-to-live for idle contexts (seconds)
        self._contexts: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._domain_history: List[str] = []

    def get_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            return urlparse(url).netloc.lower()
        except Exception:
            return url.lower()

    def get_or_create_context(self, domain: str) -> Dict[str, Any]:
        """Get existing context for domain or create new one.

        Returns context info dict with 'created_at' and 'last_used' timestamps.
        """
        domain = domain.lower()

        if domain in self._contexts:
            ctx = self._contexts[domain]
            ctx["last_used"] = time.time()
            ctx["reuse_count"] = ctx.get("reuse_count", 0) + 1
            # Move to end (most recently used)
            self._contexts.move_to_end(domain)
            return ctx

        # Create new context
        ctx = {
            "domain": domain,
            "created_at": time.time(),
            "last_used": time.time(),
            "reuse_count": 0,
            "navigation_count": 0,
        }
        self._contexts[domain] = ctx
        self._domain_history.append(domain)

        # Evict oldest if over capacity
        while len(self._contexts) > self.max_contexts:
            oldest_domain, oldest_ctx = self._contexts.popitem(last=False)
            # Could close browser context here if we had a reference

        return ctx

    def release_context(self, domain: str, context: Optional[Dict] = None):
        """Release context back to pool (updates last_used)."""
        domain = domain.lower()
        if domain in self._contexts:
            self._contexts[domain]["last_used"] = time.time()
            self._contexts.move_to_end(domain)

    def cleanup_expired(self) -> List[str]:
        """Remove expired contexts. Returns list of removed domains."""
        now = time.time()
        expired = []
        for domain, ctx in list(self._contexts.items()):
            if now - ctx["last_used"] > self.ttl:
                expired.append(domain)
                del self._contexts[domain]
        return expired

    def get_stats(self) -> Dict[str, Any]:
        """Get pool statistics."""
        total_reuses = sum(ctx.get("reuse_count", 0) for ctx in self._contexts.values())
        total_navigations = sum(
            ctx.get("navigation_count", 0) for ctx in self._contexts.values()
        )
        return {
            "active_contexts": len(self._contexts),
            "max_contexts": self.max_contexts,
            "total_reuses": total_reuses,
            "total_navigations": total_navigations,
            "reuse_rate": total_reuses / max(1, total_navigations + total_reuses),
            "domains": list(self._contexts.keys()),
        }

    def clear(self):
        """Clear all contexts."""
        self._contexts.clear()
        self._domain_history.clear()

    def should_reuse(self, url: str) -> bool:
        """Check if we should reuse an existing context for this URL."""
        domain = self.get_domain(url)
        return domain in self._contexts

    def record_navigation(self, url: str):
        """Record a navigation for tracking."""
        domain = self.get_domain(url)
        if domain in self._contexts:
            self._contexts[domain]["navigation_count"] = (
                self._contexts[domain].get("navigation_count", 0) + 1
            )
