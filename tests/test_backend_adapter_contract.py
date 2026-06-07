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
    AdapterNotFoundError,
    BackendAdapter,
    Capability,
    get_adapter,
    register_adapter,
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
    assert expected.issubset(actual), f"Missing capabilities: {expected - actual}"


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
        "launch",
        "close",
        "navigate",
        "click",
        "fill",
        "screenshot",
        "status",
        "capabilities",
        "supports",
    }
    actual = set(dir(BackendAdapter))
    missing = required - actual
    assert not missing, f"BackendAdapter missing methods: {missing}"


def test_backend_adapter_has_name_attribute():
    """Every adapter must declare a stable name string. We check the
    annotation (not dir(), which would have included the old `name: str = ""`
    default). The absence of a default value also means adapters that
    forget to override it fail at attribute access, not silently — which
    is the footgun issue 3 in the code-quality review addresses."""
    annotations = getattr(BackendAdapter, "__annotations__", {})
    assert "name" in annotations, (
        f"BackendAdapter must declare `name` in its annotations; "
        f"got {sorted(annotations)}"
    )
    # `from __future__ import annotations` makes all annotations PEP 563
    # strings, so compare against the string "str" rather than the type itself.
    assert annotations["name"] == "str", (
        f"BackendAdapter.name must be typed as `str`, got {annotations['name']!r}"
    )


def test_get_adapter_raises_adapter_not_found_for_unknown_backend():
    """get_adapter must raise AdapterNotFoundError (a LookupError subclass)
    for unknown names — NOT AdapterLaunchError, which is reserved for
    runtime launch failures. This separation lets callers distinguish
    "wrong name" from "process spawn failed"."""
    with pytest.raises(AdapterNotFoundError) as exc_info:
        get_adapter("does-not-exist")
    assert "does-not-exist" in str(exc_info.value)
    # Must also be catchable as LookupError so generic dict-style handlers work
    with pytest.raises(LookupError):
        get_adapter("does-not-exist")


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


@pytest.mark.parametrize(
    "capability_name",
    [
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
    ],
)
def test_capability_wire_value_is_lowercase_name(capability_name):
    """The wire form of a Capability must be its lowercase name so the
    dashboard's status field and JSON payloads stay stable as we add members."""
    cap = Capability[capability_name]
    assert cap.value == capability_name.lower(), (
        f"Capability.{capability_name}.value should be {capability_name.lower()!r}, "
        f"got {cap.value!r}"
    )
    # Belt-and-braces: still a non-empty string (kept from the older loose test).
    assert isinstance(cap.value, str) and cap.value


def test_adapter_passes_runtime_checkable_isinstance():
    """BackendAdapter is @runtime_checkable, so a class with the right shape
    must pass isinstance() even without inheriting. This is the whole point
    of the protocol: structural subtyping for plugin-style adapters."""

    class _GoodAdapter:
        name = "good"

        async def launch(self, profile, headless=True): ...
        async def close(self): ...
        async def navigate(self, url): ...
        async def click(self, selector): ...
        async def fill(self, selector, value): ...
        async def screenshot(self, path=None): ...
        async def status(self): ...
        def capabilities(self):
            return set()

        def supports(self, capability):
            return False

    class _BadAdapter:
        """Missing close() and click() — must NOT satisfy the protocol."""

        name = "bad"

        async def launch(self, profile, headless=True): ...
        async def navigate(self, url): ...
        async def fill(self, selector, value): ...
        async def screenshot(self, path=None): ...
        async def status(self): ...
        def capabilities(self):
            return set()

    assert isinstance(_GoodAdapter(), BackendAdapter), (
        "_GoodAdapter implements every method and must satisfy the protocol"
    )
    assert not isinstance(_BadAdapter(), BackendAdapter), (
        "_BadAdapter is missing close() and click() and must fail isinstance()"
    )


def test_supports_default_uses_capabilities_set_membership():
    """BackendAdapter.supports() default must return True for declared
    capabilities and False for undeclared ones. This pins the default
    behaviour so M1-M3 inherit it for free unless they override.

    We invoke the unbound ``BackendAdapter.supports`` method directly
    against a stub instance. Protocol default methods don't propagate to
    unrelated classes (Python typing.Protocol semantics), so we test the
    default as it lives on the protocol itself."""

    class _Stub:
        name = "stub"

        def capabilities(self):
            return {Capability.LAUNCH, Capability.CLOSE}

        # NOTE: no supports() — we want the protocol's default to be exercised

    stub = _Stub()
    # Call the protocol's default supports() against our stub. The default
    # body is `return capability in self.capabilities()`, so this is exactly
    # what an inheriting adapter would do unless it overrides. The stub is
    # intentionally incomplete; we are exercising the unbound method, not
    # asserting full protocol conformance.
    assert BackendAdapter.supports(stub, Capability.LAUNCH) is True  # type: ignore[arg-type]
    assert BackendAdapter.supports(stub, Capability.CLOSE) is True  # type: ignore[arg-type]
    assert BackendAdapter.supports(stub, Capability.CLICK) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# registry guards (added in v2.5.0 review fixes)
# ---------------------------------------------------------------------------


def test_register_adapter_rejects_duplicate_name():
    """The registry must fail loud, not silently overwrite, when two
    adapters claim the same name. Real-world impact: a user plugin with
    a name collision would otherwise mask the built-in adapter and be
    near-impossible to debug.

    Uses a unique, throwaway name to avoid colliding with the three
    built-in adapters (cdp-bridge, playwright-mcp, agentic-stealth-mcp).
    """
    unique = "_test_dup_probe_zz"

    # The stubs are intentionally incomplete — we only care that
    # register_adapter enforces the name-uniqueness invariant before
    # any protocol-conformance check. Mirror the existing _Stub pattern
    # in this file (`# type: ignore[arg-type]`) to keep pyright quiet.
    @register_adapter  # type: ignore[arg-type]
    class _First:
        name = unique

        def capabilities(self):
            return set()

    try:
        with pytest.raises(AdapterLaunchError, match="already registered"):

            @register_adapter  # type: ignore[arg-type]
            class _Second:
                name = unique

                def capabilities(self):
                    return set()
    finally:
        # Clean up so subsequent tests see the original registry.
        BACKEND_REGISTRY.pop(unique, None)


def test_register_adapter_rejects_empty_name():
    """An adapter with name='' must be rejected at registration time,
    not silently added (which would render as '': '' in dashboard
    status JSON and be undebuggable)."""

    class _Anon:
        name = ""

        def capabilities(self):
            return set()

    with pytest.raises(AdapterLaunchError, match="non-empty string"):
        register_adapter(_Anon)  # type: ignore[arg-type]


def test_register_adapter_rejects_non_string_name():
    """Defends against accidental `name = SomeEnum.X` or `name = 1`."""

    class _Bad:
        name = 42

        def capabilities(self):
            return set()

    with pytest.raises(AdapterLaunchError, match="non-empty string"):
        register_adapter(_Bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# JSON-RPC stdio frame size cap (v2.5.0 review fix F2)
# ---------------------------------------------------------------------------


def test_jsonrpc_frame_size_limit_constant_exists():
    """A 16MB hard cap on a single JSON-RPC frame protects the client
    from a misbehaving (or hostile) server emitting a runaway readline.
    Pin the constant so a future refactor doesn't quietly remove it."""
    from production.adapters import _jsonrpc_stdio

    assert hasattr(_jsonrpc_stdio, "MAX_FRAME_BYTES")
    assert _jsonrpc_stdio.MAX_FRAME_BYTES == 16 * 1024 * 1024
