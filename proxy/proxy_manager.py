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
