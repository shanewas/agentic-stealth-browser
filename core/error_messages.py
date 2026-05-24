"""
User-friendly error messages for Agentic Stealth Browser.
Addresses #141: Error messages from Playwright and internal failures are rarely user-friendly.

Provides:
- Human-readable error messages for common Playwright failures
- Actionable suggestions for each error type
- Structured error formatting with context
"""

import re
from typing import Optional, Dict, Any


# Common Playwright error patterns and their user-friendly explanations
PLAYWRIGHT_ERROR_PATTERNS = [
    {
        "pattern": r"Timeout\s+(\d+)ms exceeded",
        "friendly": "Operation timed out after {0}ms.",
        "suggestions": [
            "Increase the timeout parameter if the page is slow to load.",
            "Check if the URL is accessible and the server is responding.",
            "Try using wait_until='domcontentloaded' instead of 'load' for faster navigation.",
            "If running headless, try headed mode to visually debug the issue.",
        ],
    },
    {
        "pattern": r"Target page.*closed",
        "friendly": "The target page was closed before the operation could complete.",
        "suggestions": [
            "Ensure the page is not being closed by another process.",
            "Check if navigation triggered a page reload.",
            "Use page.wait_for_load_state() before interacting with the page.",
        ],
    },
    {
        "pattern": r"Element.*not found",
        "friendly": "The specified element could not be found on the page.",
        "suggestions": [
            "Verify the selector is correct and matches the current page DOM.",
            "The page may not have fully loaded — add a wait before selecting.",
            "Try using a more specific or alternative selector.",
            "Check if the element is inside an iframe or shadow DOM.",
        ],
    },
    {
        "pattern": r"Element.*detached from the DOM",
        "friendly": "The element was removed from the page before the action could complete.",
        "suggestions": [
            "The page may have reloaded or the element was dynamically removed.",
            "Re-query the element after waiting for the page to stabilize.",
            "Use page.wait_for_selector() before interacting.",
        ],
    },
    {
        "pattern": r"Element.*is not visible",
        "friendly": "The element exists but is not visible on the page.",
        "suggestions": [
            "Scroll to the element first using human.scroll_naturally().",
            "Check if the element is hidden behind another element.",
            "The element may be inside a collapsed menu or tab — expand it first.",
        ],
    },
    {
        "pattern": r"Element.*is not clickable",
        "friendly": "The element cannot be clicked at its current position.",
        "suggestions": [
            "Another element may be overlapping it — try scrolling first.",
            "Use human.human_click() instead of page.click() for natural interaction.",
            "Wait for any loading animations or overlays to disappear.",
        ],
    },
    {
        "pattern": r"Navigation.*failed",
        "friendly": "Navigation to the URL failed.",
        "suggestions": [
            "Verify the URL is correct and accessible.",
            "Check if the site is blocking automated access (use safe_goto with recovery).",
            "Try a different region or proxy if the site is geo-restricted.",
            "Ensure cookies are fresh if accessing a login-protected page.",
        ],
    },
    {
        "pattern": r"net::ERR_.*",
        "friendly": "Network error occurred: {0}",
        "suggestions": [
            "Check your internet connection.",
            "If using a proxy, verify the proxy configuration is correct.",
            "The site may be temporarily unavailable.",
            "Try again with a different proxy or after a short delay.",
        ],
    },
    {
        "pattern": r"Browser.*not launched",
        "friendly": "The browser has not been launched yet.",
        "suggestions": [
            "Call browser.launch() before performing any browser actions.",
            "Use 'async with AgentBrowser() as browser:' for automatic launch and cleanup.",
        ],
    },
    {
        "pattern": r"Access denied.*file access",
        "friendly": "File access was denied by the security policy.",
        "suggestions": [
            "The file path is outside the allowed directories.",
            "Add the directory to the allowed list using FileAccessPolicy.add_allowed_dir().",
            "Ensure the file is within ~/.agentic-browser or ~/.stealth-browser.",
        ],
    },
]


def make_user_friendly(
    error: str, context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Convert a raw error message into a user-friendly format with suggestions.

    Args:
        error: The raw error message.
        context: Optional context dict (e.g., url, selector, platform).

    Returns:
        Dict with 'friendly_message', 'suggestions', and 'raw_error'.
    """

    for pattern_info in PLAYWRIGHT_ERROR_PATTERNS:
        match = re.search(pattern_info["pattern"], error, re.IGNORECASE)
        if match:
            friendly = pattern_info["friendly"]
            # Format with match groups if present
            if match.groups():
                try:
                    friendly = friendly.format(*match.groups())
                except (IndexError, KeyError):
                    pass

            return {
                "friendly_message": friendly,
                "suggestions": pattern_info["suggestions"],
                "raw_error": error,
                "context": context or {},
            }

    # Fallback for unrecognized errors
    return {
        "friendly_message": f"An error occurred: {error[:100]}{'...' if len(error) > 100 else ''}",
        "suggestions": [
            "Check the raw error message for details.",
            "Ensure the browser is launched and the page is loaded.",
            "Try using safe_goto() instead of goto() for automatic recovery.",
            "Enable debug mode (launch(debug=True)) for more diagnostics.",
            "Check the audit logs for additional context.",
        ],
        "raw_error": error,
        "context": context or {},
    }


def format_error_for_display(error_info: Dict[str, Any]) -> str:
    """Format a user-friendly error for console display."""
    lines = [
        f"Error: {error_info['friendly_message']}",
        "",
        "Suggestions:",
    ]
    for i, suggestion in enumerate(error_info["suggestions"], 1):
        lines.append(f"  {i}. {suggestion}")

    if error_info.get("context"):
        lines.append("")
        lines.append("Context:")
        for key, value in error_info["context"].items():
            lines.append(f"  {key}: {value}")

    return "\n".join(lines)


class UserFriendlyError(Exception):
    """Exception that carries both raw and user-friendly error information."""

    def __init__(self, raw_error: str, context: Optional[Dict[str, Any]] = None):
        self.raw_error = raw_error
        self.context = context or {}
        self.error_info = make_user_friendly(raw_error, context)
        super().__init__(self.error_info["friendly_message"])

    def __str__(self) -> str:
        return format_error_for_display(self.error_info)

    def to_dict(self) -> Dict[str, Any]:
        """Return the full error info as a dict."""
        return self.error_info
