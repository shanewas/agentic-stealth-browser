"""
Unit tests for MCP SessionEnforcer binding exclusivity.

Covers:
- Second-context bind of an owned session is rejected
- Owner check_access passes, non-owner fails
- Wrong-token re-bind rejected, correct-token re-bind (transfer) passes
- Bind after unbind succeeds
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import asyncio

import pytest

from production.mcp_session_isolation import (
    SessionEnforcer,
    SessionIsolationError,
)


class TestSessionEnforcerExclusivity:
    def test_second_context_bind_rejected_and_owner_access_passes(self):
        async def _run():
            enforcer = SessionEnforcer()
            browser = object()
            binding = await enforcer.bind_session("s1", "ctx-a", browser=browser)
            assert binding.browser is browser
            assert binding.owner_context == "ctx-a"

            with pytest.raises(SessionIsolationError):
                await enforcer.bind_session("s1", "ctx-b", browser=object())

            got = await enforcer.check_access("s1", "ctx-a")
            assert got is binding
            assert got.browser is browser

            with pytest.raises(SessionIsolationError):
                await enforcer.check_access("s1", "ctx-b")

        asyncio.run(_run())

    def test_wrong_token_rebind_rejected(self):
        async def _run():
            enforcer = SessionEnforcer()
            await enforcer.bind_session("s1", "ctx-a", browser=object())
            with pytest.raises(SessionIsolationError):
                await enforcer.bind_session(
                    "s1", "ctx-b", binding_token="not-the-token"
                )
            # Owner is unchanged.
            got = await enforcer.check_access("s1", "ctx-a")
            assert got.owner_context == "ctx-a"

        asyncio.run(_run())

    def test_correct_token_rebind_transfers_ownership(self):
        async def _run():
            enforcer = SessionEnforcer()
            browser = object()
            binding = await enforcer.bind_session("s1", "ctx-a", browser=browser)

            rebound = await enforcer.bind_session(
                "s1", "ctx-b", binding_token=binding.token
            )
            assert rebound is binding
            assert rebound.browser is browser
            assert rebound.owner_context == "ctx-b"

            got = await enforcer.check_access("s1", "ctx-b")
            assert got is binding
            with pytest.raises(SessionIsolationError):
                await enforcer.check_access("s1", "ctx-a")

        asyncio.run(_run())

    def test_bind_after_unbind_succeeds(self):
        async def _run():
            enforcer = SessionEnforcer()
            await enforcer.bind_session("s1", "ctx-a", browser=object())
            enforcer.unbind_session("s1")

            browser = object()
            binding = await enforcer.bind_session("s1", "ctx-b", browser=browser)
            assert binding.browser is browser
            assert binding.owner_context == "ctx-b"
            got = await enforcer.check_access("s1", "ctx-b")
            assert got is binding

        asyncio.run(_run())
