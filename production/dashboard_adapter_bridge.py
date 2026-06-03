"""Bridge between the dashboard's BrowserRuntimeManager and the M1-M3
Protocol adapters (production.adapters.*).

This is a thin shim, NOT a rewrite. The legacy in-file adapter classes
in production.hermes_dashboard (DashboardBackendAdapter subclasses) are
preserved; this module wires the new Protocol adapters in NEXT to them.

A full rewrite — replacing the in-file classes with Protocol-based
delegation — is deferred to v2.5.1.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from production.adapters import BACKEND_REGISTRY, BackendAdapter, get_adapter

if TYPE_CHECKING:
    from production.hermes_dashboard import BrowserRuntimeManager


def get_protocol_adapter(name: str) -> type[BackendAdapter]:
    """Module-level convenience wrapper around ``production.adapters.get_adapter``.

    Provided as a top-level symbol so callers (e.g. CLI tooling, future
    v2.5.1 action dispatch) can reach a Protocol adapter class without
    needing a live ``BrowserRuntimeManager`` instance.
    """
    return get_adapter(name)


class DashboardProtocolBridge:
    """Bridges BrowserRuntimeManager to the M1-M3 Protocol adapters.

    Construction populates the protocol adapter registry from
    production.adapters.BACKEND_REGISTRY. The bridge can be queried
    for adapter classes, instantiated adapter instances, and capability
    sets; it does NOT replace the manager's legacy in-file adapters.
    """

    def __init__(self, manager: "BrowserRuntimeManager") -> None:
        self.manager = manager
        # Mirror the BACKEND_REGISTRY for fast lookup. This is a snapshot
        # at construction time; new adapters registered after bridge
        # construction are NOT visible until the bridge is rebuilt.
        self.protocol_adapters: dict[str, type[BackendAdapter]] = dict(BACKEND_REGISTRY)

    def get(self, name: str) -> type[BackendAdapter]:
        """Look up a Protocol adapter class by registered name.

        Raises AdapterNotFoundError if the name is not registered
        (delegated to the M0 helper).
        """
        return get_adapter(name)

    def capability_set(self, name: str) -> set[str]:
        """Return the wire-form (string) capability set for an adapter.

        Used by the dashboard's status() response to surface capabilities
        to the frontend without leaking the Python enum type.
        """
        cls = self.get(name)
        # Construct a transient instance to query capabilities().
        # All M1-M3 adapter classes are stateless constructors (no launch
        # required for capability introspection), per the M0 contract.
        return {c.value for c in cls().capabilities()}

    def all_capability_sets(self) -> dict[str, list[str]]:
        """Return all registered adapters' capability sets, keyed by name.

        Format: {name: [str, str, ...]} (sorted, for stable JSON output).
        """
        return {
            name: sorted(self.capability_set(name))
            for name in sorted(self.protocol_adapters.keys())
        }
