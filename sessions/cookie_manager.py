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


    async def validate_cookies(self) -> Dict[str, Any]:
        """Check if current cookies are still valid by testing a simple request."""
        if not self.browser_context or not self.cookies:
            return {"valid": False, "reason": "No cookies or context"}

        try:
            # Try to get cookies back from context
            current_cookies = await self.browser_context.cookies()
            if len(current_cookies) == 0:
                return {"valid": False, "reason": "No cookies present in browser"}

            # Check for critical cookies (common login/session cookies)
            critical_domains = set()
            for cookie in self.cookies:
                if "domain" in cookie:
                    critical_domains.add(cookie["domain"])

            return {
                "valid": True,
                "cookie_count": len(current_cookies),
                "domains": list(critical_domains)[:5]
            }
        except Exception as e:
            return {"valid": False, "reason": str(e)}

    async def auto_refresh_if_needed(self, max_age_hours: int = 12) -> Dict[str, Any]:
        """Automatically refresh cookies if they are older than max_age_hours."""
        if not self.last_refresh:
            self.last_refresh = datetime.now()
            return {"action": "initialized", "message": "First load"}

        age = datetime.now() - self.last_refresh
        if age.total_seconds() > (max_age_hours * 3600):
            result = await self.refresh_cookies(max_age_hours)
            return {"action": "refreshed", "result": result}

        return {"action": "no_refresh_needed", "age_hours": round(age.total_seconds() / 3600, 1)}

    async def get_cookie_health(self) -> Dict[str, Any]:
        """Return detailed health status of current cookies."""
        if not self.cookies:
            return {"status": "empty", "count": 0}

        now = datetime.now()
        expired = 0
        expiring_soon = 0
        secure_count = 0
        http_only_count = 0

        for cookie in self.cookies:
            if cookie.get("secure"):
                secure_count += 1
            if cookie.get("httpOnly"):
                http_only_count += 1

            if "expires" in cookie and cookie["expires"]:
                try:
                    expiry = datetime.fromtimestamp(cookie["expires"])
                    if expiry < now:
                        expired += 1
                    elif (expiry - now).total_seconds() < (24 * 3600):
                        expiring_soon += 1
                except:
                    pass

        return {
            "status": "healthy" if expired == 0 else "degraded",
            "total": len(self.cookies),
            "expired": expired,
            "expiring_soon": expiring_soon,
            "secure": secure_count,
            "http_only": http_only_count,
            "last_refresh": self.last_refresh.isoformat() if self.last_refresh else None
        }


class SessionOrchestrator:
    """High-level session management with cookie resilience."""

    def __init__(self):
        self.sessions: Dict[str, Dict] = {}
        self.cookie_managers: Dict[str, CookieManager] = {}

    def create_resilient_session(self, session_name: Optional[str] = None, 
                                  cookies_path: Optional[str] = None) -> Dict:
        """Create a new session with optional cookie loading."""
        import uuid
        if session_name is None:
            session_name = f"resilient-{uuid.uuid4().hex[:8]}"

        session = {
            "name": session_name,
            "created_at": datetime.now().isoformat(),
            "cookies_loaded": False,
            "last_activity": None,
            "rotation_count": 0
        }

        self.sessions[session_name] = session

        if cookies_path:
            cookie_manager = CookieManager()
            # Note: actual loading happens when browser context is available
            session["cookies_path"] = cookies_path
            self.cookie_managers[session_name] = cookie_manager

        return session

    async def rotate_if_needed(self, session_name: str, reason: str = "scheduled") -> Optional[Dict]:
        """Rotate session if it has been used too long or has issues."""
        if session_name not in self.sessions:
            return None

        session = self.sessions[session_name]
        session["rotation_count"] += 1
        session["last_rotation"] = datetime.now().isoformat()
        session["rotation_reason"] = reason

        # Create new session
        new_name = f"{session_name}-rotated-{session['rotation_count']}"
        new_session = self.create_resilient_session(new_name)
        return new_session


    async def ensure_fresh_cookies(self, max_age_hours: int = 8, force: bool = False) -> Dict[str, Any]:
        """Ensure cookies are fresh. Auto-refresh if older than max_age_hours or forced."""
        if not self.last_refresh:
            self.last_refresh = datetime.now()
            return {"status": "initialized"}

        age_hours = (datetime.now() - self.last_refresh).total_seconds() / 3600

        if force or age_hours > max_age_hours:
            refresh_result = await self.refresh_cookies(max_age_hours)
            return {
                "status": "refreshed",
                "age_hours": round(age_hours, 1),
                "result": refresh_result
            }

        return {
            "status": "fresh",
            "age_hours": round(age_hours, 1)
        }

    async def warm_up_session(self, intensity: str = "medium") -> Dict[str, Any]:
        """Perform natural warm-up behavior before using the session for real work."""
        if not self.browser_context:
            return {"status": "error", "message": "No browser context available"}

        try:
            page = await self.browser_context.new_page() if hasattr(self.browser_context, 'new_page') else None

            if intensity == "light":
                # Light warm-up
                await asyncio.sleep(1.5)
                if page:
                    await page.mouse.wheel(0, 200)
                    await asyncio.sleep(0.8)

            elif intensity == "medium":
                # Medium warm-up with human-like behavior
                await asyncio.sleep(2.0)
                if page:
                    await page.mouse.wheel(0, 350)
                    await asyncio.sleep(1.2)
                    await page.mouse.wheel(0, -80)
                    await asyncio.sleep(0.9)

            elif intensity == "heavy":
                # Heavy warm-up (more realistic)
                await asyncio.sleep(3.0)
                if page:
                    await page.mouse.wheel(0, 420)
                    await asyncio.sleep(1.8)
                    await page.mouse.wheel(0, -120)
                    await asyncio.sleep(2.2)
                    await page.mouse.wheel(0, 180)
                    await asyncio.sleep(1.5)

            return {
                "status": "success",
                "intensity": intensity,
                "message": "Warm-up completed"
            }

        except Exception as e:
            return {"status": "error", "message": str(e)}
