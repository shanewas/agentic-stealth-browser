"""
Firefox adapter (feature-flagged stub).

When STEALTH_FIREFOX_SUPPORT=true, this module provides a minimal
Firefox-compatible stealth injection and browser bridge.

Currently a stub awaiting full Gecko CDP integration.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


FIREFOX_STEALTH_SCRIPT = """
// Firefox stealth injection stub (Gecko-compatible)
(function() {
    // Placeholder for WebDriver / Marionette hiding
    if (navigator.webdriver) {
        Object.defineProperty(navigator, 'webdriver', {get: () => false});
    }
    // Suppress Firefox-specific automation flags
    if (typeof InstallTrigger !== 'undefined') {
        delete window.InstallTrigger;
    }
})();
"""


def get_firefox_stealth_script() -> str:
    """Return Firefox-compatible stealth patching script."""
    return FIREFOX_STEALTH_SCRIPT


def get_firefox_launch_args(region: str = "global", headless: bool = True) -> list:
    """Return Firefox-specific launch arguments."""
    args = []
    if headless:
        args.append("--headless")
    # Firefox uses about:config preferences, not Chromium-style CLI flags.
    # Stealth is achieved via firefox_user_prefs in Playwright launch options.
    return args


def get_firefox_headers() -> Dict[str, str]:
    """Return Firefox-specific HTTP header overrides."""
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
            "Gecko/20100101 Firefox/125.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }


class FirefoxAdapter:
    """Minimal Firefox adapter for feature-flagged support.

    When FIREFOX_SUPPORT=true, this adapter provides:
      - Basic navigation via Playwright Firefox channel
      - Firefox-specific stealth script injection
      - Reduced capability set (no full Chromium stealth)

    Usage (feature-flagged):
        from core.feature_flags import is_firefox_supported
        if is_firefox_supported():
            from stealth.firefox_adapter import FirefoxAdapter
            adapter = FirefoxAdapter()
    """

    def __init__(self):
        self._launched = False
        self._stealth_script = get_firefox_stealth_script()
        self._headers = get_firefox_headers()

    async def launch(self, headless: bool = True) -> Dict[str, Any]:
        self._launched = True
        return {
            "status": "stub",
            "browser": "firefox",
            "headless": headless,
            "message": "Firefox adapter is a stub. Full support is under development.",
            "stealth_script_ready": bool(self._stealth_script),
        }

    async def navigate(self, url: str) -> Dict[str, Any]:
        return {
            "status": "stub",
            "url": url,
            "message": "Navigation not yet implemented for Firefox adapter.",
        }

    async def close(self) -> Dict[str, Any]:
        self._launched = False
        return {"status": "closed", "browser": "firefox"}
