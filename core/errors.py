"""
Library-specific exception hierarchy for Agentic Stealth Browser (#249 DX improvement).
Extracted from core/agent_browser.py (ARC-07) — re-exported there for backward compat.
"""

from typing import Optional, Dict, Any


class StealthBrowserError(Exception):
    """Base exception for all Agentic Stealth Browser library errors (DX #249)."""

    pass


class LaunchError(StealthBrowserError):
    """Raised when browser launch or context creation fails (stealth, proxy, etc.)."""

    pass


class RecoveryError(StealthBrowserError):
    """Raised or catchable during anti-block recovery orchestration."""

    pass


class BlockDetectedError(StealthBrowserError):
    """Explicit signal that a block/challenge was detected (for user catch blocks)."""

    def __init__(
        self,
        block_type: Optional[str] = None,
        platform: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.block_type = block_type
        self.platform = platform
        self.details = details or {}
        msg = (
            f"Block detected: {block_type or 'unknown'} on {platform or 'unknown site'}"
        )
        super().__init__(msg)


class RateLimitError(StealthBrowserError):
    """Raised when rate limiter enforces a wait or limit (informational subclass)."""

    pass
