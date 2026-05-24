"""
Agentic Stealth Browser SDK — programmatic workflow lifecycle API.

Import and use the client for library-mode scripting:
    from production.sdk import StealthClient
    client = StealthClient()
    await client.launch()
    await client.navigate("https://example.com")
    result = await client.scrape("https://example.com")
"""

from production.sdk.client import StealthClient, WorkflowContext

__all__ = ["StealthClient", "WorkflowContext"]
