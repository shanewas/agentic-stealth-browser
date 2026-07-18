import asyncio
import pytest
from core.agent_browser import AgentBrowser

pytestmark = [
    pytest.mark.perf,
    pytest.mark.e2e,
]  # e2e so the default CI (-m "not e2e") skips it; perf is the semantic label


async def test_concurrent_safe_goto_smoke():
    """N concurrent about:blank navigations must all complete without exception (headless)."""
    async with AgentBrowser(session_name="load-smoke") as b:
        await b.launch(headless=True)
        results = await asyncio.gather(
            *[b.safe_goto("about:blank") for _ in range(10)],
            return_exceptions=True,
        )
    exceptions = [r for r in results if isinstance(r, Exception)]
    assert not exceptions, f"concurrent safe_goto raised: {exceptions}"
