"""Backend adapter package.

M0: defines the contract only. M1 (cdp_bridge), M2 (playwright_mcp),
M3 (agentic_stealth_mcp) register their concrete implementations in
BACKEND_REGISTRY.

Public surface:
    BackendAdapter     - the protocol
    Capability         - the feature enum
    AdapterLaunchError - cannot start
    AdapterCapabilityError - cannot perform a requested action
    BACKEND_REGISTRY   - mutable dict[name -> Adapter class]
    get_adapter(name)  - registry lookup with friendly error
"""
from __future__ import annotations

from production.adapters.base import (
    AdapterCapabilityError,
    AdapterLaunchError,
    BackendAdapter,
    Capability,
)

# Public registry. M1-M3 append their adapter classes here.
# Note: this is intentionally a plain dict, not a frozen mapping, so
# future extensions (plugins, user-provided adapters) can register at runtime.
BACKEND_REGISTRY: dict[str, type[BackendAdapter]] = {}


def get_adapter(name: str) -> type[BackendAdapter]:
    """Look up an adapter class by name. Raises AdapterLaunchError if
    the name is not registered (so callers can write a single except clause
    for adapter-level failures)."""
    if name not in BACKEND_REGISTRY:
        registered = ", ".join(sorted(BACKEND_REGISTRY.keys())) or "<none>"
        raise AdapterLaunchError(
            f"Unknown backend adapter: {name!r}. "
            f"Registered adapters: {registered}"
        )
    return BACKEND_REGISTRY[name]


__all__ = [
    "AdapterCapabilityError",
    "AdapterLaunchError",
    "BACKEND_REGISTRY",
    "BackendAdapter",
    "Capability",
    "get_adapter",
]
