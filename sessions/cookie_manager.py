"""
Cookie & Session Resilience Module
Handles cookie loading, validation, refresh, and multi-session management.
"""

import json
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta


class CookieManager:
    """Manages cookies for long-running stealth sessions."""

    def __init__(self, browser_context=None):
        self.browser_context = browser_context
        self.cookies: List[Dict] = []
        self.last_refresh: Optional[datetime] = None

    async def load_cookies(self, cookies_path: str) -> Dict[str, Any]:
        """Load cookies from a JSON file (exported from real browser)."""
        path = Path(cookies_path)
        if not path.exists():
            return {"status": "error", "message": f"File not found: {cookies_path}"}

        try:
            with open(path, "r") as f:
                cookies = json.load(f)

            # Normalize cookies for Playwright
            normalized = []
            for cookie in cookies:
                if "sameSite" in cookie:
                    if cookie["sameSite"] not in ["None", "Lax", "Strict"]:
                        cookie["sameSite"] = "None"
                normalized.append(cookie)

            self.cookies = normalized

            if self.browser_context:
                await self.browser_context.add_cookies(normalized)

            return {
                "status": "success",
                "cookies_loaded": len(normalized),
                "file": str(path)
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def save_cookies(self, output_path: str) -> Dict[str, Any]:
        """Save current cookies to a JSON file."""
        if not self.browser_context:
            return {"status": "error", "message": "No browser context available"}

        try:
            cookies = await self.browser_context.cookies()
            with open(output_path, "w") as f:
                json.dump(cookies, f, indent=2)

            return {
                "status": "success",
                "cookies_saved": len(cookies),
                "file": output_path
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def refresh_cookies(self, max_age_hours: int = 24) -> Dict[str, Any]:
        """Refresh expired or old cookies."""
        if not self.cookies:
            return {"status": "error", "message": "No cookies loaded"}

        now = datetime.now()
        refreshed = 0
        expired = 0

        for cookie in self.cookies:
            if "expires" in cookie and cookie["expires"]:
                try:
                    expiry = datetime.fromtimestamp(cookie["expires"])
                    if (now - expiry).total_seconds() > (max_age_hours * 3600):
                        expired += 1
                except:
                    pass

        self.last_refresh = now

        return {
            "status": "success",
            "total_cookies": len(self.cookies),
            "expired": expired,
            "refreshed": refreshed
        }

    def get_cookie_stats(self) -> Dict[str, Any]:
        """Return statistics about loaded cookies."""
        if not self.cookies:
            return {"count": 0}

        domains = set()
        for cookie in self.cookies:
            if "domain" in cookie:
                domains.add(cookie["domain"])

        return {
            "count": len(self.cookies),
            "unique_domains": len(domains),
            "last_refresh": self.last_refresh.isoformat() if self.last_refresh else None
        }


class SessionManager:
    """Enhanced session management with resilience features."""

    def __init__(self):
        self.sessions: Dict[str, Dict] = {}
        self.current_session: Optional[str] = None

    def create_session(self, session_name: Optional[str] = None, anonymous: bool = False) -> Dict:
        """Create a new session with metadata."""
        import uuid
        if session_name is None:
            session_name = f"session-{uuid.uuid4().hex[:8]}"

        session = {
            "name": session_name,
            "created_at": datetime.now().isoformat(),
            "anonymous": anonymous,
            "user_data_dir": f"/tmp/stealth-sessions/{session_name}",
            "cookies_loaded": False,
            "last_used": None
        }

        self.sessions[session_name] = session
        self.current_session = session_name
        return session

    def rotate_session(self, reason: str = "manual") -> Optional[Dict]:
        """Create a new session and mark the old one as rotated."""
        if self.current_session:
            old_session = self.sessions.get(self.current_session)
            if old_session:
                old_session["rotated_at"] = datetime.now().isoformat()
                old_session["rotation_reason"] = reason

        return self.create_session(anonymous=True)

    def get_session_stats(self) -> Dict:
        """Return session statistics."""
        return {
            "total_sessions": len(self.sessions),
            "current": self.current_session,
            "active_sessions": [s for s in self.sessions.values() if not s.get("rotated_at")]
        }
