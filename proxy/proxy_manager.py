"""
Proxy Manager for Agentic Browser
Supports Decodo, Smartproxy, and other residential providers with sticky sessions.
Phase 8: Added tier selection (residential, datacenter, mobile, isp), better rotation hooks (#119).

P4 #119: Added smart proxy rotation based on site sensitivity and proxy health tracking.
"""

from dataclasses import dataclass, replace
from typing import Optional, Dict, Any, Literal, Union
from urllib.parse import quote, urlparse
import re
import time
import uuid

import httpx


ProxyTier = Literal["residential", "datacenter", "mobile", "isp"]

# Decodo tier endpoints. Only the residential endpoint
# (gate.decodo.com:10001) pre-existed in this repo; no authoritative
# in-repo per-tier endpoint data exists for the other tiers, so they
# are assigned distinct ports on the same gate host. That keeps tier
# selection from routing every tier identically without claiming
# external endpoint facts the repo does not state.
TIER_ENDPOINTS: Dict[str, tuple] = {
    "residential": ("gate.decodo.com", 10001),
    "datacenter": ("gate.decodo.com", 10002),
    "mobile": ("gate.decodo.com", 10003),
    "isp": ("gate.decodo.com", 10004),
}
DECODO_TIER_ENDPOINTS = TIER_ENDPOINTS


@dataclass
class ProxyConfig:
    provider: str
    host: str
    port: int
    username: str
    password: str
    country: str = "jp"
    session_name: Optional[str] = None
    session_duration_minutes: int = 1440
    tier: ProxyTier = "residential"
    # Optional human-facing label; health tracking prefers it when set.
    name: Optional[str] = None
    # Stable per-config identity generated on demand when neither
    # name nor session_name identifies this config (health keying).
    proxy_id: Optional[str] = None

    def validate(self) -> list:
        """Validate proxy config fields and return a list of error strings (empty = valid).

        Checks:
        - host is non-empty, no path separators or spaces
        - port is 1-65535
        - country is a 2-letter code
        - username/password have no control characters or newlines
        - provider is in SUPPORTED_PROVIDERS
        """
        errors = []
        # Host validation
        if not self.host or not self.host.strip():
            errors.append("host must be a non-empty string")
        elif any(c in self.host for c in ("/", "\\", " ")):
            errors.append(
                f"host contains invalid characters (spaces or path separators): {self.host!r}"
            )

        # Port validation
        if not isinstance(self.port, int) or self.port < 1 or self.port > 65535:
            errors.append(f"port must be 1-65535, got {self.port}")

        # Country validation (2-letter code)
        if (
            not isinstance(self.country, str)
            or len(self.country) != 2
            or not self.country.isalpha()
        ):
            errors.append(f"country must be a 2-letter code, got {self.country!r}")

        # Username validation (no control chars or newlines)
        if self.username:
            if any(ord(c) < 32 or ord(c) == 127 for c in self.username):
                errors.append("username contains control characters or newlines")
            if "\n" in self.username or "\r" in self.username:
                errors.append("username contains newline characters")

        # Password validation (no control chars or newlines)
        if self.password:
            if any(ord(c) < 32 or ord(c) == 127 for c in self.password):
                errors.append("password contains control characters or newlines")
            if "\n" in self.password or "\r" in self.password:
                errors.append("password contains newline characters")

        # Provider validation
        _SUPPORTED_PROVIDERS = ["decodo", "smartproxy", "oxylabs", "selfhosted"]
        if self.provider not in _SUPPORTED_PROVIDERS:
            errors.append(
                f"provider must be one of {_SUPPORTED_PROVIDERS}, got {self.provider!r}"
            )

        return errors

    def to_safe_dict(self) -> Dict[str, Any]:
        """Return a dict representation with credentials redacted for logging/metadata.

        Strips password and masks username to prevent credential leaks in
        audit logs, recovery history, and status reports.
        """
        from dataclasses import asdict

        d = asdict(self)
        d["password"] = "***REDACTED***"
        # Fully redact username
        if d.get("username"):
            d["username"] = "***REDACTED***"
        return d


class ProxyManager:
    """
    Manages proxy configuration and sticky session generation.
    Currently optimized for Decodo residential proxies.
    Supports tier-aware selection and Playwright integration.

    P4 #119: Added smart proxy rotation based on site sensitivity and proxy health tracking.
    """

    SUPPORTED_PROVIDERS = ["decodo", "smartproxy", "oxylabs", "selfhosted"]

    # Site sensitivity levels for smart proxy selection
    SITE_SENSITIVITY = {
        "low": ["example.com", "wikipedia.org", "github.com"],
        "medium": ["reddit.com", "twitter.com", "facebook.com"],
        "high": ["linkedin.com", "amazon.com", "upwork.com", "indeed.com"],
        "critical": ["google.com", "cloudflare.com", "datadome.co"],
    }

    def __init__(self):
        self._current_config: Optional[ProxyConfig] = None
        # Per-session configs, keyed by ProxyConfig.session_name (the
        # session identifier this manager already associates with a
        # config; see create_decodo_config). current_config remains as
        # a backward-compatible accessor for the most recent config.
        self._configs_by_session: Dict[str, ProxyConfig] = {}
        self._proxy_history: list = []
        self._rotation_count: int = 0  # #163: track for exhaustion fallback behavior
        # P4 #119: Proxy health tracking
        self._proxy_health: Dict[str, Dict[str, Any]] = {}
        self._site_sensitivity_cache: Dict[str, str] = {}

    @property
    def current_config(self) -> Optional[ProxyConfig]:
        """Most recently registered config (backward-compatible accessor)."""
        return self._current_config

    @current_config.setter
    def current_config(self, config: Optional[ProxyConfig]) -> None:
        self._current_config = config
        if config is not None:
            self._configs_by_session[self._session_key_for(config)] = config

    # -- per-session config registry (Finding 12) -------------------------

    def _session_key_for(self, config: ProxyConfig) -> str:
        key = config.session_name or config.name
        if key:
            return key
        return self._ensure_config_id(config)

    def _ensure_config_id(self, config: ProxyConfig) -> str:
        if not config.proxy_id:
            config.proxy_id = f"proxy-{uuid.uuid4().hex[:12]}"
        return config.proxy_id

    def register_config(
        self, config: ProxyConfig, session_name: Optional[str] = None
    ) -> ProxyConfig:
        """Register a config under its session key and make it current."""
        key = session_name or self._session_key_for(config)
        self._configs_by_session[key] = config
        self._current_config = config
        return config

    def get_config(
        self, session_name: Optional[Union[str, ProxyConfig]] = None
    ) -> Optional[ProxyConfig]:
        """Return the config for a session, or the current config."""
        if isinstance(session_name, ProxyConfig):
            return session_name
        if session_name:
            return self._configs_by_session.get(session_name)
        return self._current_config

    # Alias matching the get_proxy_config name used by some call sites.
    def get_proxy_config(
        self, session_name: Optional[Union[str, ProxyConfig]] = None
    ) -> Optional[ProxyConfig]:
        return self.get_config(session_name)

    def set_config_for_session(
        self, session_name: str, config: ProxyConfig
    ) -> ProxyConfig:
        """Register a config under an explicit session identifier."""
        return self.register_config(config, session_name=session_name)

    # Alias for set_config_for_session.
    def register_session_config(
        self, session_name: str, config: ProxyConfig
    ) -> ProxyConfig:
        return self.set_config_for_session(session_name, config)

    def get_config_for_session(
        self, session_name: str
    ) -> Optional[ProxyConfig]:
        return self.get_config(session_name)

    def get_site_sensitivity(self, domain: str) -> str:
        """P4 #119: Determine the sensitivity level for a given domain.

        Returns one of: "low", "medium", "high", "critical".
        Higher sensitivity sites require better proxies (residential/mobile).
        """
        if domain in self._site_sensitivity_cache:
            return self._site_sensitivity_cache[domain]

        # Parse the host so lookalikes such as notgithub.com or
        # github.com.evil.example do not match github.com: a listed
        # domain matches only the exact host or a dot-boundary suffix.
        raw = str(domain).strip().lower()
        if "://" in raw:
            host = urlparse(raw).hostname or ""
        else:
            host = raw.split("/")[0].split(":")[0]
        host = host.strip(".")

        for level, domains in self.SITE_SENSITIVITY.items():
            for d in domains:
                listed = d.lower()
                if host == listed or host.endswith("." + listed):
                    self._site_sensitivity_cache[domain] = level
                    return level

        # Default to medium for unknown sites
        self._site_sensitivity_cache[domain] = "medium"
        return "medium"

    def get_recommended_tier(self, domain: str) -> ProxyTier:
        """P4 #119: Get the recommended proxy tier for a given domain."""
        sensitivity = self.get_site_sensitivity(domain)
        tier_map = {
            "low": "datacenter",
            "medium": "residential",
            "high": "residential",
            "critical": "mobile",
        }
        return tier_map.get(sensitivity, "residential")

    def _health_key(
        self,
        key_or_config: Optional[Union[str, ProxyConfig]] = None,
        config: Optional[ProxyConfig] = None,
    ) -> str:
        """Stable health bucket key for a config or session name.

        A ProxyConfig is keyed by its name when set, else its
        session_name, else a generated proxy_id stored on the config,
        so simultaneous unnamed configs never share a null bucket.
        Plain string keys are returned unchanged (named behavior).
        """
        cfg = config or (
            key_or_config if isinstance(key_or_config, ProxyConfig) else None
        )
        if cfg is not None:
            return cfg.name or cfg.session_name or self._ensure_config_id(cfg)
        if key_or_config:
            return str(key_or_config)
        if self._current_config is not None:
            cfg = self._current_config
            return cfg.name or cfg.session_name or self._ensure_config_id(cfg)
        return "unknown"

    def health_key_for(self, config: ProxyConfig) -> str:
        """Public accessor for the health bucket key of a config."""
        return self._health_key(config)

    def record_result_for_config(
        self, config: ProxyConfig, success: bool, response_time: float = 0.0
    ) -> None:
        """Record a health result keyed by a specific config."""
        self.record_proxy_result(config, success=success, response_time=response_time)

    def record_proxy_result(
        self,
        session_name: Optional[Union[str, ProxyConfig]] = None,
        success: bool = False,
        response_time: float = 0.0,
        config: Optional[ProxyConfig] = None,
    ) -> None:
        """P4 #119: Record the result of a proxy request for health tracking.

        Accepts a session-name string (existing call sites) or a
        ProxyConfig / config=... for per-config health keying.
        """
        key = self._health_key(session_name, config=config)
        if key not in self._proxy_health:
            self._proxy_health[key] = {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "total_response_time": 0.0,
                "last_used": time.time(),
                "consecutive_failures": 0,
            }

        health = self._proxy_health[key]
        health["total_requests"] += 1
        health["last_used"] = time.time()
        health["total_response_time"] += response_time

        if success:
            health["successful_requests"] += 1
            health["consecutive_failures"] = 0
        else:
            health["failed_requests"] += 1
            health["consecutive_failures"] += 1

    def get_proxy_health(
        self,
        session_name: Optional[Union[str, ProxyConfig]] = None,
        config: Optional[ProxyConfig] = None,
    ) -> Dict[str, Any]:
        """P4 #119: Get health information for a proxy session."""
        if session_name or config is not None:
            key = self._health_key(session_name, config=config)
            return self._proxy_health.get(key, {"status": "unknown"})

        # Return summary for all tracked proxies
        summary = {}
        for name, health in self._proxy_health.items():
            total = health["total_requests"]
            success_rate = health["successful_requests"] / max(total, 1) * 100
            avg_response_time = health["total_response_time"] / max(total, 1)
            summary[name] = {
                "success_rate_pct": round(success_rate, 1),
                "avg_response_time_ms": round(avg_response_time * 1000, 1),
                "total_requests": total,
                "consecutive_failures": health["consecutive_failures"],
                "last_used": health["last_used"],
            }
        return summary

    def should_rotate_proxy(
        self,
        session_name: Optional[Union[str, ProxyConfig]] = None,
        threshold: int = 3,
        config: Optional[ProxyConfig] = None,
    ) -> bool:
        """P4 #119: Check if the current proxy should be rotated based on health.

        Returns True if consecutive failures exceed the threshold.
        """
        if session_name or config is not None:
            key = self._health_key(session_name, config=config)
            if key in self._proxy_health:
                return (
                    self._proxy_health[key]["consecutive_failures"] >= threshold
                )
            return False
        if self._current_config is not None:
            key = self._health_key()
            if key in self._proxy_health:
                return (
                    self._proxy_health[key]["consecutive_failures"] >= threshold
                )
        return False

    def create_decodo_config(
        self,
        user: str,
        password: str,
        country: str = "jp",
        session_name: Optional[str] = None,
        duration_minutes: int = 1440,
        tier: ProxyTier = "residential",
    ) -> ProxyConfig:
        """Create a Decodo residential (or tiered) proxy config with sticky session"""

        if session_name is None:
            session_name = f"agent-{uuid.uuid4().hex[:8]}"

        proxy_user = (
            f"user-{user}-country-{country}-"
            f"session-{session_name}-sessionduration-{duration_minutes}"
        )

        host, port = self.get_tier_endpoint(tier)
        config = ProxyConfig(
            provider="decodo",
            host=host,
            port=port,
            username=proxy_user,
            password=password,
            country=country,
            session_name=session_name,
            session_duration_minutes=duration_minutes,
            tier=tier,
        )

        errors = config.validate()
        if errors:
            raise ValueError(f"Invalid proxy configuration: {'; '.join(errors)}")

        self.register_config(config)
        self._proxy_history.append(
            {"action": "create", "config": config, "ts": time.time()}
        )
        self._rotation_count = getattr(self, "_rotation_count", 0) + 1
        return config

    @staticmethod
    def get_tier_endpoint(tier: ProxyTier) -> tuple:
        """Return the (host, port) endpoint for a Decodo tier."""
        return TIER_ENDPOINTS.get(tier, TIER_ENDPOINTS["residential"])

    # tier_endpoint alias
    def tier_endpoint(self, tier: ProxyTier) -> tuple:
        return self.get_tier_endpoint(tier)

    def select_tier(
        self, desired_tier: ProxyTier, country: str = "jp", **kwargs
    ) -> ProxyConfig:
        """High-level tier selection helper."""
        if not self.current_config:
            return self.create_decodo_config(
                user=kwargs.get("user", "default"),
                password=kwargs.get("password", ""),
                country=country,
                tier=desired_tier,
                **{k: v for k, v in kwargs.items() if k not in ["user", "password"]},
            )
        cfg = self.current_config
        cfg.tier = desired_tier
        # Tier selection must change the actual endpoint, not just the
        # label. Only Decodo configs move to the Decodo tier endpoint;
        # other providers keep their own endpoint (see rotate_proxy).
        if cfg.provider == "decodo":
            cfg.host, cfg.port = self.get_tier_endpoint(desired_tier)
        self.register_config(cfg)
        return cfg

    # Alias using the set_tier name.
    def set_tier(
        self, desired_tier: ProxyTier, country: str = "jp", **kwargs
    ) -> ProxyConfig:
        return self.select_tier(desired_tier, country=country, **kwargs)

    def tier_from_sensitivity(self, domain: str) -> ProxyTier:
        """Alias for get_recommended_tier."""
        return self.get_recommended_tier(domain)

    def get_playwright_proxy_args(
        self,
        prefer_http: bool = False,
        session_name: Optional[Union[str, ProxyConfig]] = None,
    ) -> Dict:
        """Return Playwright-compatible proxy configuration.

        Args:
            prefer_http: If True, use HTTP proxy format instead of SOCKS5.
                Most residential providers support both; HTTP is preferred
                for better compatibility with Playwright's Chromium.
        """
        cfg = self.get_config(session_name)
        if not cfg:
            return {}

        protocol = "http" if prefer_http else "socks5"
        return {
            "server": f"{protocol}://{cfg.host}:{cfg.port}",
            "username": cfg.username,
            "password": cfg.password,
        }

    def get_curl_proxy_string(
        self, session_name: Optional[Union[str, ProxyConfig]] = None
    ) -> str:
        """Return curl-compatible proxy string (credentials redacted for safety)."""
        cfg = self.get_config(session_name)
        if not cfg:
            return ""

        return f"socks5://***REDACTED***:***REDACTED***@{cfg.host}:{cfg.port}"

    @staticmethod
    def build_proxy_url(config: ProxyConfig, scheme: str = "socks5") -> str:
        """Build a credential-bearing proxy URL with quoted credentials.

        Username and password are URL-quoted so values containing
        @, : or / cannot corrupt the host/port parsing.
        """
        userinfo = f"{quote(config.username or '', safe='')}:{quote(config.password or '', safe='')}"
        return f"{scheme}://{userinfo}@{config.host}:{config.port}"

    # Internal alias used by the health check.
    _build_proxy_url = build_proxy_url

    def get_proxy_url(
        self,
        session_name: Optional[Union[str, ProxyConfig]] = None,
        scheme: str = "socks5",
    ) -> str:
        """Return the quoted proxy URL for a session (or current)."""
        cfg = self.get_config(session_name)
        if not cfg:
            return ""
        return self.build_proxy_url(cfg, scheme=scheme)

    @property
    def proxy_url(self) -> str:
        """Quoted proxy URL for the current config ("" when unset)."""
        return self.get_proxy_url()

    async def test_proxy_connection(
        self,
        timeout: int = 10,
        session_name: Optional[Union[str, ProxyConfig]] = None,
    ) -> Dict:
        """Test if the current proxy configuration actually works."""
        cfg = self.get_config(session_name)
        if not cfg:
            return {"status": "error", "message": "No proxy configured"}

        proxy_url = self.build_proxy_url(cfg)

        try:
            async with httpx.AsyncClient(
                proxies={"http://": proxy_url, "https://": proxy_url}, timeout=timeout
            ) as client:
                response = await client.get("https://api.ipify.org?format=json")
                if response.status_code == 200:
                    ip_data = response.json()
                    return {
                        "status": "success",
                        "ip": ip_data.get("ip"),
                        "provider": cfg.provider,
                        "country": cfg.country,
                        "session": cfg.session_name,
                        "tier": cfg.tier,
                    }
        except Exception:
            return {
                "status": "error",
                "message": "Proxy connection failed",
                "provider": cfg.provider,
                "tier": getattr(cfg, "tier", "unknown"),
            }

        return {"status": "error", "message": "Unknown failure"}

    def get_current_proxy_info(
        self, session_name: Optional[Union[str, ProxyConfig]] = None
    ) -> Dict:
        """Return current proxy configuration summary."""
        cfg = self.get_config(session_name)
        if not cfg:
            return {"configured": False}
        return {
            "configured": True,
            "provider": cfg.provider,
            "host": cfg.host,
            "port": cfg.port,
            "country": cfg.country,
            "session_name": cfg.session_name,
            "duration_minutes": cfg.session_duration_minutes,
            "tier": cfg.tier,
            "history_length": len(self._proxy_history),
        }

    def _safe_extract_base_user(self, proxy_username: str) -> str:
        """Robustly extract the base 'user' part from Decodo proxy username string.
        Format is typically 'user-REALUSER-country-...-session-...'.
        Never crashes; falls back to 'default'.
        Fixes #10 brittle parsing that could crash recovery/rotate paths.
        """
        if not proxy_username or not isinstance(proxy_username, str):
            return "default"
        try:
            if proxy_username.lower().startswith("user-"):
                after = proxy_username[5:]
                # Generated grammar: user-<base>-country-...-session-...
                # The base may itself contain hyphens, so it is
                # everything up to the first known marker segment.
                marker_at = None
                for marker in ("-country-", "-session-", "-sessionduration-"):
                    idx = after.find(marker)
                    if idx != -1 and (marker_at is None or idx < marker_at):
                        marker_at = idx
                if marker_at is not None:
                    return after[:marker_at] or "default"
                # Fallback for usernames outside the generated
                # grammar: preserved first-segment behavior.
                if "-" in after:
                    return after.split("-", 1)[0]
                if after:
                    return after
        except Exception:
            pass
        return "default"

    def _clone_with_new_session(
        self, cfg: ProxyConfig, new_session_name: str
    ) -> ProxyConfig:
        """Clone a non-Decodo config with only session fields changed.

        Provider, host, port, password, country and tier are kept, so
        rotation never rewrites another provider's config as Decodo
        or sends its credential to a Decodo endpoint.
        """
        username = cfg.username or ""
        if username and cfg.session_name and cfg.session_name in username:
            username = username.replace(cfg.session_name, new_session_name, 1)
        elif username and "session-" in username:
            username = re.sub(
                r"session-[^-]+", f"session-{new_session_name}", username, count=1
            )
        new_config = replace(
            cfg,
            username=username,
            session_name=new_session_name,
            proxy_id=None,
        )
        self.register_config(new_config)
        return new_config

    def rotate_proxy(
        self,
        reason: str = "manual",
        session_name: Optional[Union[str, ProxyConfig]] = None,
        session_id: Optional[str] = None,
    ) -> Optional[ProxyConfig]:
        """Create a fresh sticky session config (for recovery use).

        Provider identity is preserved: Decodo configs get a new
        sticky session on Decodo; any other provider is cloned on the
        same provider/endpoint with the same credentials and only the
        session-varying fields changed.
        """
        if session_id is not None and session_name is None:
            session_name = session_id
        # An explicitly named session that is unknown must not rotate
        # a different session's config.
        if isinstance(session_name, str) and session_name not in self._configs_by_session:
            return None
        cfg = self.get_config(session_name)
        if not cfg:
            return None
        old_key = self._session_key_for(cfg)
        new_session_name = f"rotated-{uuid.uuid4().hex[:6]}"
        if cfg.provider == "decodo":
            base_user = self._safe_extract_base_user(
                getattr(cfg, "username", None)
            )
            new_config = self.create_decodo_config(
                user=base_user,
                password=cfg.password,
                country=cfg.country,
                session_name=new_session_name,
                duration_minutes=30,
                tier=cfg.tier,
            )
        else:
            new_config = self._clone_with_new_session(cfg, new_session_name)
        # Replace the rotated session's registry entry; other
        # sessions keep their own configs untouched.
        if old_key != self._session_key_for(new_config):
            self._configs_by_session.pop(old_key, None)
        if isinstance(session_name, str):
            self._configs_by_session.pop(session_name, None)
        self._proxy_history.append(
            {
                "action": "rotate",
                "reason": reason,
                "old": cfg.session_name,
                "new": new_config.session_name,
            }
        )
        return new_config
