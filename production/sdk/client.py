"""
SDK Client — workflow lifecycle API for programmatic use without MCP.

Usage:
    from production.sdk import StealthClient
    client = StealthClient()

    # Simple session
    async with StealthClient(session_name="mybot") as client:
        res = await client.navigate("https://example.com")
        data = await client.scrape("https://example.com/items")

    # Workflow execution
    client = StealthClient()
    await client.execute_workflow("linkedin/send-connection-request", variables={...})
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional


@dataclass
class ClientScrapeResult:
    title: str = ""
    url: str = ""
    text: str = ""
    links: List[Dict[str, str]] = field(default_factory=list)
    images: List[Dict[str, str]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ClientStatusResult:
    session_name: str
    current_url: str = ""
    healthy: bool = True
    session_uptime: float = 0.0
    metrics: Dict[str, Any] = field(default_factory=dict)


class WorkflowContext:
    """Scoped context manager for a stealth browser session."""

    def __init__(self, client: "StealthClient"):
        self._client = client

    async def __aenter__(self) -> "StealthClient":
        await self._client.launch()
        return self._client

    async def __aexit__(self, *args: Any) -> None:
        await self._client.close()


class StealthClient:
    """High-level SDK client for programmatic stealth browser automation.

    Provides a clean async API for session lifecycle, navigation, scraping,
    and workflow execution without MCP overhead.
    """

    def __init__(
        self,
        session_name: str = "default",
        headless: bool = True,
        anonymous: bool = True,
        ephemeral: bool = False,
        preset: Optional[str] = None,
        region: Optional[str] = None,
    ):
        self._session_name = session_name
        self._headless = headless
        self._anonymous = anonymous
        self._ephemeral = ephemeral
        self._preset = preset
        self._region = region
        self._browser: Any = None
        self._launched = False

    async def __aenter__(self) -> "StealthClient":
        await self.launch()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    def session(self) -> WorkflowContext:
        return WorkflowContext(self)

    async def _lazy_browser_cls(self) -> type:
        from core.agent_browser import AgentBrowser
        return AgentBrowser

    async def launch(self) -> Dict[str, Any]:
        if self._launched and self._browser is not None:
            return {"session_name": self._session_name, "launched": True, "status": "already_running"}
        cls = await self._lazy_browser_cls()
        self._browser = cls(
            session_name=self._session_name,
            anonymous=self._anonymous,
            ephemeral=self._ephemeral,
        )
        await self._browser.launch(
            headless=self._headless,
            preset=self._preset,
            region=self._region,
        )
        self._launched = True
        return {
            "session_name": self._session_name,
            "launched": True,
            "preset": getattr(self._browser, "current_preset", self._preset),
            "region": getattr(self._browser, "current_region", self._region),
        }

    async def navigate(
        self,
        url: str,
        platform: str = "unknown",
        warm_up: bool = True,
        rate_limit: bool = True,
        domain: Optional[str] = None,
        account: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self._launched:
            await self.launch()
        ok = await self._browser.safe_goto(
            str(url),
            warm_up=warm_up,
            platform=platform,
            rate_limit=rate_limit,
            domain=domain,
            account=account,
        )
        current_url = ""
        try:
            p = self._browser.page_getter()
            current_url = getattr(p, "url", "") if p else ""
        except Exception:
            pass
        return {
            "session_name": self._session_name,
            "url": str(url),
            "current_url": current_url,
            "platform": platform,
            "navigated": ok,
        }

    async def scrape(self, url: str, extract_images: bool = False, platform: str = "unknown") -> ClientScrapeResult:
        if not self._launched:
            await self.launch()
        scraper = getattr(self._browser, "scraper", None)
        if not scraper:
            return ClientScrapeResult(title="", url=str(url))
        raw = await scraper.scrape_page(str(url), extract_images=extract_images, platform=platform)
        return ClientScrapeResult(
            title=raw.get("title", ""),
            url=raw.get("url", str(url)),
            text=raw.get("text", ""),
            links=raw.get("links", []),
            images=raw.get("images", []),
            metadata=raw.get("metadata", {}),
        )

    async def status(self) -> ClientStatusResult:
        if not self._launched or self._browser is None:
            return ClientStatusResult(session_name=self._session_name, healthy=False)
        health = await self._browser.get_health_status()
        current_url = ""
        try:
            p = self._browser.page_getter()
            current_url = getattr(p, "url", "") if p else ""
        except Exception:
            pass
        return ClientStatusResult(
            session_name=self._session_name,
            current_url=current_url,
            healthy=health.get("healthy", True),
            session_uptime=health.get("uptime_seconds", 0),
            metrics=health,
        )

    async def load_cookies(self, cookies_path: str, encryption_key: Optional[Any] = None) -> Dict[str, Any]:
        if not self._launched:
            await self.launch()
        return await self._browser.load_cookies_from_file(str(cookies_path), encryption_key=encryption_key)

    async def set_region(self, region: str, relaunch: bool = False) -> Dict[str, Any]:
        if not self._launched:
            await self.launch()
        return await self._browser.switch_region(str(region), relaunch=relaunch)

    async def close(self) -> Dict[str, Any]:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        self._launched = False
        return {"session_name": self._session_name, "closed": True}

    async def execute_workflow(
        self,
        filename: str,
        variables: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self._launched:
            await self.launch()
        from workflows.player import WorkflowPlayer
        from workflows.schema import load_workflow

        library_root = Path("workflows/library")
        workflow_path = library_root / filename
        resolved = workflow_path.resolve()
        resolved_root = library_root.resolve()
        if resolved_root not in resolved.parents and resolved != resolved_root:
            return {"success": False, "error_message": "Path traversal not allowed", "filename": filename}

        if not resolved.exists():
            return {"success": False, "error_message": f"Workflow file not found: {filename}", "filename": filename}

        workflow = load_workflow(str(resolved))
        player = WorkflowPlayer(self._browser)
        result = await player.execute(workflow, runtime_vars=dict(variables or {}))

        return {
            "session_name": self._session_name,
            "filename": filename,
            "success": result.success,
            "steps_executed": result.steps_executed,
            "total_steps": result.total_steps,
            "failed_step": result.failed_step,
            "failed_step_type": result.failed_step_type,
            "error_message": result.error_message,
            "execution_time": result.execution_time,
            "summary": result.summary,
        }

    async def list_workflows(self, platform: Optional[str] = None, pattern: Optional[str] = None) -> List[Dict[str, Any]]:
        import fnmatch
        import time

        library_root = Path("workflows/library")
        search_root = library_root / platform if platform else library_root
        if not search_root.exists():
            return []

        results = []
        for yaml_file in sorted(search_root.rglob("*.yaml")):
            relative_path = str(yaml_file.relative_to(library_root))
            if pattern and not fnmatch.fnmatch(relative_path, pattern):
                continue
            parts = yaml_file.relative_to(library_root).parts
            platform_name = parts[0] if len(parts) > 1 else "root"
            try:
                stat = yaml_file.stat()
                results.append({
                    "name": yaml_file.stem,
                    "path": relative_path,
                    "platform": platform_name,
                    "size": stat.st_size,
                    "modified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
                })
            except Exception:
                results.append({"name": yaml_file.stem, "path": relative_path, "platform": platform_name, "size": 0, "modified_at": ""})
        return results
