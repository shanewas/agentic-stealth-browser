"""
Compatibility shims and deprecation warnings for v1 → v2 migration.

Import this module anywhere v1 APIs are consumed to emit structured DeprecationWarning
messages when old APIs are used. Shims are provided to keep v1 workflows loading correctly
under v2 while migration is in progress.

These shims will be removed in v2.1.0.

Usage:
    from production.deprecations import deprecated, shim_context

    # Mark old API:
    @deprecated("v2.0.0", replacement="browser.browser_context")
    def old_context(self):
        return self.browser_context

    # Use shim:
    from production.deprecations import ConnectionPoolShim
    pool = ConnectionPoolShim()  # emits DeprecationWarning, delegates to NavigationHistory
"""

from __future__ import annotations

import functools
import logging
import warnings
from typing import Any, Callable, Dict, TypeVar, cast

F = TypeVar("F", bound=Callable[..., Any])

_deprecation_log = logging.getLogger("stealth.deprecations")


def deprecated(
    version: str, replacement: str = "", message: str = ""
) -> Callable[[F], F]:
    """Decorator to mark a function/method as deprecated.

    Emits a DeprecationWarning and logs at WARN level.
    """

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            msg = message or f"{func.__qualname__} is deprecated since {version}"
            if replacement:
                msg += f". Use {replacement} instead."
            warnings.warn(msg, DeprecationWarning, stacklevel=2)
            _deprecation_log.warning(msg)
            return func(*args, **kwargs)

        return cast(F, wrapper)

    return decorator


def warn_deprecated(item: str, version: str, replacement: str = "") -> None:
    """Emit a structured deprecation warning at the call site."""
    msg = f"{item} is deprecated since {version}"
    if replacement:
        msg += f". Use {replacement} instead."
    warnings.warn(msg, DeprecationWarning, stacklevel=2)
    _deprecation_log.warning(msg)


# ── Shim classes for deprecated v1 names ──


class ConnectionPoolShim:
    """Backward-compat shim for ConnectionPool → NavigationHistory rename (#374).

    Emits a DeprecationWarning on first use, then delegates to NavigationHistory.
    Removed in v2.1.0.
    """

    _warned = False

    def __new__(cls, *args: Any, **kwargs: Any) -> Any:
        if not cls._warned:
            warn_deprecated("ConnectionPool", "v2.0.0", "NavigationHistory")
            cls._warned = True
        from core.connection_pool import ConnectionPool as _CP

        return _CP(*args, **kwargs)


def shim_context_attr(owner: Any, name: str) -> Any:
    """Access `self.context` on AgentBrowser while emitting a deprecation warning."""
    warn_deprecated(
        f"{type(owner).__name__}.{name}",
        "v2.0.0",
        f"{type(owner).__name__}.browser_context",
    )
    if hasattr(owner, "browser"):
        return getattr(owner, "browser")
    return None


def generate_deprecation_report() -> Dict[str, Any]:
    """Return a structured report of all deprecated APIs and their replacements.

    Used by CI migration check and migration guide generation.
    """
    return {
        "deprecated_apis": [
            {
                "name": "AgentBrowser.context",
                "version": "v2.0.0",
                "replacement": "AgentBrowser.browser_context",
                "removal": "v2.1.0",
            },
            {
                "name": "ConnectionPool",
                "version": "v2.0.0",
                "replacement": "NavigationHistory",
                "removal": "v2.1.0",
            },
            {
                "name": "rate_limiter naive datetime",
                "version": "v2.0.0",
                "replacement": "timezone-aware UTC datetimes",
                "removal": "v2.1.0",
            },
            {
                "name": "metrics naive datetime uptime",
                "version": "v2.0.0",
                "replacement": "time.monotonic()",
                "removal": "v2.1.0",
            },
            {
                "name": "ad-hoc MCP response shapes",
                "version": "v2.0.0",
                "replacement": "unified_result_envelope",
                "removal": "v2.1.0",
            },
        ],
        "migration_guide_url": "See CHANGELOG.md and scripts/migrate_v1_to_v2.py",
        "migration_script": "scripts/migrate_v1_to_v2.py",
    }
