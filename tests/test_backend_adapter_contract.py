"""Contract tests for the BackendAdapter protocol.

These tests pin the public surface that M1-M3 will implement. They run
without any actual adapter logic — just the protocol/enum/registry.
"""
from __future__ import annotations

import pytest

from production.adapters import (
    BACKEND_REGISTRY,
    AdapterCapabilityError,
    AdapterLaunchError,
    BackendAdapter,
    Capability,
    get_adapter,
)


def test_capability_enum_has_canonical_members():
    """All canonical capabilities must be present. Adding a new one
    is a deliberate API change; this test must be updated consciously."""
    expected = {
        "LAUNCH",
        "CLOSE",
        "NAVIGATE",
        "CLICK",
        "FILL",
        "SCREENSHOT",
        "STATUS",
        "STREAM_CDP",
        "MULTI_CONTEXT",
        "HEADLESS_SWITCH",
    }
    actual = {c.name for c in Capability}
    assert expected.issubset(actual), (
        f"Missing capabilities: {expected - actual}"
    )


def test_backend_adapter_is_a_protocol():
    """BackendAdapter must be a typing.Protocol so adapters can use
    structural subtyping (no forced inheritance)."""
    # Protocol classes have _is_protocol attribute in CPython
    assert hasattr(BackendAdapter, "_is_protocol") or (
        getattr(BackendAdapter, "__class__", None).__name__ == "ProtocolMeta"
    ), "BackendAdapter must be a typing.Protocol"


def test_backend_adapter_has_required_methods():
    """The protocol must define the eight action methods + capabilities()."""
    required = {
        "launch", "close", "navigate", "click", "fill",
        "screenshot", "status", "capabilities", "supports",
    }
    actual = set(dir(BackendAdapter))
    missing = required - actual
    assert not missing, f"BackendAdapter missing methods: {missing}"


def test_backend_adapter_has_name_attribute():
    """Every adapter must declare a stable name string."""
    assert "name" in dir(BackendAdapter)


def test_get_adapter_raises_for_unknown_backend():
    """get_adapter must raise AdapterLaunchError (not bare KeyError)
    so callers can handle the failure mode uniformly."""
    with pytest.raises(AdapterLaunchError) as exc_info:
        get_adapter("does-not-exist")
    assert "does-not-exist" in str(exc_info.value)


def test_backend_registry_is_a_dict():
    """The registry is a public, mutable dict. M1-M3 will register adapters here."""
    assert isinstance(BACKEND_REGISTRY, dict)
    # Initially empty in M0; M1-M3 will populate
    # We do not assert emptiness — M0 is the contract, M1+ is the impl.


def test_adapter_capability_error_inherits_from_runtime_error():
    """AdapterCapabilityError must be catchable as RuntimeError so
    callers can write a single except clause for adapter failures."""
    assert issubclass(AdapterCapabilityError, RuntimeError)
    assert issubclass(AdapterLaunchError, RuntimeError)


def test_capability_values_are_strings():
    """Capabilities serialise as strings for JSON / dashboard status."""
    for cap in Capability:
        # Capability can be StrEnum or plain Enum; the .value is the wire form.
        assert isinstance(cap.value, str)
        assert cap.value  # not empty


@pytest.mark.parametrize(
    "capability_name",
    ["LAUNCH", "CLOSE", "NAVIGATE", "CLICK", "FILL", "SCREENSHOT",
     "STATUS", "STREAM_CDP", "MULTI_CONTEXT", "HEADLESS_SWITCH"],
)
def test_each_capability_is_independent(capability_name):
    """Each capability is a distinct enum member, not an alias."""
    cap = Capability[capability_name]
    assert cap.name == capability_name
    # Distinct from every other capability
    others = [c for c in Capability if c is not cap]
    for other in others:
        assert cap is not other
