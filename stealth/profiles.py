"""
Persona + DeviceProfile foundation (P1 #109 + #88)

Minimal but solid dataclasses to centralize device/browser profile constants
(viewport, UA, locale, timezone, hardware) that were previously scattered
hardcodes in AgentBrowser.launch, headers, tls, behavior, etc.

This is the starting point for:
- Consistent persona-driven launch config
- Future per-account Persona instances with rotation policies
- Tighter integration with PlatformPreset (e.g. persona.recommended_preset)
- DeviceProfile can be extended for canvas seeds, fonts, etc.

Usage (foundation only):
    from stealth.profiles import Persona, DeviceProfile, DEFAULT_PERSONA, get_persona
    p = get_persona("default")
    overrides = p.to_launch_overrides()
    browser = AgentBrowser(persona=p)
    await browser.launch(persona=some_other)

Keep this file dependency-free (no Playwright, no internal cycles).
"""

from dataclasses import dataclass, field, asdict
import functools
from typing import Dict, Any, Optional


@dataclass(frozen=True)
class DeviceProfile:
    """Core device + browser environment profile for fingerprint consistency.

    Minimal solid set of attributes used by launch, stealth injection,
    and behavior simulation. Frozen for safety when passed around.
    """
    name: str = "win_chrome_124_desktop"
    viewport: Dict[str, int] = field(
        default_factory=lambda: {"width": 1366, "height": 768}
    )
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    locale: str = "en-US"
    timezone_id: str = "America/New_York"
    platform: str = "Win32"
    hardware_concurrency: int = 8
    device_memory: int = 8  # GB, for future navigator.deviceMemory spoof
    power_level: str = "medium"  # "low"|"medium"|"high" -> correlates hardware for #255

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def get_hardware_fingerprint(self) -> Dict[str, Any]:
        """Return hardware dict correlated to power_level (implements #255 correlation).
        Called from AgentBrowser for dynamic navigator.deviceMemory / hardwareConcurrency.
        """
        mapping = {
            "low": {"hardwareConcurrency": 4, "deviceMemory": 4},
            "medium": {"hardwareConcurrency": 8, "deviceMemory": 8},
            "high": {"hardwareConcurrency": 12, "deviceMemory": 16},
        }
        return mapping.get(getattr(self, "power_level", "medium"), mapping["medium"])

    @classmethod
    def default(cls) -> "DeviceProfile":
        return cls()


@dataclass
class Persona:
    """High-level user persona / identity.

    Wraps a DeviceProfile + persona-level overrides and metadata.
    This is the main object operators and higher layers will hold per session/account.
    """
    name: str
    device: DeviceProfile = field(default_factory=DeviceProfile.default)
    description: str = ""
    # Persona can override device-level locale/tz (e.g. traveler using US device in EU TZ)
    locale: Optional[str] = None
    timezone_id: Optional[str] = None
    notes: str = ""
    # Link to DX presets for convenience (foundation, not enforced yet)
    recommended_preset: Optional[str] = None

    def effective_locale(self) -> str:
        return self.locale or self.device.locale

    def effective_timezone(self) -> str:
        return self.timezone_id or self.device.timezone_id

    def to_launch_overrides(self) -> Dict[str, Any]:
        """Return the minimal dict consumed by AgentBrowser.launch and similar."""
        return {
            "viewport": self.device.viewport,
            "user_agent": self.device.user_agent,
            "locale": self.effective_locale(),
            "timezone_id": self.effective_timezone(),
            "device_profile_name": self.device.name,
        }

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # device already serialized via its to_dict in asdict for frozen? ensure
        if isinstance(self.device, DeviceProfile):
            d["device"] = self.device.to_dict()
        return d


# === Foundation default personas ===

DEFAULT_PERSONA = Persona(
    name="professional_us_desktop",
    device=DeviceProfile(
        name="win_chrome_124_desktop",
        viewport={"width": 1366, "height": 768},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="America/New_York",
        platform="Win32",
        hardware_concurrency=8,
        device_memory=8,
        power_level="medium",
    ),
    description="Baseline professional US desktop persona (2026 stealth default).",
    recommended_preset="linkedin_2026",
    notes="P1 foundation for #109/#88. Start here; specialize per account.",
)


US_PROFESSIONAL = DEFAULT_PERSONA  # alias for clarity

EU_PROFESSIONAL = Persona(
    name="professional_eu_desktop",
    device=DeviceProfile(
        name="win_chrome_124_eu",
        viewport={"width": 1366, "height": 768},
        user_agent=DEFAULT_PERSONA.device.user_agent,
        locale="en-GB",
        timezone_id="Europe/London",
        platform="Win32",
    ),
    description="European professional desktop (en-GB + London TZ).",
    recommended_preset="general",
    notes="Use for EU-facing work or GDPR-aware testing.",
)


# Registry for discovery (minimal)
PERSONAS: Dict[str, Persona] = {
    "default": DEFAULT_PERSONA,
    "us_professional": US_PROFESSIONAL,
    "eu_professional": EU_PROFESSIONAL,
    "professional_us_desktop": DEFAULT_PERSONA,
}


@functools.lru_cache(maxsize=64)
def get_persona(name: str = "default") -> Persona:
    """Lookup by short name / alias. Always returns a valid Persona (never None).
    Cached (P2 perf) for repeated lookups during fleet launches / device profile use.
    """
    if not name:
        return DEFAULT_PERSONA
    key = name.lower().strip().replace("-", "_").replace(" ", "_")
    return PERSONAS.get(key, DEFAULT_PERSONA)


def list_personas() -> list[str]:
    """Discoverable list for CLI / docs / MCP."""
    return sorted(PERSONAS.keys())


# For convenient re-export / DX
__all__ = [
    "DeviceProfile",
    "Persona",
    "DEFAULT_PERSONA",
    "US_PROFESSIONAL",
    "EU_PROFESSIONAL",
    "get_persona",
    "list_personas",
    "PERSONAS",
]
