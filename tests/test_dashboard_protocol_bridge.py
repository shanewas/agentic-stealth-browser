"""Tests for the dashboard-to-protocol-adapter bridge (M4).

The bridge wires the M1-M3 Protocol adapters (production.adapters.*)
into the dashboard's BrowserRuntimeManager as a thin shim. The legacy
in-file adapters (DashboardBackendAdapter subclasses) are preserved —
a full rewrite is v2.5.1.
"""
from __future__ import annotations

import pytest

from production.adapters import BACKEND_REGISTRY, Capability
from production.dashboard_adapter_bridge import DashboardProtocolBridge
from production.hermes_dashboard import BrowserRuntimeManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def manager(tmp_path, monkeypatch):
    """Construct a real BrowserRuntimeManager pointed at tmp_path.

    The dashboard constructor wants a real activity stream + storage root;
    we provide both via the manager's own initializer.
    """
    # NOTE: spec's draft used `settings=DashboardSettings(...)`, but
    # BrowserRuntimeManager.__init__ takes (agent_browser_cls, storage_root,
    # activity), not a settings kwarg. We mirror the existing dashboard
    # test pattern (tests/test_hermes_dashboard.py).
    manager = BrowserRuntimeManager(storage_root=tmp_path / "agentic-browser")
    return manager


# ---------------------------------------------------------------------------
# Bridge construction
# ---------------------------------------------------------------------------

def test_bridge_constructs_with_manager(manager):
    """The bridge holds a reference to the manager for activity events."""
    bridge = DashboardProtocolBridge(manager)
    assert bridge.manager is manager


def test_bridge_initializes_protocol_adapter_registry(manager):
    """On construction, the bridge registers all M1-M3 Protocol adapters."""
    bridge = DashboardProtocolBridge(manager)
    assert "cdp-bridge" in bridge.protocol_adapters
    assert "playwright-mcp" in bridge.protocol_adapters
    assert "agentic-stealth-mcp" in bridge.protocol_adapters


def test_get_protocol_adapter_returns_class(manager):
    """get_protocol_adapter(name) returns the M1-M3 adapter class."""
    bridge = DashboardProtocolBridge(manager)
    cls = bridge.get("playwright-mcp")
    assert cls is BACKEND_REGISTRY["playwright-mcp"]


def test_get_protocol_adapter_raises_for_unknown(manager):
    from production.adapters import AdapterNotFoundError
    bridge = DashboardProtocolBridge(manager)
    with pytest.raises(AdapterNotFoundError):
        bridge.get("nonexistent")


# ---------------------------------------------------------------------------
# Manager integration
# ---------------------------------------------------------------------------

def test_manager_exposes_protocol_adapters_attribute(manager):
    """BrowserRuntimeManager.protocol_adapters is populated on construction."""
    assert hasattr(manager, "protocol_adapters")
    assert "cdp-bridge" in manager.protocol_adapters
    assert "playwright-mcp" in manager.protocol_adapters
    assert "agentic-stealth-mcp" in manager.protocol_adapters


def test_manager_default_active_protocol_adapter_is_none(manager):
    """No protocol adapter is active until use_protocol_adapter() is called."""
    assert manager.active_protocol_adapter is None


def test_use_protocol_adapter_switches(manager):
    """Calling use_protocol_adapter(name) sets active_protocol_adapter and
    records an audit event in the manager's activity stream."""
    manager.use_protocol_adapter("playwright-mcp")
    assert manager.active_protocol_adapter == "playwright-mcp"
    events = [
        e for e in manager.activity._events
        if e.event == "protocol_adapter_activated"
    ]
    assert events, "No protocol_adapter_activated audit event recorded"


def test_use_protocol_adapter_rejects_unknown(manager):
    from production.adapters import AdapterNotFoundError
    with pytest.raises(AdapterNotFoundError):
        manager.use_protocol_adapter("nonexistent")


# ---------------------------------------------------------------------------
# Status surfacing (the issue's acceptance criterion)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_status_includes_protocol_adapter_capabilities(manager):
    """The dashboard's status() response must include the M1-M3 capabilities.

    Issue #444 acceptance criterion: "Dashboard status identifies the
    active adapter and its negotiated capabilities."
    """
    manager.use_protocol_adapter("playwright-mcp")
    status = await manager.status()
    assert "protocol_adapters" in status
    assert "playwright-mcp" in status["protocol_adapters"]
    caps = status["protocol_adapters"]["playwright-mcp"]
    # Capability enum serializes as its .value (string)
    assert Capability.LAUNCH.value in caps
    assert Capability.STREAM_CDP.value not in caps  # Playwright-MCP lacks it


@pytest.mark.asyncio
async def test_status_includes_active_protocol_adapter(manager):
    manager.use_protocol_adapter("cdp-bridge")
    status = await manager.status()
    assert status.get("active_protocol_adapter") == "cdp-bridge"


@pytest.mark.asyncio
async def test_status_active_protocol_adapter_is_none_initially(manager):
    status = await manager.status()
    assert status.get("active_protocol_adapter") is None


# ---------------------------------------------------------------------------
# Capability surfacing vs the in-file adapters (M4 should NOT remove them)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_legacy_capabilities_still_present(manager):
    """The existing 'capabilities' key in status() must still be present
    (the legacy in-file adapters are NOT removed in M4)."""
    status = await manager.status()
    assert "capabilities" in status
    assert "playwright-mcp" in status["capabilities"]
    assert "agentic-stealth-mcp" in status["capabilities"]
    assert "cdp-bridge" in status["capabilities"]


# ---------------------------------------------------------------------------
# Backwards compatibility: existing in-file adapters still work
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_legacy_adapters_still_respond_to_status(manager):
    """The legacy in-file DashboardBackendAdapter objects must still be in
    manager.adapters (their presence is what status()['capabilities'] reads)."""
    assert "playwright-mcp" in manager.adapters
    assert "cdp-bridge" in manager.adapters
    assert "agentic-stealth-mcp" in manager.adapters
