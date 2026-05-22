"""
Type stubs for Agentic Stealth Browser public API.
Addresses #165: No typed public API surface — everything is dynamic.

This module provides type hints for the main public interfaces.
Import from here for IDE autocomplete and type checking:

    from core.types import AgentBrowser, Persona, DeviceProfile
    from core.types import StealthBrowserError, LaunchError, BlockDetectedError
"""

from typing import (
    Optional,
    Dict,
    Any,
    List,
    Literal,
    TypedDict,
    Protocol,
    runtime_checkable,
)

# Re-export main classes for convenience
from proxy.proxy_manager import ProxyTier


# === TypedDicts for return types ===

class SessionDict(TypedDict, total=False):
    """Type hint for session metadata dict."""
    name: str
    created_at: str
    anonymous: bool
    ephemeral: bool
    user_data_dir: str
    cookies_file: str
    state_file: str
    compromised: bool
    cleaned_at: str
    cleanup_reason: str
    cloned_from: str
    cloned_at: str


class CookieHealthDict(TypedDict, total=False):
    """Type hint for cookie health check result."""
    status: str
    message: str
    count: int
    oldest_cookie_age_hours: float
    expired_count: int


class HealthStatusDict(TypedDict, total=False):
    """Type hint for get_health_status() return value."""
    status: str
    launched: bool
    current_url: str
    preset: Optional[str]
    region: str
    tls_profile: Dict[str, Any]
    proxy: Dict[str, Any]
    cookies: CookieHealthDict
    recovery: Dict[str, Any]
    block_rate_pct: float
    account_state: str
    debug_mode: bool
    metrics_sample: Dict[str, Any]
    stealth_score: Dict[str, Any]
    replay_preview: Dict[str, Any]
    timestamp: float


class WarmUpResultDict(TypedDict, total=False):
    """Type hint for warm_up_before_work() return value."""
    status: Literal["success", "partial", "degraded", "error"]
    intensity: str
    steps_attempted: int
    steps_succeeded: int
    errors: List[str]
    message: str


class StealthScoreDict(TypedDict, total=False):
    """Type hint for get_stealth_score() return value."""
    config_hint: int
    detectability_risk_pct: int
    note: str
    advice: str


class ProxyInfoDict(TypedDict, total=False):
    """Type hint for proxy information."""
    configured: bool
    provider: str
    host: str
    port: int
    country: str
    session_name: Optional[str]
    duration_minutes: int
    tier: ProxyTier
    history_length: int


class RecoveryResultDict(TypedDict, total=False):
    """Type hint for recovery-related results."""
    status: str
    action: str
    block_type: str
    platform: str
    attempt: int
    backoff_seconds: float


# === Protocols for duck typing ===

@runtime_checkable
class PageLike(Protocol):
    """Protocol for Playwright Page-like objects."""
    async def goto(self, url: str, **kwargs: Any) -> Any: ...
    async def content(self) -> str: ...
    async def inner_text(self, selector: str) -> str: ...
    async def click(self, selector: str, **kwargs: Any) -> None: ...
    async def fill(self, selector: str, value: str, **kwargs: Any) -> None: ...
    async def screenshot(self, **kwargs: Any) -> bytes: ...
    @property
    def url(self) -> str: ...


@runtime_checkable
class BrowserContextLike(Protocol):
    """Protocol for Playwright BrowserContext-like objects."""
    async def new_page(self) -> PageLike: ...
    async def close(self) -> None: ...
    async def clear_cookies(self) -> None: ...
    async def add_init_script(self, script: str) -> None: ...
    @property
    def pages(self) -> List[PageLike]: ...


# === Aliases for common types ===

IntensityLevel = Literal["light", "medium", "heavy"]
ExtractType = Literal["text", "html", "title"]
RegionName = Literal["us", "eu", "japan", "korea", "global"]
PresetName = str  # Dynamic, but common values: "linkedin_2026", "amazon_2026", "upwork_2026"
