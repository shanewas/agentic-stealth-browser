"""BackendAdapter protocol and capability definitions.

This module defines the contract that M1-M3 implement. See
docs/plans/2026-06-03-v2.5.0-real-backend-adapters.md for the full design.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Protocol, runtime_checkable


class Capability(str, Enum):
    """Negotiable features a backend adapter may or may not support.

    Each backend declares its capability set via BackendAdapter.capabilities().
    The dashboard uses this to decide what UI affordances to expose and what
    errors to raise when an unsupported action is requested.

    Wire form is the enum .value (a string) so it round-trips through JSON.
    """

    LAUNCH = "launch"  # can start a new browser process
    CLOSE = "close"  # can tear down cleanly
    NAVIGATE = "navigate"  # can drive page.goto
    CLICK = "click"  # can drive page.click
    FILL = "fill"  # can drive page.fill
    SCREENSHOT = "screenshot"  # can capture page screenshots
    STATUS = "status"  # can report runtime health
    STREAM_CDP = "stream_cdp"  # can expose raw CDP event stream
    MULTI_CONTEXT = "multi_context"  # can manage multiple BrowserContexts
    HEADLESS_SWITCH = "headless_switch"  # can toggle headless at runtime


class AdapterLaunchError(RuntimeError):
    """Raised when a backend adapter cannot start (process spawn, CDP connect,
    JSON-RPC handshake, etc.). Distinct from AdapterCapabilityError so callers
    can decide whether to fall back to another backend or surface a feature gap.
    """


class AdapterCapabilityError(RuntimeError):
    """Raised when an action is requested that the active adapter does not
    support. Distinct from AdapterLaunchError so callers can render a
    different UX (capability-explanation vs retry-with-different-backend).
    """


class AdapterNotFoundError(LookupError):
    """Raised by get_adapter() when the requested name is not in
    BACKEND_REGISTRY. Inherits from LookupError (the natural superclass for
    "tried to look something up and failed") so callers can write a single
    except clause for missing-resource errors.

    Distinct from AdapterLaunchError, which is reserved for runtime launch
    failures. The two failure modes deserve different UX:
      * AdapterNotFoundError  -> "Backend 'X' is not configured"
      * AdapterLaunchError    -> "Backend 'X' failed to start, retry?"

    Note: KeyError is a subclass of LookupError, so existing callers using
    `except KeyError` will not catch this — that is intentional. The contract
    change forces callers to be explicit about whether they handle a missing
    registration or a runtime failure.
    """


@runtime_checkable
class BackendAdapter(Protocol):
    """Structural interface for all dashboard backend adapters.

    Adapters MAY subclass DashboardBackendAdapter (the legacy shim) or
    implement this protocol directly. The contract is the same.

    Required attribute:
        name: stable string identifier used in BACKEND_REGISTRY and the
              dashboard's "active_adapter" status field. Must be non-empty
              (validated by register_adapter() at registration time).

    Required async methods (see docs/plans/2026-06-03-v2.5.0-real-backend-adapters.md
    for semantics):
        launch(profile, headless) -> None
        close() -> None
        navigate(url) -> None
        click(selector) -> None
        fill(selector, value) -> None
        screenshot(path) -> str   # path saved to; raises AdapterCapabilityError
                                   # if the adapter does not declare Capability.SCREENSHOT
        status() -> dict[str, Any]

    Required sync method:
        capabilities() -> set[Capability]

    Default helpers (inherited by all adapters via the protocol):
        supports(capability) -> bool
    """

    name: str  # subclasses must override; no default — register_adapter enforces non-empty

    async def launch(self, profile: str, headless: bool = True) -> None: ...

    async def close(self) -> None: ...

    async def navigate(self, url: str) -> None: ...

    async def click(self, selector: str) -> None: ...

    async def fill(self, selector: str, value: str) -> None: ...

    async def screenshot(self, path: str) -> str: ...

    async def status(self) -> dict[str, Any]: ...

    def capabilities(self) -> set[Capability]: ...

    def supports(self, capability: Capability) -> bool:
        """Default capability check. Adapters MAY override for custom logic,
        but the default (set membership) is correct for all known cases."""
        return capability in self.capabilities()
