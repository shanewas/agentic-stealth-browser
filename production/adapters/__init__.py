"""Backend adapter package.

M0: defines the contract only. M1 (cdp_bridge), M2 (playwright_mcp),
M3 (agentic_stealth_mcp) register their concrete implementations in
BACKEND_REGISTRY.

Public surface:
    BackendAdapter         - the protocol
    Capability             - the feature enum
    AdapterLaunchError     - cannot start (runtime)
    AdapterCapabilityError - cannot perform a requested action
    AdapterNotFoundError   - get_adapter() was called with an unknown name
    BACKEND_REGISTRY       - mutable dict[name -> Adapter class]
    get_adapter(name)      - registry lookup with friendly error
    register_adapter(cls)  - validate + register a BackendAdapter subclass
"""
from __future__ import annotations

from production.adapters.base import (
    AdapterCapabilityError,
    AdapterLaunchError,
    AdapterNotFoundError,
    BackendAdapter,
    Capability,
)

# Public registry. M1-M3 append their adapter classes here.
# Note: this is intentionally a plain dict, not a frozen mapping, so
# future extensions (plugins, user-provided adapters) can register at runtime.
BACKEND_REGISTRY: dict[str, type[BackendAdapter]] = {}


def register_adapter(cls: type[BackendAdapter]) -> type[BackendAdapter]:
    """Validate and register a BackendAdapter subclass in BACKEND_REGISTRY.

    Validation rules (so footguns fail loud at registration, not at runtime):
      * ``cls.name`` must be a non-empty string. This prevents two failure
        modes we hit before: empty ``name`` (renders as "": "" in the
        dashboard status JSON) and unnamed adapters silently colliding.
      * The name must be unique within BACKEND_REGISTRY; re-registration
        of the same name raises AdapterLaunchError (not a silent overwrite).

    Returns ``cls`` so this can be used as a class decorator:

        @register_adapter
        class CdpBridgeAdapter:
            name = "cdp_bridge"
            ...
    """
    name = getattr(cls, "name", None)
    if not isinstance(name, str) or not name:
        raise AdapterLaunchError(
            f"{cls.__name__!r} cannot be registered: "
            f"`name` must be a non-empty string, got {name!r}"
        )
    if name in BACKEND_REGISTRY:
        existing = BACKEND_REGISTRY[name].__name__
        raise AdapterLaunchError(
            f"Backend adapter {name!r} is already registered to {existing!r}; "
            f"refusing to silently overwrite with {cls.__name__!r}"
        )
    BACKEND_REGISTRY[name] = cls
    return cls


def get_adapter(name: str) -> type[BackendAdapter]:
    """Look up an adapter class by name. Raises AdapterNotFoundError if
    the name is not registered — NOT AdapterLaunchError, which is reserved
    for runtime launch failures. This lets callers distinguish:
      * "wrong/missing configuration" (AdapterNotFoundError -> LookupError)
      * "process spawn / handshake failed" (AdapterLaunchError -> RuntimeError)
    """
    if name not in BACKEND_REGISTRY:
        registered = ", ".join(sorted(BACKEND_REGISTRY.keys())) or "<none>"
        raise AdapterNotFoundError(
            f"Unknown backend adapter: {name!r}. "
            f"Registered adapters: {registered}"
        )
    return BACKEND_REGISTRY[name]


# M1: CDP-bridge adapter registration
from production.adapters.cdp_bridge import CDPBridgeAdapter as _CDPBridgeAdapter  # noqa: E402
register_adapter(_CDPBridgeAdapter)

# M2: Playwright-MCP adapter registration
from production.adapters.playwright_mcp import PlaywrightMCPAdapter as _PlaywrightMCPAdapter  # noqa: E402
register_adapter(_PlaywrightMCPAdapter)


__all__ = [
    "AdapterCapabilityError",
    "AdapterLaunchError",
    "AdapterNotFoundError",
    "BACKEND_REGISTRY",
    "BackendAdapter",
    "Capability",
    "get_adapter",
    "register_adapter",
]
