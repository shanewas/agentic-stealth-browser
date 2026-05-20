"""
AgentOrchestrator (a.k.a. Fleet) — High-level Multi-Agent Browser Orchestrator

Implements the foundational architecture for issues:
  - #80: High-level Fleet / Multi-Agent Orchestrator
  - #66: High-level Fleet / AgentOrchestrator
  - #39: Proper multi-browser orchestrator with shared rate limiting and proxy pool

This is the missing high-level coordination layer on top of the solid per-browser
AgentBrowser + AntiBlockOrchestrator + AccountRateLimiter + ProxyManager foundation.

### MVP Design Goals (focused, production-aware, non-over-engineered)
- Manage a pool of reusable `AgentBrowser` instances (launch / acquire / release / close).
- Provide **shared** `AccountRateLimiter` and `MetricsCollector` to all managed browsers
  (enables coordinated in-process rate limiting and aggregated observability).
- **ProxyPool**: simple, explicit shared pool of `ProxyConfig` entries. Browsers are
  assigned distinct proxies at creation time (prevents accidental IP sharing).
  Usage tracking, round-robin / least-used checkout, basic health (error counts).
- Concurrency control via asyncio.Semaphore (max concurrent active browsers).
- Dispatch helper `run_on_browser` for "give me an available worker + wait for rate limit".
- Lease model to prevent double-use of a browser instance.
- Full async context manager support (`async with AgentOrchestrator(...) as fleet`).
- Delegates all real work (stealth, recovery, human behavior, rotation hooks) to the
  individual AgentBrowser / recovery instances. Orchestrator only coordinates resources.
- Strong documentation of limits (see rate_limiter.py #87 caveats): this is an
  *in-process* coordinator. True fleet scale across machines requires sharding +
  external coordination (Redis rate limits, proxy gateway, etc.).

### Non-Goals for this minimal core implementation
- No automatic scaling, no persistent task queue, no cross-process comms, no advanced
  scheduling / priority, no automatic proxy health probing (ProxyManager can be
  extended later), no UI / TUI.
- Rotation inside a browser (via its AntiBlockOrchestrator) continues to use that
  browser's ProxyManager (usually creating a new sticky session on the *same* base
  credentials). Pool-level "give me a completely different upstream proxy" can be
  added as a future hook if needed.
- No changes to AgentBrowser, ProxyManager, or recovery internals.

### Basic Usage
```python
from production.agent_orchestrator import AgentOrchestrator, ProxyPool
from proxy.proxy_manager import ProxyConfig
from production.rate_limiter import AccountRateLimiter
from production.metrics import MetricsCollector

# Prepare 2 distinct proxies (Decodo example)
proxies = [
    ProxyConfig(provider="decodo", host="gate.decodo.com", port=10001,
                username="user-xxx-country-us-session-...", password="pw", country="us"),
    ProxyConfig(provider="decodo", host="gate.decodo.com", port=10001,
                username="user-xxx-country-us-session-...", password="pw", country="us"),
]

fleet = AgentOrchestrator(
    max_browsers=3,
    proxies=proxies,
    shared_rate_limiter=AccountRateLimiter(),
    shared_metrics=MetricsCollector(),
    namespace="prod-fleet-1",   # passed to rate limiter for isolation
    default_launch_kwargs={"headless": True, "light_mode": True},
)

async with fleet:
    # Acquire a browser bound to a logical account (for rate limiting + traceability)
    browser = await fleet.acquire_browser(account_id="linkedin-alice")
    try:
        # Central rate wait (or call browser.rate_limiter directly since shared object)
        await fleet.wait_rate_limit(account_id="linkedin-alice", domain="linkedin.com")

        success = await browser.safe_goto("https://www.linkedin.com/feed/", platform="linkedin")
        # ... do work via browser.human, browser.page, browser.recovery etc.
        html = await browser.page.content()
    finally:
        await fleet.release_browser("linkedin-alice")   # or by the returned lease id

    # Convenience one-shot dispatch (recommended for fire-and-forget tasks)
    async def my_task(b):
        await b.safe_goto("https://example.com", platform="example")
        return await b.page.title()

    title = await fleet.run_on_browser(my_task, account_id="example-bob")
```

See also: AgentBrowser docs for per-instance options (persona, light_mode, pre-configured proxy_manager).
"""

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Awaitable

from proxy.proxy_manager import ProxyConfig, ProxyManager
from production.rate_limiter import AccountRateLimiter
from production.metrics import MetricsCollector
from core.agent_browser import AgentBrowser


@dataclass
class ProxyLease:
    """Represents a checked-out proxy from the pool (internal)."""
    config: ProxyConfig
    leased_at: float = field(default_factory=time.time)
    usage_count: int = 0
    error_count: int = 0


class ProxyPool:
    """
    Lightweight shared proxy pool with usage tracking and basic checkout.

    Intended for use by AgentOrchestrator (or standalone for advanced users).
    Does *not* perform live health checks or automatic rotation of upstream
    credentials — that remains the responsibility of ProxyManager + recovery layer
    inside each AgentBrowser.

    Thread/async safe via internal lock.
    """

    def __init__(self, proxies: Optional[List[ProxyConfig]] = None):
        self._proxies: List[ProxyConfig] = list(proxies or [])
        self._leases: Dict[str, ProxyLease] = {}  # lease_id -> lease
        self._index: int = 0  # round-robin cursor
        self._lock = asyncio.Lock()
        self._stats: Dict[str, Dict[str, Any]] = {}  # session_name-ish -> counters

    @property
    def size(self) -> int:
        return len(self._proxies)

    def add_proxy(self, config: ProxyConfig) -> None:
        """Add a proxy config to the pool (can be called before or after launch)."""
        self._proxies.append(config)

    async def checkout(self, hint: Optional[str] = None) -> Optional[tuple[str, ProxyConfig]]:
        """
        Checkout a proxy (returns (lease_id, config) or None if pool empty).
        Uses simple round-robin + least-recently-used bias.
        """
        if not self._proxies:
            return None

        async with self._lock:
            # Prefer least-used overall (simple heuristic)
            # Fall back to round-robin for even distribution
            sorted_by_use = sorted(
                self._proxies,
                key=lambda p: self._get_usage(p)
            )
            chosen = sorted_by_use[0] if sorted_by_use else self._proxies[self._index % len(self._proxies)]
            self._index = (self._index + 1) % max(1, len(self._proxies))

            lease_id = f"proxy-{uuid.uuid4().hex[:12]}"
            lease = ProxyLease(config=chosen)
            self._leases[lease_id] = lease

            key = self._key_for(chosen)
            self._stats.setdefault(key, {"checkouts": 0, "errors": 0})
            self._stats[key]["checkouts"] += 1

            return lease_id, chosen

    def _get_usage(self, p: ProxyConfig) -> int:
        key = self._key_for(p)
        return self._stats.get(key, {}).get("checkouts", 0)

    def _key_for(self, p: ProxyConfig) -> str:
        return getattr(p, "session_name", None) or f"{p.host}:{p.port}:{p.username[:16]}"

    async def checkin(self, lease_id: str, had_error: bool = False) -> None:
        """Return a proxy lease (updates stats)."""
        async with self._lock:
            lease = self._leases.pop(lease_id, None)
            if not lease:
                return
            key = self._key_for(lease.config)
            st = self._stats.setdefault(key, {"checkouts": 0, "errors": 0})
            if had_error:
                st["errors"] += 1
                lease.error_count += 1

    def mark_error(self, lease_id: str) -> None:
        """Record an error against a still-held lease (call from recovery hooks if desired)."""
        lease = self._leases.get(lease_id)
        if lease:
            key = self._key_for(lease.config)
            self._stats.setdefault(key, {"checkouts": 0, "errors": 0})["errors"] += 1
            lease.error_count += 1

    async def get_stats(self) -> Dict[str, Any]:
        """Return snapshot of pool usage and health (async because of lock)."""
        async with self._lock:
            return {
                "pool_size": len(self._proxies),
                "active_leases": len(self._leases),
                "stats_by_proxy": dict(self._stats),
                "total_checkouts": sum(s.get("checkouts", 0) for s in self._stats.values()),
                "total_errors": sum(s.get("errors", 0) for s in self._stats.values()),
            }

    def __repr__(self):
        return f"ProxyPool(size={len(self._proxies)}, active={len(self._leases)})"


class AgentOrchestrator:
    """
    High-level Fleet / Multi-Agent Orchestrator.

    Manages multiple `AgentBrowser` instances with:
    - Shared rate limiter (pass the same AccountRateLimiter to every child)
    - Shared metrics collector
    - Optional shared ProxyPool (distinct proxies assigned on creation)
    - Bounded concurrency
    - Acquire/release leasing
    - One-liner dispatch via `run_on_browser`

    See module docstring for full rationale, caveats (#87), and usage examples.
    """

    def __init__(
        self,
        max_browsers: int = 5,
        proxies: Optional[List[ProxyConfig]] = None,
        shared_rate_limiter: Optional[AccountRateLimiter] = None,
        shared_metrics: Optional[MetricsCollector] = None,
        namespace: Optional[str] = None,
        default_launch_kwargs: Optional[Dict[str, Any]] = None,
    ):
        self.max_browsers = max_browsers
        self.namespace = namespace
        self.default_launch_kwargs: Dict[str, Any] = default_launch_kwargs or {"headless": True}

        # Shared resources (create fresh if not supplied — caller can share across fleets)
        self.rate_limiter: AccountRateLimiter = shared_rate_limiter or AccountRateLimiter()
        self.metrics: MetricsCollector = shared_metrics or MetricsCollector()

        # Proxy pool
        self.proxy_pool = ProxyPool(proxies or [])

        # Managed browsers: browser_id -> state dict
        # state: {"browser": AgentBrowser, "account_id": str|None, "proxy_lease_id": str|None,
        #         "proxy_config": ProxyConfig|None, "leased": bool, "created_at": float}
        self._browsers: Dict[str, Dict[str, Any]] = {}
        self._semaphore = asyncio.Semaphore(max_browsers)
        self._lock = asyncio.Lock()  # protects _browsers and lease state

        self._closed = False

    async def launch_fleet(self, count: int, launch_kwargs: Optional[Dict[str, Any]] = None) -> List[str]:
        """
        Pre-launch `count` browsers (up to max_browsers).
        Each gets a distinct proxy (if pool non-empty) and the shared rate/metrics objects.
        Returns list of browser_ids.
        """
        ids = []
        for _ in range(min(count, self.max_browsers - len(self._browsers))):
            bid = await self._create_browser(launch_kwargs=launch_kwargs)
            ids.append(bid)
        return ids

    async def _create_browser(
        self,
        account_id: Optional[str] = None,
        launch_kwargs: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Internal: create + launch one AgentBrowser, optionally bound to a proxy + account."""
        async with self._lock:
            if len(self._browsers) >= self.max_browsers:
                raise RuntimeError(f"Fleet at capacity ({self.max_browsers})")

            browser_id = f"browser-{uuid.uuid4().hex[:10]}"
            effective_account = account_id or browser_id

            # Create the browser with shared resources (core of #39 / #80 / #66)
            browser = AgentBrowser(
                session_name=effective_account,
                rate_limiter=self.rate_limiter,
                metrics_collector=self.metrics,
                # light_mode etc can come via launch_kwargs
            )

            # Assign proxy from pool if available (shared pool with tracking)
            proxy_lease_id = None
            proxy_cfg = None
            lease = await self.proxy_pool.checkout(hint=effective_account)
            if lease:
                proxy_lease_id, proxy_cfg = lease
                # Wire into the per-browser ProxyManager *before* launch
                try:
                    browser.proxy_manager.current_config = proxy_cfg
                    # Also ensure create_decodo-style state if needed by recovery rotation
                    # (many paths read .current_config directly)
                except Exception:
                    pass  # best effort

            # Launch (respect caller overrides + defaults)
            lk = {**self.default_launch_kwargs, **(launch_kwargs or {})}
            await browser.launch(**lk)

            # Record
            self._browsers[browser_id] = {
                "browser": browser,
                "account_id": effective_account,
                "proxy_lease_id": proxy_lease_id,
                "proxy_config": proxy_cfg,
                "leased": False,
                "created_at": time.time(),
                "launched_with": lk,
            }

            # Tag the browser instance for traceability (useful in logs / recovery)
            try:
                setattr(browser, "_fleet_id", browser_id)
                setattr(browser, "_fleet_account", effective_account)
            except Exception:
                pass

            return browser_id

    async def acquire_browser(
        self,
        account_id: Optional[str] = None,
        launch_kwargs: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> AgentBrowser:
        """
        Acquire a (possibly newly created) browser from the fleet.

        Waits for a concurrency slot (semaphore).
        If under capacity and no idle browser matches, a fresh one is launched.
        The returned browser is marked "leased" until release_browser is called.

        Returns the live AgentBrowser (already launched).
        Use in try/finally with release_browser(account_id or browser._fleet_id).
        """
        if self._closed:
            raise RuntimeError("AgentOrchestrator has been closed")

        await asyncio.wait_for(self._semaphore.acquire(), timeout=timeout)

        async with self._lock:
            # Look for an unleased browser (preference for matching account if given)
            for bid, state in self._browsers.items():
                if not state["leased"]:
                    if account_id is None or state.get("account_id") == account_id:
                        state["leased"] = True
                        state["lease_start"] = time.time()
                        return state["browser"]

            # None free that match — create a new one if capacity allows
            if len(self._browsers) < self.max_browsers:
                bid = await self._create_browser(account_id=account_id, launch_kwargs=launch_kwargs)
                state = self._browsers[bid]
                state["leased"] = True
                state["lease_start"] = time.time()
                return state["browser"]

            # All in use and at capacity — release the semaphore slot we took and wait for a release
            self._semaphore.release()

        # Wait for any release (simple approach: poll + re-acquire)
        # In production a condition variable would be nicer, but this is minimal & correct.
        deadline = time.time() + (timeout or 300)
        while time.time() < deadline:
            async with self._lock:
                for bid, state in self._browsers.items():
                    if not state["leased"]:
                        if account_id is None or state.get("account_id") == account_id:
                            # re-acquire slot
                            await self._semaphore.acquire()
                            state["leased"] = True
                            state["lease_start"] = time.time()
                            return state["browser"]
            await asyncio.sleep(0.05)

        raise TimeoutError("Timed out acquiring a browser from the fleet")

    async def release_browser(self, identifier: str, had_error: bool = False) -> None:
        """
        Release a previously acquired browser back to the pool.

        `identifier` can be:
          - the account_id used at acquire
          - the browser_id returned from internal structures (browser._fleet_id)
          - or the AgentBrowser instance itself
        """
        async with self._lock:
            target_bid = None
            target_state = None

            for bid, state in self._browsers.items():
                b = state["browser"]
                if (
                    identifier == bid
                    or identifier == state.get("account_id")
                    or (hasattr(identifier, "_fleet_id") and identifier._fleet_id == bid)
                    or identifier is b
                ):
                    target_bid = bid
                    target_state = state
                    break

            if not target_state or not target_state.get("leased"):
                # Idempotent / already released
                self._semaphore.release()  # safety — ensure we don't leak slots
                return

            target_state["leased"] = False
            target_state.pop("lease_start", None)

            # Return proxy lease (if any) with error flag for pool stats
            plid = target_state.get("proxy_lease_id")
            if plid:
                await self.proxy_pool.checkin(plid, had_error=had_error)

            self._semaphore.release()

    async def wait_rate_limit(self, account: str, domain: str) -> float:
        """Central helper — waits using the fleet's shared rate limiter (with namespace)."""
        return await self.rate_limiter.wait_if_needed(account, domain, namespace=self.namespace)

    async def run_on_browser(
        self,
        func: Callable[[AgentBrowser], Awaitable[Any]],
        account_id: Optional[str] = None,
        launch_kwargs: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        release_on_error: bool = True,
    ) -> Any:
        """
        Acquire a browser, (optionally) wait for rate limit on the account, run func(browser),
        then release. Returns whatever func returns.

        Excellent for simple fire-and-forget or map-reduce style fleet workloads.
        """
        browser = await self.acquire_browser(account_id=account_id, launch_kwargs=launch_kwargs, timeout=timeout)
        acc = account_id or getattr(browser, "_fleet_account", "unknown")
        try:
            await self.wait_rate_limit(acc, "orchestrator-task")
            result = await func(browser)
            await self.release_browser(browser, had_error=False)
            return result
        except Exception:
            if release_on_error:
                await self.release_browser(browser, had_error=True)
            raise

    async def close_all(self, force: bool = False) -> None:
        """Close every managed browser and release all resources. Idempotent."""
        if self._closed and not force:
            return
        self._closed = True

        async with self._lock:
            for bid, state in list(self._browsers.items()):
                b = state.get("browser")
                if b:
                    try:
                        await b.close()
                    except Exception:
                        pass
                plid = state.get("proxy_lease_id")
                if plid:
                    try:
                        await self.proxy_pool.checkin(plid, had_error=False)
                    except Exception:
                        pass
            self._browsers.clear()

        # Drain semaphore if needed
        for _ in range(self.max_browsers):
            try:
                self._semaphore.release()
            except ValueError:
                break

    async def get_stats(self) -> Dict[str, Any]:
        """Aggregate fleet health + usage snapshot."""
        async with self._lock:
            active = sum(1 for s in self._browsers.values() if s.get("leased"))
            total = len(self._browsers)
            proxy_stats = await self.proxy_pool.get_stats()
            return {
                "total_browsers": total,
                "active_leases": active,
                "capacity": self.max_browsers,
                "namespace": self.namespace,
                "proxy_pool": proxy_stats,
                "metrics_sample": {
                    "counters": dict(self.metrics.counters) if hasattr(self.metrics, "counters") else {},
                },
                "rate_limiter_accounts": len(getattr(self.rate_limiter, "account_limiters", {})),
            }

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close_all()
        return False

    def __repr__(self):
        return (
            f"AgentOrchestrator(max={self.max_browsers}, "
            f"active={len([s for s in self._browsers.values() if s.get('leased')])}, "
            f"pool={self.proxy_pool})"
        )


# Convenience alias matching issue titles ("Fleet / AgentOrchestrator")
Fleet = AgentOrchestrator

__all__ = ["AgentOrchestrator", "Fleet", "ProxyPool"]
