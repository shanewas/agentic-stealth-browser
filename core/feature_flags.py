"""
Feature flag / platform-capability system for Agentic Stealth Browser.

Centralizes browser/backend capability checks and feature toggles.
Use `get_client_capabilities()` for dynamic availability queries.

Usage:
    from core.feature_flags import get_client_capabilities, is_firefox_supported
"""

from __future__ import annotations

import os
from typing import Any, Dict


_ENV_PREFIX = "STEALTH_"


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(f"{_ENV_PREFIX}{name}")
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "enabled")


def is_firefox_supported() -> bool:
    return _env_flag("FIREFOX_SUPPORT", default=False)


def is_edge_supported() -> bool:
    return _env_flag("EDGE_SUPPORT", default=True)


def is_adaptive_tuning_enabled() -> bool:
    return _env_flag("ADAPTIVE_TUNING", default=True)


def is_plugin_system_enabled() -> bool:
    return _env_flag("PLUGIN_SYSTEM", default=True)


def is_pooled_contexts_enabled() -> bool:
    return _env_flag("POOLED_CONTEXTS", default=True)


def is_workflow_replay_enabled() -> bool:
    return _env_flag("WORKFLOW_REPLAY", default=True)


def is_learning_loop_enabled() -> bool:
    return _env_flag("LEARNING_LOOP", default=False)


def get_browser_backend() -> str:
    """Return the active browser backend identifier."""
    backend = os.getenv("STEALTH_BROWSER_BACKEND", "").lower()
    if backend in ("chromium", "chrome", "edge", "firefox", "gecko"):
        return backend
    if is_firefox_supported() and backend == "firefox":
        return "firefox"
    return "chromium"


def get_client_capabilities(browser_backend: str = "") -> Dict[str, Any]:
    """Return a capabilities map for the current browser/backend.

    Each key maps to a boolean indicating whether the feature is available.
    Unsupported features produce actionable error messages when attempted.
    """
    backend = browser_backend or get_browser_backend()
    is_chromium = backend in ("chromium", "chrome", "edge")

    caps: Dict[str, Any] = {
        "browser_backend": backend,
        "stealth_injection": is_chromium or is_firefox_supported(),
        "tls_spoofing": is_chromium,
        "human_behavior": True,
        "anti_block_recovery": is_chromium,
        "workflow_support": is_chromium and is_workflow_replay_enabled(),
        "cookie_persistence": True,
        "proxy_rotation": True,
        "pooled_contexts": is_chromium and is_pooled_contexts_enabled(),
        "cdp_debug": is_chromium,
        "adaptive_tuning": is_adaptive_tuning_enabled(),
        "plugin_system": is_plugin_system_enabled(),
        "learning_loop": is_learning_loop_enabled(),
        "firefox_support": is_firefox_supported(),
        "edge_support": is_edge_supported() and is_chromium,
    }
    return caps


def unsupported_feature_message(feature: str, reason: str = "not available for this backend") -> str:
    """Produce an actionable error message when a feature is not supported."""
    caps = get_client_capabilities()
    backend = caps.get("browser_backend", "unknown")
    return (
        f"Feature '{feature}' is not supported: {reason}. "
        f"(browser_backend={backend}, firefox_support={caps.get('firefox_support')})"
    )
