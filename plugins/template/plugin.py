"""
Example plugin for the Agentic Stealth Browser plugin ecosystem.

To create a plugin:
1. Copy this directory to plugins/<your_plugin_name>/
2. Extend BasePlugin with your custom hooks
3. Register your plugin in production settings or at runtime

Each plugin receives a PluginContext with access to the browser session,
logger, and shared configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class PluginContext:
    """Context injected into every plugin hook.

    Plugins read from `context.session` to inspect browser state
    and `context.logger` to emit structured logs.
    """

    session: Optional[Any] = None
    logger: Any = None
    config: Dict[str, Any] = field(default_factory=dict)


class BasePlugin:
    """Base class for all plugins.

    Override the hooks you need. Each hook receives a PluginContext.
    Return values are plugin-specific and composable upstream.

    Hook lifecycle:
        on_launch          -> after browser launch
        on_navigate(url)   -> before page navigation
        on_page_loaded(url) -> after page load complete
        on_scraped(data)   -> after scrape result is available
        on_close           -> before browser shutdown
    """

    name: str = "base"
    version: str = "0.1.0"

    async def on_launch(self, ctx: PluginContext) -> None:
        pass

    async def on_navigate(self, ctx: PluginContext, url: str) -> None:
        pass

    async def on_page_loaded(self, ctx: PluginContext, url: str) -> None:
        pass

    async def on_scraped(
        self, ctx: PluginContext, data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        return None

    async def on_close(self, ctx: PluginContext) -> None:
        pass


class ExamplePlugin(BasePlugin):
    """A concrete example plugin that logs navigation events."""

    name = "example"
    version = "0.1.0"

    async def on_launch(self, ctx: PluginContext) -> None:
        if ctx.logger:
            ctx.logger.info(
                f"[{self.name}] Browser launched (session={getattr(ctx.session, 'session_name', '?')})"
            )

    async def on_navigate(self, ctx: PluginContext, url: str) -> None:
        if ctx.logger:
            ctx.logger.info(f"[{self.name}] Navigating to {url}")

    async def on_page_loaded(self, ctx: PluginContext, url: str) -> None:
        if ctx.logger:
            ctx.logger.info(f"[{self.name}] Page loaded: {url}")
