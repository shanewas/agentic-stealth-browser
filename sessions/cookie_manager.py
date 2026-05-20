"""
Cookie & Session Resilience Module
Handles cookie loading, validation, refresh, and multi-session management.
Cleaned up for Phase 8: removed duplication with sessions/session_manager.py (#134),
fixed broken SessionOrchestrator, added persist/resume + distributed bundle support (#236, #298).
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

            self.last_refresh = datetime.now()
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
        """Refresh expired or old cookies (placeholder - real refresh may need re-auth)."""
        if not self.cookies:
            return {"status": "error", "message": "No cookies loaded"}

        now = datetime.now()
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
            "refreshed": 0,
            "note": "Cookie refresh typically requires re-login or token refresh flows outside this manager."
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
    """High-level session management with cookie resilience. Composes with main SessionManager + CookieManager.
    Supports MCP session persist/resume and distributed bundles (#236, #298).
    """

    def __init__(self, session_manager=None):
        from sessions.session_manager import SessionManager as MainSessionManager
        self.main_session_manager = session_manager or MainSessionManager()
        self.sessions: Dict[str, Dict] = {}
        self.cookie_managers: Dict[str, CookieManager] = {}
        self.browser_contexts: Dict[str, Any] = {}

    def create_resilient_session(self, session_name: Optional[str] = None, 
                                  cookies_path: Optional[str] = None,
                                  anonymous: bool = False) -> Dict:
        """Create a new session with optional cookie loading setup."""
        if session_name is None:
            import uuid
            session_name = f"resilient-{uuid.uuid4().hex[:8]}"

        meta = self.main_session_manager.create_session(session_name, anonymous=anonymous)

        session = {
            "name": session_name,
            "created_at": datetime.now().isoformat(),
            "cookies_loaded": False,
            "last_activity": None,
            "rotation_count": 0,
            "user_data_dir": meta.get("user_data_dir"),
            "cookies_file": meta.get("cookies_file"),
        }

        self.sessions[session_name] = session

        if cookies_path:
            cookie_manager = CookieManager()
            session["cookies_path"] = cookies_path
            self.cookie_managers[session_name] = cookie_manager

        return session

    async def attach_browser_context(self, session_name: str, browser_context) -> None:
        """Attach a live browser context to a session for cookie ops."""
        self.browser_contexts[session_name] = browser_context
        if session_name in self.cookie_managers:
            self.cookie_managers[session_name].browser_context = browser_context

    async def load_cookies_for_session(self, session_name: str, cookies_path: Optional[str] = None) -> Dict[str, Any]:
        """Load cookies for a managed session."""
        if session_name not in self.cookie_managers:
            cm = CookieManager(self.browser_contexts.get(session_name))
            self.cookie_managers[session_name] = cm

        path = cookies_path or self.sessions.get(session_name, {}).get("cookies_path")
        if not path:
            return {"status": "error", "message": "No cookies_path for session"}

        result = await self.cookie_managers[session_name].load_cookies(path)
        if result.get("status") == "success":
            self.sessions[session_name]["cookies_loaded"] = True
            self.sessions[session_name]["last_activity"] = datetime.now().isoformat()
        return result

    async def save_cookies_for_session(self, session_name: str, output_path: Optional[str] = None) -> Dict[str, Any]:
        """Save cookies for a session."""
        if session_name not in self.cookie_managers:
            return {"status": "error", "message": "No cookie manager for session"}

        path = output_path or self.sessions.get(session_name, {}).get("cookies_file", f"/tmp/{session_name}-cookies.json")
        return await self.cookie_managers[session_name].save_cookies(path)

    async def rotate_if_needed(self, session_name: str, reason: str = "scheduled") -> Optional[Dict]:
        """Rotate session if it has been used too long or has issues."""
        if session_name not in self.sessions:
            return None

        session = self.sessions[session_name]
        session["rotation_count"] += 1
        session["last_rotation"] = datetime.now().isoformat()
        session["rotation_reason"] = reason

        new_name = f"{session_name}-rotated-{session['rotation_count']}"
        new_session = self.create_resilient_session(new_name, anonymous=True)
        return new_session

    async def ensure_fresh_cookies(self, session_name: str, max_age_hours: int = 8, force: bool = False) -> Dict[str, Any]:
        """Ensure cookies are fresh for the session."""
        if session_name not in self.cookie_managers:
            return {"status": "no_manager"}

        cm = self.cookie_managers[session_name]
        if not cm.last_refresh:
            cm.last_refresh = datetime.now()
            return {"status": "initialized"}

        age_hours = (datetime.now() - cm.last_refresh).total_seconds() / 3600

        if force or age_hours > max_age_hours:
            refresh_result = await cm.refresh_cookies(max_age_hours)
            return {
                "status": "refreshed",
                "age_hours": round(age_hours, 1),
                "result": refresh_result
            }

        return {
            "status": "fresh",
            "age_hours": round(age_hours, 1)
        }

    async def get_cookie_health(self, session_name: str) -> Dict[str, Any]:
        if session_name not in self.cookie_managers:
            return {"status": "no_manager"}
        return await self.cookie_managers[session_name].get_cookie_health()

    async def warm_up_session(self, session_name: str, intensity: str = "medium") -> Dict[str, Any]:
        """Lightweight warm-up marker."""
        if session_name not in self.sessions:
            return {"status": "error", "message": "Unknown session"}

        self.sessions[session_name]["last_activity"] = datetime.now().isoformat()
        return {"status": "success", "intensity": intensity, "message": "Warm-up marker recorded"}

    # === New: MCP / Distributed support (#236, #298) ===
    async def export_session_bundle(self, session_name: str, bundle_path: str) -> Dict[str, Any]:
        """Export session (cookies + meta) for multi-machine / distributed use or MCP resume."""
        if session_name not in self.sessions:
            return {"status": "error", "message": "Session not found"}

        session = self.sessions[session_name]
        bundle = {
            "meta": session,
            "cookies": [],
            "exported_at": datetime.utcnow().isoformat(),
            "version": "1.0",
        }

        if session_name in self.cookie_managers:
            cm = self.cookie_managers[session_name]
            if cm.browser_context:
                try:
                    cookies = await cm.browser_context.cookies()
                    bundle["cookies"] = cookies
                except Exception as e:
                    bundle["cookies_error"] = str(e)

        cookies_file = session.get("cookies_file")
        if cookies_file and Path(cookies_file).exists():
            try:
                with open(cookies_file) as f:
                    bundle["cookies_file_content"] = json.load(f)
            except:
                pass

        Path(bundle_path).parent.mkdir(parents=True, exist_ok=True)
        with open(bundle_path, "w") as f:
            json.dump(bundle, f, indent=2)

        return {
            "status": "success",
            "bundle": bundle_path,
            "cookie_count": len(bundle.get("cookies", [])),
            "note": "For full resume, also copy the user_data_dir and use same session_name on target machine."
        }

    async def import_session_bundle(self, bundle_path: str, target_session_name: Optional[str] = None) -> Dict[str, Any]:
        """Import a bundle and create/resume session."""
        if not Path(bundle_path).exists():
            return {"status": "error", "message": "Bundle not found"}

        with open(bundle_path) as f:
            bundle = json.load(f)

        meta = bundle.get("meta", {})
        name = target_session_name or meta.get("name", f"imported-{datetime.now().strftime('%Y%m%d%H%M')}")
        cookies = bundle.get("cookies", []) or bundle.get("cookies_file_content", [])

        session = self.create_resilient_session(name)
        session["imported_from"] = bundle_path
        session["imported_at"] = datetime.utcnow().isoformat()

        if cookies and name in self.cookie_managers:
            cm = self.cookie_managers[name]
            cm.cookies = cookies
            if cm.browser_context:
                try:
                    await cm.browser_context.add_cookies(cookies)
                except Exception as e:
                    session["import_cookie_error"] = str(e)

        return {
            "status": "success",
            "session": name,
            "cookies_restored": len(cookies),
            "meta": meta
        }

    async def resume_session(self, session_name: str, cookies_path: Optional[str] = None) -> Dict[str, Any]:
        """Resume a named session (for MCP persist/resume)."""
        if session_name not in self.sessions:
            self.create_resilient_session(session_name)

        if cookies_path:
            return await self.load_cookies_for_session(session_name, cookies_path)
        recorded = self.sessions[session_name].get("cookies_file")
        if recorded and Path(recorded).exists():
            return await self.load_cookies_for_session(session_name, recorded)
        return {"status": "success", "message": "Session resumed (no cookies to load)", "session": session_name}
