"""Basic validation test for Agentic Stealth Browser"""

import asyncio
from core.agent_browser import AgentBrowser


async def test_basic_launch():
    print("Testing basic launch...")
    browser = AgentBrowser(session_name="test-session", anonymous=True)
    await browser.launch(headless=True)
    print("✓ Browser launched successfully")
    
    await browser.close()
    print("✓ Browser closed cleanly")
    print("Basic test passed.")


if __name__ == "__main__":
    asyncio.run(test_basic_launch())
