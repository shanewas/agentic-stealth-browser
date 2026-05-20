"""
Proxy Manager for Agentic Browser
Supports Decodo, Smartproxy, and other residential providers with sticky sessions.
Phase 8: Added tier selection (residential, datacenter, mobile, isp), better rotation hooks (#119).
"""

from dataclasses import dataclass
from typing import Optional, Dict, Literal


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


class ProxyManager:
    """
    Manages proxy configuration and sticky session generation.
    Currently optimized for Decodo residential proxies.
    Supports tier-aware selection and Playwright integration.
    """

    SUPPORTED_PROVIDERS = ["decodo", "smartproxy", "oxylabs", "selfhosted"]

    def __init__(self):
        self.current_config: Optional[ProxyConfig] = None
        self._proxy_history: list = []
        self._rotation_count: int = 0  # #163: track for exhaustion fallback behavior

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

    def get_playwright_proxy_args(self) -> Dict:
        """Return Playwright-compatible proxy configuration"""
        if not self.current_config:
            return {}

        cfg = self.current_config
        return {
            "server": f"socks5://{cfg.host}:{cfg.port}",
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
