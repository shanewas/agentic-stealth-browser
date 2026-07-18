"""
REL-04: __aenter__ must clean up (stop the Playwright driver subprocess) when
launch() fails, instead of leaking self._pw / self.browser.
"""

import pytest

from core.agent_browser import AgentBrowser

pytestmark = pytest.mark.contract


async def test_aenter_launch_failure_calls_close(monkeypatch):
    close_calls = []

    async def failing_launch(self, *args, **kwargs):
        raise RuntimeError("boom")

    async def spy_close(self):
        close_calls.append(True)

    monkeypatch.setattr(AgentBrowser, "launch", failing_launch)
    monkeypatch.setattr(AgentBrowser, "close", spy_close)

    with pytest.raises(RuntimeError):
        async with AgentBrowser(session_name="leak-test") as b:
            pass

    assert close_calls == [True]
