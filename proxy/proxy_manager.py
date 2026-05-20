"""
Proxy Manager for Agentic Browser
Supports Decodo, Smartproxy, and other residential providers with sticky sessions
"""

from dataclasses import dataclass
from typing import Optional, Dict


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


class ProxyManager:
    """
    Manages proxy configuration and sticky session generation.
    Currently optimized for Decodo residential proxies.
    """
    
    def __init__(self):
        self.current_config: Optional[ProxyConfig] = None
    
    def create_decodo_config(
        self,
        user: str,
        password: str,
        country: str = "jp",
        session_name: Optional[str] = None,
        duration_minutes: int = 1440
    ) -> ProxyConfig:
        """Create a Decodo residential proxy config with sticky session"""
        
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
            session_duration_minutes=duration_minutes
        )
        
        self.current_config = config
        return config
    
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
                        "session": cfg.session_name
                    }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e),
                "provider": cfg.provider
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
            "duration_minutes": cfg.session_duration_minutes
        }
