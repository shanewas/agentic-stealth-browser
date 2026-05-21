"""
Platform Presets for Agentic Stealth Browser (DX Feature #288)

Provides recommended, battle-tested configurations for major platforms in 2026.
Especially tuned for LinkedIn's aggressive 2026 detection (unusual activity, security verifications).

Usage:
    from stealth.presets import get_preset, PlatformPreset, PRESETS
    preset = get_preset("linkedin_2026")
    # Then pass to AgentBrowser.launch(preset="linkedin_2026") or apply_preset(preset)

These are high-value DX improvements: one-liner for operators to get good defaults instead of guessing.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List
from enum import Enum

from stealth.tls_fingerprint import Region


@dataclass
class PlatformPreset:
    """Recommended settings bundle for a target platform."""
    name: str
    description: str
    tls_region: Region = Region.GLOBAL
    # Header overrides (merged with base realistic headers)
    recommended_headers_overrides: Dict[str, str] = field(default_factory=dict)
    # Behavior / human mimicry intensity for warm_up and interactions
    behavior_intensity: str = "medium"  # "light" | "medium" | "heavy"
    # Recovery tuning
    recovery_max_retries: int = 4
    recovery_base_backoff: int = 25
    # Warm-up recommendation before real work
    warm_up: str = "medium"  # "light" | "medium" | "heavy"
    # 2026-specific operational notes and gotchas
    notes: str = ""
    # Suggested additional stealth patches or future hooks (extensible)
    extra_patches: List[str] = field(default_factory=list)
    # Recommended locale/timezone for this persona
    locale: str = "en-US"
    timezone_id: str = "America/New_York"


# === 2026 High-Value Presets ===

LINKEDIN_2026 = PlatformPreset(
    name="linkedin_2026",
    description="Production-recommended settings for LinkedIn (2026). Conservative professional profile to minimize 'unusual activity' and security checkpoints.",
    tls_region=Region.US,
    behavior_intensity="heavy",
    warm_up="heavy",
    recovery_max_retries=6,
    recovery_base_backoff=45,
    locale="en-US",
    timezone_id="America/New_York",
    notes=(
        "CRITICAL for 2026 LinkedIn survival:\n"
        "1. ALWAYS load cookies exported from a real browser logged into the SAME account (use stealth_load_cookies).\n"
        "2. Run heavy warm_up (scroll + micro movements + idle) on linkedin.com/feed before profile visits.\n"
        "3. Never rapid-fire profile views — space with human.think(8-15s) + random idle.\n"
        "4. Use US East Coast TLS + locale for professional US personas. Rotate accounts every 20-30 actions.\n"
        "5. If 'unusual activity' appears, immediately trigger recovery with proxy/session rotation + 5+ min backoff.\n"
        "6. Viewport now persona-varied (e.g. 1920x1080 US / 1440x900 EU) + screen/DPR/orient spoof for #124 #198. Matches real desktop variety."
    ),
    extra_patches=["linkedin_safe_scroll", "conservative_mouse_jitter"]
)

AMAZON_2026 = PlatformPreset(
    name="amazon_2026",
    description="Recommended for Amazon product pages, reviews, and search (2026). Balanced stealth with CAPTCHA resilience.",
    tls_region=Region.US,
    behavior_intensity="medium",
    warm_up="medium",
    recovery_max_retries=5,
    recovery_base_backoff=30,
    locale="en-US",
    timezone_id="America/Los_Angeles",
    notes=(
        "Amazon is sensitive to timing anomalies and non-US locales on .com.\n"
        "Heavy warm_up helps; rotate residential proxies aggressively on 403/503.\n"
        "Consider Japan/EU presets for amazon.co.jp / amazon.de."
    )
)

UPWORK_2026 = PlatformPreset(
    name="upwork_2026",
    description="Settings for Upwork client/freelancer dashboards and proposals (2026). High-trust professional persona.",
    tls_region=Region.US,
    behavior_intensity="heavy",
    warm_up="heavy",
    recovery_max_retries=4,
    recovery_base_backoff=35,
    locale="en-US",
    timezone_id="America/New_York",
    notes=(
        "Upwork values consistency. Use the exact same persona (cookies + fingerprint) for weeks.\n"
        "Heavy warm_up + natural proposal reading simulation before sending messages.\n"
        "Load fresh cookies from your real Upwork browser profile."
    )
)

CLOUDFLARE_GENERIC = PlatformPreset(
    name="cloudflare_generic",
    description="Tuned for Cloudflare-protected sites (Turnstile, JS challenges, 2026 variants).",
    tls_region=Region.GLOBAL,
    behavior_intensity="medium",
    warm_up="light",
    recovery_max_retries=3,
    recovery_base_backoff=20,
    locale="en-US",
    timezone_id="UTC",
    notes="Cloudflare challenges are best beaten by clean TLS + no webdriver signals + realistic first navigation timing. Avoid headless indicators."
)

GENERAL_HIGH_STEALTH = PlatformPreset(
    name="general_high_stealth",
    description="Maximum stealth defaults for unknown or high-risk platforms. Good starting point.",
    tls_region=Region.GLOBAL,
    behavior_intensity="heavy",
    warm_up="heavy",
    recovery_max_retries=5,
    recovery_base_backoff=30,
    locale="en-US",
    timezone_id="America/New_York",
    notes="Use as baseline then specialize. Combine with region switching for geo-targeted sites (JP/KR/EU presets)."
)

# #277: minimal viable stealth light preset (speed-first)
LIGHT_STEALTH = PlatformPreset(
    name="light_stealth",
    description="Minimal viable stealth (light protection, speed-first preset). For CI, high volume, low resource. Light behavior + quick warm-ups.",
    tls_region=Region.GLOBAL,
    behavior_intensity="light",
    warm_up="light",
    recovery_max_retries=2,
    recovery_base_backoff=10,
    locale="en-US",
    timezone_id="UTC",
    notes="Speed over max stealth. Aliases: light, minimal, speed_first. Combine with STEALTH_REALISM=light.",
)

# Registry for easy lookup
PRESETS: Dict[str, PlatformPreset] = {
    "linkedin": LINKEDIN_2026,
    "linkedin_2026": LINKEDIN_2026,
    "li": LINKEDIN_2026,
    "amazon": AMAZON_2026,
    "amazon_2026": AMAZON_2026,
    "upwork": UPWORK_2026,
    "upwork_2026": UPWORK_2026,
    "cloudflare": CLOUDFLARE_GENERIC,
    "cf": CLOUDFLARE_GENERIC,
    "general": GENERAL_HIGH_STEALTH,
    "high_stealth": GENERAL_HIGH_STEALTH,
    "default": GENERAL_HIGH_STEALTH,
    # #277 light preset aliases
    "light": LIGHT_STEALTH,
    "light_stealth": LIGHT_STEALTH,
    "minimal": LIGHT_STEALTH,
    "speed_first": LIGHT_STEALTH,
}


def get_preset(name: str) -> PlatformPreset:
    """Get a PlatformPreset by short name or alias. Falls back to general high-stealth."""
    key = name.lower().strip()
    if key in PRESETS:
        return PRESETS[key]
    # Fuzzy match
    for k, p in PRESETS.items():
        if key in k or k in key:
            return p
    return PRESETS["default"]


def list_presets() -> List[str]:
    """Return all available preset names for discovery / CLI / docs."""
    return sorted(PRESETS.keys())


def get_linkedin_2026_preset() -> PlatformPreset:
    """Convenience for the #288 P1 target."""
    return LINKEDIN_2026


# Helper to merge preset into launch config (used by AgentBrowser)
def build_launch_config_from_preset(preset: PlatformPreset, base_headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Returns a dict of launch overrides derived from the preset (tls_region, headers, etc.)."""
    headers = dict(base_headers or {})
    headers.update(preset.recommended_headers_overrides)
    return {
        "tls_region": preset.tls_region.value,
        "extra_http_headers": headers,
        "locale": preset.locale,
        "timezone_id": preset.timezone_id,
        "behavior_intensity": preset.behavior_intensity,
        "warm_up": preset.warm_up,
        # recovery params applied at orchestrator or browser level
        "recovery_overrides": {
            "max_retries": preset.recovery_max_retries,
            "base_backoff": preset.recovery_base_backoff,
        },
        "notes": preset.notes,
    }


if __name__ == "__main__":
    print("Available presets:", list_presets())
    li = get_preset("linkedin_2026")
    print("LinkedIn 2026 TLS region:", li.tls_region.value)
    print("Notes excerpt:", li.notes[:100], "...")

# === Persona / DeviceProfile foundation (added for #109 + #88) ===
# Minimal solid start - co-located with PlatformPreset for smallest footprint.
# Future: can move to dedicated stealth/profiles.py once stable.

from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional


@dataclass(frozen=True)
class DeviceProfile:
    """Core device + browser environment profile (centralizes viewport, UA, locale, tz etc)."""
    name: str = "win_chrome_124_desktop"
    viewport: Dict[str, int] = field(default_factory=lambda: {"width": 1366, "height": 768})
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    locale: str = "en-US"
    timezone_id: str = "America/New_York"
    platform: str = "Win32"
    hardware_concurrency: int = 8
    device_memory: int = 8

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def default(cls) -> "DeviceProfile":
        return cls()


@dataclass
class Persona:
    """User persona foundation. Wraps DeviceProfile for AgentBrowser launch etc."""
    name: str
    device: DeviceProfile = field(default_factory=DeviceProfile.default)
    description: str = ""
    locale: Optional[str] = None
    timezone_id: Optional[str] = None
    notes: str = ""
    recommended_preset: Optional[str] = None

    def effective_locale(self) -> str:
        return self.locale or self.device.locale

    def effective_timezone(self) -> str:
        return self.timezone_id or self.device.timezone_id

    def to_launch_overrides(self) -> Dict[str, Any]:
        return {
            "viewport": self.device.viewport,
            "user_agent": self.device.user_agent,
            "locale": self.effective_locale(),
            "timezone_id": self.effective_timezone(),
        }


DEFAULT_PERSONA = Persona(name="professional_us_desktop", description="Baseline 2026 professional US desktop for P1 #109 foundation.")
PERSONAS = {"default": DEFAULT_PERSONA, "us_professional": DEFAULT_PERSONA}

def get_persona(name: str = "default") -> Persona:
    return PERSONAS.get(name.lower().strip().replace("-", "_"), DEFAULT_PERSONA)

def list_personas():
    return list(PERSONAS.keys())


__all__ = ["Persona", "DeviceProfile", "DEFAULT_PERSONA", "get_persona", "list_personas"]
