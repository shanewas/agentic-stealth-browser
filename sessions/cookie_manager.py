"""
Cookie & Session Resilience Module
Handles cookie loading, validation, refresh, and multi-session management.
Cleaned up for Phase 8: removed duplication with sessions/session_manager.py (#134),
fixed broken SessionOrchestrator, added persist/resume + distributed bundle support (#236, #298).
Phase 8 P1 #82: added optional at-rest encryption + integrity protection for cookie files (Fernet).
"""

import json
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone

# Optional encryption support (cryptography already in pyproject.toml deps)
try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # pragma: no cover
    Fernet = None
    InvalidToken = Exception


class CookieManager:
    """Manages cookies for long-running stealth sessions."""

    def __init__(self, browser_context=None):
        self.browser_context = browser_context
        self.cookies: List[Dict] = []
        self.last_refresh: Optional[datetime] = None

    def _get_cipher(self, key: Optional[str]) -> Optional["Fernet"]:
        """Return Fernet cipher for optional encryption (supports raw secret or fernet key)."""
        if not key or Fernet is None:
            return None
        try:
            k = key.encode() if isinstance(key, str) else key
            if len(k) == 44 and k.endswith(b"="):  # looks like a Fernet key
                return Fernet(k)
            # Derive a stable 32-byte key from arbitrary secret (user provided password etc)
            import hashlib
            import base64
            digest = hashlib.sha256(k).digest()
            fkey = base64.urlsafe_b64encode(digest)
            return Fernet(fkey)
        except Exception:
            return None

    async def load_cookies(self, cookies_path: str, encryption_key: Optional[str] = None) -> Dict[str, Any]:
        """Load cookies from JSON file (Playwright format or simple list).
        Supports optional decryption when encryption_key provided (#82 P1 security).
        Backward compatible: plain files continue to work with no key.
        """
        path = Path(cookies_path)
        if not path.exists():
            return {"status": "error", "message": f"Cookies file not found: {cookies_path}"}

        try:
            with open(path) as f:
                data = json.load(f)

            cipher = self._get_cipher(encryption_key)
            cookies_list = None

            if isinstance(data, dict) and data.get("encrypted") and cipher:
                try:
                    token = data["data"].encode()
                    decrypted = cipher.decrypt(token)
                    cookies_list = json.loads(decrypted)
                except InvalidToken:
                    return {"status": "error", "message": "Invalid encryption key or corrupted cookie file"}
                except Exception as e:
                    return {"status": "error", "message": f"Decryption failed: {e}"}
            elif isinstance(data, dict) and data.get("encrypted"):
                return {"status": "error", "message": "Encrypted cookie file but no encryption_key provided"}

            # Fallback to plain / legacy formats
            if cookies_list is None:
                if isinstance(data, list):
                    cookies_list = data
                elif isinstance(data, dict):
                    cookies_list = data.get("cookies", data.get("cookies_file_content", []))
                else:
                    cookies_list = []

            self.cookies = cookies_list or []

            if self.browser_context and self.cookies:
                try:
                    await self.browser_context.add_cookies(self.cookies)
                except Exception as e:
                    return {"status": "partial", "loaded": len(self.cookies), "error": str(e)}

            return {"status": "success", "cookies_loaded": len(self.cookies)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def load_cookies_from_data(self, cookies_data: Any, encryption_key: Optional[str] = None) -> Dict[str, Any]:
        """Load cookies from in-memory data (list / dict / JSON string or bytes).
        Supports optional decryption key for encrypted payloads (#82).
        Addresses P1 #145 (MCP cookies/state) + security.
        """
        try:
            if isinstance(cookies_data, (str, bytes)):
                data = json.loads(cookies_data)
            else:
                data = cookies_data

            cipher = self._get_cipher(encryption_key)
            cookies_list = None

            if isinstance(data, dict) and data.get("encrypted") and cipher:
                try:
                    token = data["data"].encode()
                    decrypted = cipher.decrypt(token)
                    cookies_list = json.loads(decrypted)
                except InvalidToken:
                    return {"status": "error", "message": "Invalid encryption key for inline data"}
                except Exception as e:
                    return {"status": "error", "message": f"Decryption failed: {e}"}
            elif isinstance(data, dict) and data.get("encrypted"):
                return {"status": "error", "message": "Encrypted data provided but no key"}

            if cookies_list is None:
                if isinstance(data, list):
                    cookies_list = data
                elif isinstance(data, dict):
                    cookies_list = data.get("cookies", data.get("cookies_file_content", []))
                else:
                    cookies_list = []

            self.cookies = cookies_list or []

            if self.browser_context and self.cookies:
                try:
                    await self.browser_context.add_cookies(self.cookies)
                except Exception as e:
                    return {"status": "partial", "loaded": len(self.cookies), "error": str(e)}

            return {"status": "success", "cookies_loaded": len(self.cookies), "source": "inline_data"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def is_cookie_expired(self, cookie: Dict, max_age_hours: int = 24) -> bool:
        """Check if a single cookie is expired or too old."""
        if "expires" not in cookie or not cookie["expires"]:
            return False
        try:
            expiry = datetime.fromtimestamp(cookie["expires"])
            now = datetime.now(timezone.utc)
            return (now - expiry).total_seconds() > (max_age_hours * 3600)
        except Exception:
            return True  # treat bad data as expired for safety

    async def refresh_cookies_if_needed(self, max_age_hours: int = 8) -> Dict[str, Any]:
        """Check and report on cookie freshness (actual refresh usually requires re-auth)."""
        if not self.cookies:
            return {"status": "no_cookies"}

        now = datetime.now(timezone.utc)
        expired = 0

        for cookie in self.cookies:
            if "expires" in cookie and cookie["expires"]:
                try:
                    expiry = datetime.fromtimestamp(cookie["expires"])
                    if (now - expiry).total_seconds() > (max_age_hours * 3600):
                        expired += 1
                except Exception:
                    pass

        self.last_refresh = now

        return {
            "status": "success",
            "total_cookies": len(self.cookies),
            "expired": expired,
            "refreshed": 0,
            "note": "Cookie refresh typically requires re-login or token refresh flows outside this manager."
        }

    async def clear_cookies(self) -> Dict[str, Any]:
        """Clear in-memory tracked cookies and the underlying browser context cookies (if any).

        P1 #90: supports automatic invalidation on account restriction or compromise detection.
        Safe to call multiple times; idempotent. (deduped duplicate definition)
        """
        cleared = len(self.cookies)
        self.cookies = []
        self.last_refresh = None

        if self.browser_context:
            try:
                await self.browser_context.clear_cookies()
                return {"status": "success", "cleared": cleared, "context_cleared": True}
            except Exception as e:
                return {"status": "partial", "cleared": cleared, "error": str(e)}

        return {"status": "success", "cleared": cleared}

    async def get_cookie_health(self) -> Dict[str, Any]:
        """Return detailed health snapshot of current cookies."""
        if not self.cookies:
            return {"status": "no_cookies", "total": 0}

        now = datetime.now(timezone.utc)
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
                except Exception:
                    pass

        return {
            "status": "healthy" if expired == 0 else "degraded",
            "total": len(self.cookies),
            "expired": expired,
            "expiring_soon": expiring_soon,
            "secure": secure_count,
            "http_only": http_only_count,
            "last_check": now.isoformat()
        }

    async def save_cookies_to_file(self, cookies_path: str, encryption_key: Optional[str] = None, encrypt: bool = False) -> Dict[str, Any]:
        """Save current in-memory cookies to a file.
        If encryption_key (or encrypt=True + key) provided, uses Fernet authenticated encryption (#82 P1).
        Plaintext format remains compatible. Supports both kwarg styles used by callers.
        """
        if not self.cookies:
            return {"status": "no_cookies"}

        # Support legacy/compat call style where encrypt flag is passed separately
        key = encryption_key
        path = Path(cookies_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        cipher = self._get_cipher(key)
        meta = {
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "count": len(self.cookies),
            "encrypted": bool(cipher),
        }

        try:
            if cipher:
                plain = json.dumps(self.cookies, separators=(",", ":")).encode("utf-8")
                token = cipher.encrypt(plain)
                payload = {
                    "encrypted": True,
                    "version": 1,
                    "data": token.decode("utf-8"),
                    "meta": meta,
                }
                with open(path, "w") as f:
                    json.dump(payload, f, indent=2)
                return {"status": "success", "saved": len(self.cookies), "encrypted": True, "path": str(path)}
            else:
                # Plaintext (legacy compatible) + meta wrapper
                payload = {"cookies": self.cookies, "meta": meta}
                with open(path, "w") as f:
                    json.dump(payload, f, indent=2)
                return {"status": "success", "saved": len(self.cookies), "encrypted": False, "path": str(path)}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def ensure_fresh_cookies(self, max_age_hours: int = 8) -> Dict[str, Any]:
        """Check/report cookie freshness (compatibility wrapper)."""
        return await self.refresh_cookies_if_needed(max_age_hours)

    def create_resilient_session(self, session_name: str) -> Dict[str, Any]:
        """Create or get a resilient session record."""
        if not hasattr(self, "sessions"):
            self.sessions = {}
            self.cookie_managers = {}

        if session_name not in self.sessions:
            self.sessions[session_name] = {
                "name": session_name,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "cookies_count": 0,
                "last_used": datetime.now(timezone.utc).isoformat(),
            }
            self.cookie_managers[session_name] = CookieManager()

        return self.sessions[session_name]

    async def export_session_bundle(self, session_name: str, bundle_path: str) -> Dict[str, Any]:
        """Export full session + cookies for backup / transfer."""
        if session_name not in getattr(self, "sessions", {}):
            return {"status": "error", "message": "Session not found"}

        session = self.sessions[session_name]
        bundle = {
            "meta": session,
            "cookies": [],
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "version": "1.0",
        }

        if session_name in getattr(self, "cookie_managers", {}):
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
            except Exception:
                pass

        Path(bundle_path).parent.mkdir(parents=True, exist_ok=True)
        with open(bundle_path, "w") as f:
            json.dump(bundle, f, indent=2)

        return {
            "status": "success",
            "bundle": bundle_path,
            "cookies_count": len(bundle.get("cookies", []))
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
        session["imported_at"] = datetime.now(timezone.utc).isoformat()

        if cookies and name in getattr(self, "cookie_managers", {}):
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
            "cookies_imported": len(cookies)
        }


class SessionOrchestrator:
    """High-level coordinator for multiple resilient sessions (MCP / agent use).

    Updated for MCP contract compatibility (#106 hygiene): accepts session_manager
    in constructor and exposes create/export/import for tests + MCP wrappers.
    """

    def __init__(self, session_manager: Optional[object] = None):
        self.main_session_manager = session_manager
        self.cm = CookieManager()
        self.active_sessions: Dict[str, Dict] = {}
        # Compat aliases for existing MCP contract tests (#106)
        self.sessions = self.active_sessions
        self.cookie_managers: Dict[str, Any] = {}

    def create_resilient_session(self, session_name: str) -> Dict[str, Any]:
        """Create session (MCP hygiene / contract compat). Delegates to cm."""
        sess = self.cm.create_resilient_session(session_name)
        self.active_sessions[session_name] = sess
        self.cookie_managers[session_name] = self.cm
        return sess

    async def start_session(self, name: str, cookies_path: Optional[str] = None) -> Dict[str, Any]:
        sess = self.cm.create_resilient_session(name)
        self.active_sessions[name] = sess
        if cookies_path:
            await self.cm.load_cookies(cookies_path)
        return {"status": "started", "session": name}

    async def export_session_bundle(self, session_name: str, bundle_path: str) -> Dict[str, Any]:
        """Delegate for full MCP test / agent contract."""
        return await self.cm.export_session_bundle(session_name, bundle_path)

    async def import_session_bundle(self, bundle_path: str, target_session_name: Optional[str] = None) -> Dict[str, Any]:
        """Delegate for full MCP test / agent contract."""
        return await self.cm.import_session_bundle(bundle_path, target_session_name)

    async def export_all(self, out_dir: str) -> Dict[str, Any]:
        results = {}
        for name in list(self.active_sessions.keys()):
            path = f"{out_dir}/{name}_bundle.json"
            results[name] = await self.cm.export_session_bundle(name, path)
        return results


# P1 #82 cookie security (additive note + stub for encryption in follow-up)
# Recommended: implement Fernet save/load using existing "cryptography" dep.
async def _save_cookies_secure_stub(self, path, key=None):
    return {"status": "todo", "note": "Implement full encrypted save per #82 (see agent_browser save_cookies_to_file entrypoint)"}
