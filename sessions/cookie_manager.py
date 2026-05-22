"""
Cookie & Session Resilience Module
Handles cookie loading, validation, refresh, and multi-session management.
Cleaned up for Phase 8: removed duplication with sessions/session_manager.py (#134),
AgentBrowser legacy now delegates (full consolidation in core P2 cluster); 
fixed broken SessionOrchestrator, added persist/resume + distributed bundle support (#236, #298).
Phase 8 P1 #82: added optional at-rest encryption + integrity protection for cookie files and session bundles (Fernet).
"""

import json
import hmac
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

# Optional encryption support (cryptography already in pyproject.toml deps)
try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # pragma: no cover
    Fernet = None
    InvalidToken = Exception

logger = logging.getLogger(__name__)

_MIN_KEY_LENGTH = 16


def _validate_path(path: str, must_exist_parent: bool = True) -> Path:
    """Validate and resolve a file path for cookie/bundle operations.

    - Resolves the path (no .. traversal)
    - Ensures it ends with .json or .jsonl (expected cookie format)
    - Ensures parent directory exists if must_exist_parent=True
    - Returns the resolved path or raises ValueError
    """
    if not path or not isinstance(path, str):
        raise ValueError("Path must be a non-empty string.")
    resolved = Path(path).resolve()
    # Block path traversal: resolved must not differ in a way that escapes
    # (resolve() already handles '..' expansion; we just ensure no path traversal pattern remains)
    if ".." in Path(path).parts:
        raise ValueError(f"Path traversal (..) not allowed: {path}")
    if not resolved.name.endswith((".json", ".jsonl")):
        raise ValueError(
            f"File must end with .json or .jsonl, got: {resolved.name}"
        )
    if must_exist_parent and not resolved.parent.exists():
        raise ValueError(
            f"Parent directory does not exist: {resolved.parent}"
        )
    return resolved


_INTEGRITY_SALT = b"agentic-stealth-browser-integrity-v1"


def _compute_hmac(key: str, data: bytes, session_name: str = "") -> str:
    """Compute HMAC-SHA256 integrity hash for cookie/bundle data.

    When *key* is provided (non-empty), it is used directly as the HMAC key
    so that integrity is tied to the same secret used for encryption.
    When *key* is empty / not provided, the HMAC key is derived from a
    hardcoded application salt combined with *session_name* so that plaintext
    files still carry a tamper-evident signature.
    """
    if key:
        hmac_key = key.encode("utf-8") if isinstance(key, str) else key
    else:
        hmac_key = _INTEGRITY_SALT + session_name.encode("utf-8")
    return hmac.new(hmac_key, data, "sha256").hexdigest()


def _verify_hmac(key: str, data: bytes, expected_hex: str, session_name: str = "") -> bool:
    """Recompute and compare HMAC; returns True iff the digest matches."""
    return hmac.compare_digest(_compute_hmac(key, data, session_name=session_name), expected_hex)


def _validate_cookie_domains(cookies: list, allowed_domains: list = None) -> list:
    """Filter *cookies* so that only those whose ``domain`` matches (or is a
    subdomain of) one of *allowed_domains* are kept.

    If *allowed_domains* is ``None``, no filtering is performed (backward
    compatible).  Each rejected cookie triggers a warning log entry.
    """
    if allowed_domains is None:
        return cookies

    # Normalise allowed domains: strip leading dots for matching
    norm_allowed = [d.lstrip(".") for d in allowed_domains]

    accepted = []
    for cookie in cookies:
        domain = cookie.get("domain", "")
        # Strip leading dot from cookie domain for comparison
        norm_domain = domain.lstrip(".")
        if not norm_domain:
            # Cookies without a domain are kept (session-scoped)
            accepted.append(cookie)
            continue

        # Domain matches if it equals or ends with ".<allowed>"
        matched = False
        for ad in norm_allowed:
            if norm_domain == ad or norm_domain.endswith("." + ad):
                matched = True
                break
        if matched:
            accepted.append(cookie)
        else:
            logger.warning(
                "Cookie rejected — domain %r not in allowed list %r (name=%s)",
                domain, allowed_domains, cookie.get("name", "?"),
            )

    return accepted


class CookieManager:
    """Manages cookies for long-running stealth sessions.

    Encryption key requirements:
        When providing an encryption_key to _get_cipher(), encrypt_data(), decrypt_data(),
        or any save/load method, the key must be at least 16 characters long to ensure
        adequate entropy for derived Fernet keys. Shorter keys raise ValueError.
        Pass None to disable encryption (backward compatible).
    """

    _MIN_KEY_LENGTH = _MIN_KEY_LENGTH

    def __init__(self, browser_context=None):
        self.browser_context = browser_context
        self.cookies: List[Dict] = []
        self.last_refresh: Optional[datetime] = None

    def _get_cipher(self, key: Optional[str]) -> Optional["Fernet"]:
        """Return Fernet cipher for optional encryption (supports raw secret or fernet key).

        Raises ValueError if key is provided but shorter than _MIN_KEY_LENGTH.
        Returns None if key is None or Fernet is unavailable (no encryption).
        """
        if not key or Fernet is None:
            return None
        if len(key) < self._MIN_KEY_LENGTH:
            raise ValueError(
                f"Encryption key too short (minimum {self._MIN_KEY_LENGTH} characters). "
                "Use a strong, unique passphrase."
            )
        if len(key) < 32:
            logger.warning(
                "Encryption key is shorter than 32 characters; "
                "derived key may have reduced entropy. Use a longer passphrase for better security."
            )
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

    def encrypt_data(self, data: bytes, key: Optional[str] = None) -> Optional[bytes]:
        """Basic encrypt helper in CookieManager (#82).
        Provides encrypt API for save/load flows including bundles.
        """
        cipher = self._get_cipher(key)
        if cipher is None:
            return None
        try:
            return cipher.encrypt(data)
        except Exception:
            return None

    def decrypt_data(self, token: bytes, key: Optional[str] = None) -> Optional[bytes]:
        """Basic decrypt helper in CookieManager (#82).
        Provides decrypt API for save/load flows including bundles.
        """
        cipher = self._get_cipher(key)
        if cipher is None:
            return None
        try:
            return cipher.decrypt(token)
        except Exception:
            return None

    def _try_decrypt_with_keys(self, token: bytes, keys: list) -> Optional[bytes]:
        """Try decrypting token with a list of keys (key rotation support).

        Iterates through keys in order, returning the first successful
        decryption result. Returns None if no key works.
        """
        for key in keys:
            cipher = self._get_cipher(key)
            if cipher is None:
                continue
            try:
                result = cipher.decrypt(token)
                if result is not None:
                    return result
            except Exception:
                continue
        return None

    async def load_cookies(self, cookies_path: str, encryption_key: Optional[str] = None, allowed_domains: Optional[List[str]] = None) -> Dict[str, Any]:
        """Load cookies from JSON file (Playwright format or simple list).
        Supports optional decryption when encryption_key provided (#82 P1 security).
        Backward compatible: plain files continue to work with no key.
        Integrity verification (#111): validates HMAC when present, warns on legacy files.
        Domain validation (#64): filters cookies to allowed_domains when provided.
        """
        try:
            path = _validate_path(cookies_path, must_exist_parent=True)
        except ValueError as e:
            return {"status": "error", "message": str(e)}
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

            # Integrity check for plaintext payloads (#111)
            if isinstance(data, dict) and not data.get("encrypted") and "integrity" in data:
                stored_hmac = data["integrity"]
                # Build canonical payload without the integrity field
                payload_copy = {k: v for k, v in data.items() if k != "integrity"}
                raw = json.dumps(payload_copy, separators=(",", ":"), sort_keys=True).encode("utf-8")
                # Best-effort session name: from self, from meta, or empty
                verify_name = getattr(self, "session_name", "") or ""
                if not verify_name and isinstance(data, dict):
                    verify_name = data.get("meta", {}).get("session_name", "") if isinstance(data.get("meta"), dict) else ""
                if not _verify_hmac(encryption_key or "", raw, stored_hmac, session_name=verify_name):
                    return {"status": "integrity_error", "message": "Cookie file integrity check failed — file may have been tampered with"}
            elif isinstance(data, dict) and not data.get("encrypted") and "integrity" not in data and isinstance(data, dict):
                logger.warning("No integrity field in cookie file (legacy format); proceeding without verification")

            if cookies_list is None:
                cookies_list = []

            # Domain validation (#64)
            original_count = len(cookies_list)
            if allowed_domains is not None:
                cookies_list = _validate_cookie_domains(cookies_list, allowed_domains)
            filtered_count = original_count - len(cookies_list)

            self.cookies = cookies_list or []

            if self.browser_context and self.cookies:
                try:
                    await self.browser_context.add_cookies(self.cookies)
                except Exception as e:
                    return {"status": "partial", "loaded": len(self.cookies), "error": str(e)}

            result = {"status": "success", "cookies_loaded": len(self.cookies)}
            if filtered_count:
                result["filtered_domains"] = filtered_count
            return result
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def load_cookies_from_data(self, cookies_data: Any, encryption_key: Optional[str] = None, allowed_domains: Optional[List[str]] = None) -> Dict[str, Any]:
        """Load cookies from in-memory data (list / dict / JSON string or bytes).
        Supports optional decryption key for encrypted payloads (#82).
        Addresses P1 #145 (MCP cookies/state) + security.
        Integrity verification (#111): validates HMAC when present, warns on legacy data.
        Domain validation (#64): filters cookies to allowed_domains when provided.
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

            # Integrity check for plaintext payloads (#111)
            if isinstance(data, dict) and not data.get("encrypted") and "integrity" in data:
                stored_hmac = data["integrity"]
                payload_copy = {k: v for k, v in data.items() if k != "integrity"}
                raw = json.dumps(payload_copy, separators=(",", ":"), sort_keys=True).encode("utf-8")
                session_name = getattr(self, "session_name", "") or ""
                if not _verify_hmac(encryption_key or "", raw, stored_hmac, session_name=session_name):
                    return {"status": "integrity_error", "message": "Inline data integrity check failed — data may have been tampered with"}
            elif isinstance(data, dict) and not data.get("encrypted") and "integrity" not in data:
                logger.warning("No integrity field in inline data (legacy format); proceeding without verification")

            if cookies_list is None:
                if isinstance(data, list):
                    cookies_list = data
                elif isinstance(data, dict):
                    cookies_list = data.get("cookies", data.get("cookies_file_content", []))
                else:
                    cookies_list = []

            # Domain validation (#64)
            original_count = len(cookies_list) if cookies_list else 0
            if allowed_domains is not None and cookies_list:
                cookies_list = _validate_cookie_domains(cookies_list, allowed_domains)
            filtered_count = original_count - (len(cookies_list) if cookies_list else 0)

            self.cookies = cookies_list or []

            if self.browser_context and self.cookies:
                try:
                    await self.browser_context.add_cookies(self.cookies)
                except Exception as e:
                    return {"status": "partial", "loaded": len(self.cookies), "error": str(e)}

            result = {"status": "success", "cookies_loaded": len(self.cookies), "source": "inline_data"}
            if filtered_count:
                result["filtered_domains"] = filtered_count
            return result
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def is_cookie_expired(self, cookie: Dict, max_age_hours: int = 24) -> bool:
        """Check if a single cookie is expired (expiry in the past).

        Uses UTC-aware comparison to avoid timezone mismatch.
        A cookie with no expires field or expires=0 is a session cookie (not expired).
        """
        if "expires" not in cookie or not cookie["expires"]:
            return False  # session cookie — never expired by this check
        try:
            # Use UTC-aware datetime to match datetime.now(timezone.utc)
            expiry = datetime.fromtimestamp(cookie["expires"], tz=timezone.utc)
            now = datetime.now(timezone.utc)
            # Cookie is expired if its expiry time is in the past
            return expiry < now
        except (OSError, OverflowError, ValueError):
            return True  # treat badly-formed expires as expired for safety

    async def refresh_cookies_if_needed(self, max_age_hours: int = 8) -> Dict[str, Any]:
        """Check and report on cookie freshness (actual refresh usually requires re-auth)."""
        if not self.cookies:
            return {"status": "no_cookies"}

        now = datetime.now(timezone.utc)
        expired = 0

        for cookie in self.cookies:
            if "expires" in cookie and cookie["expires"]:
                try:
                    expiry = datetime.fromtimestamp(cookie["expires"], tz=timezone.utc)
                    if expiry < now:
                        expired += 1
                except (OSError, OverflowError, ValueError):
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
        # Try to get actual count from browser context for accuracy
        actual_count = len(self.cookies)
        if self.browser_context:
            try:
                ctx_cookies = await self.browser_context.cookies()
                actual_count = len(ctx_cookies)
            except Exception:
                pass  # fall back to in-memory count if context is unavailable

        self.cookies = []
        self.last_refresh = None

        if self.browser_context:
            try:
                await self.browser_context.clear_cookies()
                return {"status": "success", "cleared": actual_count, "context_cleared": True}
            except Exception as e:
                return {"status": "partial", "cleared": actual_count, "error": str(e)}

        return {"status": "success", "cleared": actual_count}

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

        try:
            path = _validate_path(cookies_path, must_exist_parent=False)
        except ValueError as e:
            return {"status": "error", "message": str(e)}

        # Support legacy/compat call style where encrypt flag is passed separately
        key = encryption_key
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
                # Plaintext (legacy compatible) + meta wrapper + integrity (#111)
                payload = {"cookies": self.cookies, "meta": meta}
                raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
                payload["integrity"] = _compute_hmac(encryption_key or "", raw, session_name=self.session_name if hasattr(self, "session_name") else "")
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

    async def export_session_bundle(self, session_name: str, bundle_path: str, encryption_key: Optional[str] = None) -> Dict[str, Any]:
        """Export full session + cookies for backup / transfer.
        Supports optional encryption_key for Fernet-encrypted bundles (#82 P1).
        Backward compatible (plain when no key).
        """
        # light_mode integration note: in AgentBrowser light_mode perf paths, omit encryption_key
        # for zero crypto overhead on bundles; encryption only on explicit key for security-sensitive exports.
        try:
            validated_bundle_path = _validate_path(bundle_path, must_exist_parent=False)
        except ValueError as e:
            return {"status": "error", "message": str(e)}

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

        validated_bundle_path.parent.mkdir(parents=True, exist_ok=True)

        cipher = self._get_cipher(encryption_key)
        try:
            if cipher:
                plain = json.dumps(bundle, separators=(",", ":")).encode("utf-8")
                token = cipher.encrypt(plain)
                payload = {
                    "encrypted": True,
                    "version": 1,
                    "data": token.decode("utf-8"),
                    "meta": {"exported_at": bundle.get("exported_at"), "bundle_for": session_name},
                }
                with open(validated_bundle_path, "w") as f:
                    json.dump(payload, f, indent=2)
                return {
                    "status": "success",
                    "bundle": str(validated_bundle_path),
                    "cookies_count": len(bundle.get("cookies", [])),
                    "encrypted": True,
                }
            else:
                # Plaintext bundle — add integrity (#111)
                raw = json.dumps(bundle, separators=(",", ":"), sort_keys=True).encode("utf-8")
                bundle["integrity"] = _compute_hmac(encryption_key or "", raw, session_name=session_name)
                with open(validated_bundle_path, "w") as f:
                    json.dump(bundle, f, indent=2)
                return {
                    "status": "success",
                    "bundle": str(validated_bundle_path),
                    "cookies_count": len(bundle.get("cookies", [])),
                }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def import_session_bundle(self, bundle_path: str, target_session_name: Optional[str] = None, encryption_key: Optional[str] = None, allowed_domains: Optional[List[str]] = None) -> Dict[str, Any]:
        """Import a bundle and create/resume session.
        Supports optional decryption when encryption_key provided (#82 P1).
        Backward compatible with plain bundles.
        Integrity verification (#73): validates HMAC on import, checks bundle structure.
        Domain validation (#64): filters cookies to allowed_domains when provided.
        """
        try:
            validated_bundle_path = _validate_path(bundle_path, must_exist_parent=True)
        except ValueError as e:
            return {"status": "error", "message": str(e)}

        if not validated_bundle_path.exists():
            return {"status": "error", "message": "Bundle not found"}

        try:
            with open(validated_bundle_path) as f:
                data = json.load(f)

            bundle = data
            cipher = self._get_cipher(encryption_key)
            if isinstance(data, dict) and data.get("encrypted") and cipher:
                try:
                    token = data["data"].encode()
                    decrypted = cipher.decrypt(token)
                    bundle = json.loads(decrypted)
                except InvalidToken:
                    return {"status": "error", "message": "Invalid encryption key or corrupted bundle file"}
                except Exception as e:
                    return {"status": "error", "message": f"Bundle decryption failed: {e}"}
            elif isinstance(data, dict) and data.get("encrypted"):
                return {"status": "error", "message": "Encrypted bundle but no encryption_key provided"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

        # Bundle structure validation (#73)
        if isinstance(bundle, dict):
            has_required = any(k in bundle for k in ("meta", "cookies", "version"))
            if not has_required:
                return {"status": "error", "message": "Bundle structure invalid: missing required keys (meta, cookies, or version)"}

        # Integrity check for plaintext bundles (#73)
        if isinstance(data, dict) and not data.get("encrypted") and "integrity" in data:
            stored_hmac = data["integrity"]
            payload_copy = {k: v for k, v in data.items() if k != "integrity"}
            raw = json.dumps(payload_copy, separators=(",", ":"), sort_keys=True).encode("utf-8")
            # Use the session name from the bundle's meta for verification
            # (same key used during export)
            bundle_meta = bundle.get("meta", {}) if isinstance(bundle, dict) else {}
            verify_name = bundle_meta.get("name", "") or target_session_name or ""
            if not _verify_hmac(encryption_key or "", raw, stored_hmac, session_name=verify_name):
                return {"status": "integrity_error", "message": "Bundle integrity check failed — bundle may have been tampered with"}
        elif isinstance(data, dict) and not data.get("encrypted") and "integrity" not in data:
            logger.warning("No integrity field in bundle (legacy format); proceeding without verification")

        meta = bundle.get("meta", {})
        name = target_session_name or meta.get("name", f"imported-{datetime.now().strftime('%Y%m%d%H%M')}")
        cookies = bundle.get("cookies", []) or bundle.get("cookies_file_content", [])

        # Domain validation (#64)
        original_count = len(cookies)
        if allowed_domains is not None:
            cookies = _validate_cookie_domains(cookies, allowed_domains)
        filtered_count = original_count - len(cookies)

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

        result = {
            "status": "success",
            "session": name,
            "cookies_imported": len(cookies),
        }
        if filtered_count:
            result["filtered_domains"] = filtered_count
        return result

    async def rotate_encryption_key(
        self,
        *,
        cookies_path: Optional[str] = None,
        bundle_path: Optional[str] = None,
        old_keys: List[Any] = None,
        new_key: str = None,
        target_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Rotate encryption key for a cookie file or session bundle (#270).

        Re-encrypts under the new_key using old_keys (str or list) for decryption.
        This is the supported way to perform key rotation without data loss.

        - Provide cookies_path for .json cookie files (from save_cookies_to_file)
        - Provide bundle_path for exported session bundles
        - target_path optional: write rotated to different location (else in-place overwrite)
        - All ops opt-in, secure (no key material logged)

        Returns status + details. Does NOT auto-delete originals.
        """
        if not new_key:
            return {"status": "error", "message": "new_key is required for rotation"}
        old_keys = old_keys or []
        paths_to_process = []
        if cookies_path:
            paths_to_process.append(("cookie", cookies_path))
        if bundle_path:
            paths_to_process.append(("bundle", bundle_path))

        results = []
        for kind, src_path in paths_to_process:
            p = Path(src_path)
            if not p.exists():
                results.append({"path": src_path, "status": "not_found"})
                continue
            try:
                with open(p) as f:
                    data = json.load(f)
                if not (isinstance(data, dict) and data.get("encrypted")):
                    results.append({"path": src_path, "status": "not_encrypted"})
                    continue

                token = data["data"].encode()
                decrypted = self._try_decrypt_with_keys(token, old_keys or [None])
                if decrypted is None:
                    results.append({"path": src_path, "status": "decrypt_failed"})
                    continue

                new_cipher = self._get_cipher(new_key)
                if new_cipher is None:
                    results.append({"path": src_path, "status": "new_key_invalid"})
                    continue
                plain = decrypted if isinstance(decrypted, (bytes, bytearray)) else str(decrypted).encode("utf-8")
                new_token = new_cipher.encrypt(plain)
                new_payload = {
                    "encrypted": True,
                    "version": data.get("version", 1),
                    "data": new_token.decode("utf-8"),
                    "meta": data.get("meta", {}),
                    "rotated_at": datetime.now(timezone.utc).isoformat(),
                    "rotated_from": "key-rotation-#270",
                }
                out_p = Path(target_path or src_path)
                out_p.parent.mkdir(parents=True, exist_ok=True)
                with open(out_p, "w") as f:
                    json.dump(new_payload, f, indent=2)
                results.append({"path": str(out_p), "status": "rotated", "kind": kind})
            except Exception as e:
                results.append({"path": src_path, "status": "error", "message": str(e)})

        return {
            "status": "success" if any(r.get("status") == "rotated" for r in results) else "partial",
            "results": results,
        }


class SessionOrchestrator:
    """High-level coordinator for multiple resilient sessions (MCP / agent use).

    Updated for MCP contract compatibility (#106 hygiene): accepts session_manager
    in constructor and exposes create/export/import for tests + MCP wrappers.
    """

    def __init__(self, session_manager: Optional[object] = None, cookie_manager: Optional["CookieManager"] = None):
        self.main_session_manager = session_manager
        # Allow wiring a real CookieManager (with browser_context) instead of creating a disconnected one.
        # This addresses part of the original duplication/broken state concerns in #30.
        self.cm = cookie_manager or CookieManager()
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

    async def export_session_bundle(self, session_name: str, bundle_path: str, encryption_key: Optional[str] = None) -> Dict[str, Any]:
        """Delegate for full MCP test / agent contract. Forwards encryption_key for #82 bundle encryption."""
        return await self.cm.export_session_bundle(session_name, bundle_path, encryption_key)

    async def import_session_bundle(self, bundle_path: str, target_session_name: Optional[str] = None, encryption_key: Optional[str] = None, allowed_domains: Optional[List[str]] = None) -> Dict[str, Any]:
        """Delegate for full MCP test / agent contract. Forwards encryption_key for #82 bundle encryption."""
        return await self.cm.import_session_bundle(bundle_path, target_session_name, encryption_key, allowed_domains=allowed_domains)

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
