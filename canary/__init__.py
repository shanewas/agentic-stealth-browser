"""asb-canary: continuous public detection score for Agentic Stealth Browser."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agentic-stealth-browser")
except PackageNotFoundError:
    __version__ = "unknown"