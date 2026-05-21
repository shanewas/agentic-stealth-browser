"""
Proxy Manager for Agentic Browser
Supports Decodo, Smartproxy, and other residential providers with sticky sessions.
Phase 8: Added tier selection (residential, datacenter, mobile, isp), better rotation hooks (#119).

P4 #119: Added smart proxy rotation based on site sensitivity and proxy health tracking.
"""

from dataclasses import dataclass
from typing import Optional, Dict, Any, Literal
import time


ProxyTier = Literal["residential", "datacenter", "mobile", "isp"]


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
            errors.append(f"host contains invalid characters (spaces or path separators): {self.host!r}")

        # Port validation
        if not isinstance(self.port, int) or self.port < 1 or self.port > 65535:
            errors.append(f"port must be 1-65535, got {self.port}")

        # Country validation (2-letter code)
        if not isinstance(self.country, str) or len(self.country) != 2 or not self.country.isalpha():
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
            errors.append(f"provider must be one of {_SUPPORTED_PROVIDERS}, got {self.provider!r}")

        return errors

    def to_safe_dict(self) -> Dict[str, Any]:
        """Return a dict representation with credentials redacted for logging/metadata.

        Strips password and masks username to prevent credential leaks in
        audit logs, recovery history, and status reports.
        """
        from dataclasses import asdict
        d = asdict(self)
        d["password"] = "***REDACTED***"
        # Mask most of the username, keep first 3 chars
        if d.get("username") and len(d["username"]) > 3:
            d["username"] = d["username"][:3] + "***"
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
        self.current_config: Optional[ProxyConfig] = None
        self._proxy_history: list = []
        self._rotation_count: int = 0  # #163: track for exhaustion fallback behavior
        # P4 #119: Proxy health tracking
        self._proxy_health: Dict[str, Dict[str, Any]] = {}
        self._site_sensitivity_cache: Dict[str, str] = {}

    def get_site_sensitivity(self, domain: str) -> str:
        """P4 #119: Determine the sensitivity level for a given domain.
        
        Returns one of: "low", "medium", "high", "critical".
        Higher sensitivity sites require better proxies (residential/mobile).
        """
        if domain in self._site_sensitivity_cache:
            return self._site_sensitivity_cache[domain]

        for level, domains in self.SITE_SENSITIVITY.items():
            for d in domains:
                if d in domain.lower():
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

    def record_proxy_result(self, session_name: str, success: bool, response_time: float = 0.0) -> None:
        """P4 #119: Record the result of a proxy request for health tracking."""
        if session_name not in self._proxy_health:
            self._proxy_health[session_name] = {
                "total_requests": 0,
                "successful_requests": 0,
                "failed_requests": 0,
                "total_response_time": 0.0,
                "last_used": time.time(),
                "consecutive_failures": 0,
            }

        health = self._proxy_health[session_name]
        health["total_requests"] += 1
        health["last_used"] = time.time()
        health["total_response_time"] += response_time

        if success:
            health["successful_requests"] += 1
            health["consecutive_failures"] = 0
        else:
            health["failed_requests"] += 1
            health["consecutive_failures"] += 1

    def get_proxy_health(self, session_name: Optional[str] = None) -> Dict[str, Any]:
        """P4 #119: Get health information for a proxy session."""
        if session_name:
            return self._proxy_health.get(session_name, {"status": "unknown"})
        
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

    def should_rotate_proxy(self, session_name: Optional[str] = None, threshold: int = 3) -> bool:
        """P4 #119: Check if the current proxy should be rotated based on health.
        
        Returns True if consecutive failures exceed the threshold.
        """
        if session_name and session_name in self._proxy_health:
            return self._proxy_health[session_name]["consecutive_failures"] >= threshold
        return False

    def create_decodo_config(
        self,
        user: str,
        password: str,
        country: str = "jp",
        session_name: Optional[str] = None,
        duration_minutes: int = 1440,
        tier: ProxyTier = "residential"
    ) -> ProxyConfig:
        """Create a Decodo residential (or tiered) proxy config with sticky session"""

        if session_name is None:
            import uuid
            session_name = f"agent-{uuid.uuid4().hex[:8]}"

        proxy_user = (
            f"user-{user}-country-{country}-"
            f"session-{session_name}-sessionduration-{duration_minutes}"
        )

        config = ProxyConfig(
            provider="decodo",
            host="gate.decodo.com",
            port=10001,
            username=proxy_user,
            password=password,
            country=country,
            session_name=session_name,
            session_duration_minutes=duration_minutes,
            tier=tier
        )

        errors = config.validate()
        if errors:
            raise ValueError(f"Invalid proxy configuration: {'; '.join(errors)}")

        self.current_config = config
        self._proxy_history.append({"action": "create", "config": config, "ts": __import__("time").time()})
        self._rotation_count = getattr(self, "_rotation_count", 0) + 1
        return config

    def select_tier(self, desired_tier: ProxyTier, country: str = "jp", **kwargs) -> ProxyConfig:
        """High-level tier selection helper."""
        if not self.current_config:
            return self.create_decodo_config(
                user=kwargs.get("user", "default"),
                password=kwargs.get("password", ""),
                country=country,
                tier=desired_tier,
                **{k: v for k, v in kwargs.items() if k not in ["user", "password"]}
            )
        self.current_config.tier = desired_tier
        return self.current_config

    def get_playwright_proxy_args(self, prefer_http: bool = False) -> Dict:
        """Return Playwright-compatible proxy configuration.

        Args:
            prefer_http: If True, use HTTP proxy format instead of SOCKS5.
                Most residential providers support both; HTTP is preferred
                for better compatibility with Playwright's Chromium.
        """
        if not self.current_config:
            return {}

        cfg = self.current_config
        protocol = "http" if prefer_http else "socks5"
        return {
            "server": f"{protocol}://{cfg.host}:{cfg.port}",
            "username": cfg.username,
            "password": cfg.password
        }

    def get_curl_proxy_string(self) -> str:
        """Return curl-compatible proxy string"""
        if not self.current_config:
            return ""

        cfg = self.current_config
        return f"socks5://{cfg.username}:{cfg.password}@{cfg.host}:{cfg.port}"

    async def test_proxy_connection(self, timeout: int = 10) -> Dict:
        """Test if the current proxy configuration actually works."""
        import httpx

        if not self.current_config:
            return {"status": "error", "message": "No proxy configured"}

        cfg = self.current_config
        proxy_url = f"socks5://{cfg.username}:{cfg.password}@{cfg.host}:{cfg.port}"

        try:
            async with httpx.AsyncClient(proxies={"http://": proxy_url, "https://": proxy_url}, timeout=timeout) as client:
                response = await client.get("https://api.ipify.org?format=json")
                if response.status_code == 200:
                    ip_data = response.json()
                    return {
                        "status": "success",
                        "ip": ip_data.get("ip"),
                        "provider": cfg.provider,
                        "country": cfg.country,
                        "session": cfg.session_name,
                        "tier": cfg.tier
                    }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e),
                "provider": cfg.provider,
                "tier": getattr(cfg, 'tier', 'unknown')
            }

        return {"status": "error", "message": "Unknown failure"}

    def get_current_proxy_info(self) -> Dict:
        """Return current proxy configuration summary."""
        if not self.current_config:
            return {"configured": False}

        cfg = self.current_config
        return {
            "configured": True,
            "provider": cfg.provider,
            "host": cfg.host,
            "port": cfg.port,
            "country": cfg.country,
            "session_name": cfg.session_name,
            "duration_minutes": cfg.session_duration_minutes,
            "tier": cfg.tier,
            "history_length": len(self._proxy_history)
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
            parts = proxy_username.split("-")
            if len(parts) > 1 and parts[0].lower() == "user":
                return parts[1]
            if proxy_username.lower().startswith("user-"):
                after = proxy_username[5:]
                if "-" in after:
                    return after.split("-", 1)[0]
                if after:
                    return after
        except Exception:
            pass
        return "default"

    def rotate_proxy(self, reason: str = "manual") -> Optional[ProxyConfig]:
        """Create a fresh sticky session config (for recovery use)."""
        if not self.current_config:
            return None
        cfg = self.current_config
        base_user = self._safe_extract_base_user(getattr(cfg, 'username', None))
        new_config = self.create_decodo_config(
            user=base_user,
            password=cfg.password,
            country=cfg.country,
            session_name=f"rotated-{__import__('uuid').uuid4().hex[:6]}",
            duration_minutes=30,
            tier=cfg.tier
        )
        self._proxy_history.append({"action": "rotate", "reason": reason, "old": cfg.session_name, "new": new_config.session_name})
        return new_config
