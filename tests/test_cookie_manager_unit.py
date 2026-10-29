"""
Unit tests for CookieManager: validation, expiry, domain filtering, encryption, integrity.

Covers:
- Cookie expiry detection
- Cookie health calculation
- Domain filtering
- Path validation
- HMAC integrity
- Encryption/decryption
- Key rotation
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import json
import tempfile
import asyncio
from datetime import datetime, timezone

import pytest

from sessions.cookie_manager import (
    CookieManager,
    SessionOrchestrator,
    _validate_path,
    _compute_hmac,
    _verify_hmac,
    _validate_cookie_domains,
)


class TestPathValidation:
    def test_valid_path(self):
        p = _validate_path("/tmp/cookies.json", must_exist_parent=True)
        assert p.name == "cookies.json"

    def test_invalid_extension(self):
        with pytest.raises(ValueError, match="must end with"):
            _validate_path("/tmp/cookies.txt")

    def test_path_traversal_blocked(self):
        with pytest.raises(ValueError, match="traversal"):
            _validate_path("/tmp/../etc/cookies.json")

    def test_empty_path(self):
        with pytest.raises(ValueError):
            _validate_path("")


class TestDomainFiltering:
    def test_allowed_domain_match(self):
        cookies = [
            {"domain": ".example.com", "name": "a"},
            {"domain": "sub.example.com", "name": "b"},
            {"domain": "other.com", "name": "c"},
        ]
        result = _validate_cookie_domains(cookies, ["example.com"])
        assert len(result) == 2
        assert result[0]["name"] == "a"
        assert result[1]["name"] == "b"

    def test_no_domain_cookie_kept(self):
        cookies = [
            {"name": "session_only"},
            {"domain": "bad.com", "name": "track"},
        ]
        result = _validate_cookie_domains(cookies, ["good.com"])
        assert len(result) == 1
        assert result[0]["name"] == "session_only"

    def test_none_allowed_is_noop(self):
        cookies = [
            {"domain": "example.com", "name": "a"},
            {"domain": "other.com", "name": "b"},
        ]
        result = _validate_cookie_domains(cookies, None)
        assert len(result) == 2

    def test_strips_leading_dot(self):
        cookies = [
            {"domain": ".linkedin.com", "name": "li"},
        ]
        result = _validate_cookie_domains(cookies, ["linkedin.com"])
        assert len(result) == 1


class TestHMACIntegrity:
    def test_compute_and_verify(self):
        data = b'{"cookies": []}'
        h = _compute_hmac("secret", data)
        assert _verify_hmac("secret", data, h)

    def test_tampered_data_fails(self):
        data = b'{"cookies": []}'
        h = _compute_hmac("secret", data)
        assert not _verify_hmac("secret", b'{"cookies": [1]}', h)

    def test_wrong_key_fails(self):
        data = b'{"cookies": []}'
        h = _compute_hmac("secret", data)
        assert not _verify_hmac("wrong", data, h)


class TestCookieExpiry:
    def test_session_cookie_not_expired(self):
        mgr = CookieManager()
        cookie = {"name": "session", "expires": 0}
        assert not mgr.is_cookie_expired(cookie)

    def test_future_cookie_not_expired(self):
        mgr = CookieManager()
        future = int(datetime.now(timezone.utc).timestamp()) + 3600
        cookie = {"name": "valid", "expires": future}
        assert not mgr.is_cookie_expired(cookie)

    def test_past_cookie_expired(self):
        mgr = CookieManager()
        past = int(datetime.now(timezone.utc).timestamp()) - 3600
        cookie = {"name": "expired", "expires": past}
        assert mgr.is_cookie_expired(cookie)

    def test_missing_expires_not_expired(self):
        mgr = CookieManager()
        cookie = {"name": "noexpiry"}
        assert not mgr.is_cookie_expired(cookie)

    def test_invalid_expires_treated_as_expired(self):
        mgr = CookieManager()
        cookie = {"name": "bad", "expires": 999999999999999}
        assert mgr.is_cookie_expired(cookie)


class TestCookieHealth:
    def test_empty_health(self):
        mgr = CookieManager()
        health = asyncio.run(mgr.get_cookie_health())
        assert health["status"] == "no_cookies"
        assert health["total"] == 0

    def test_healthy_cookies(self):
        mgr = CookieManager()
        future = int(datetime.now(timezone.utc).timestamp()) + 86400
        mgr.cookies = [
            {"name": "a", "expires": future, "secure": True, "httpOnly": True},
            {"name": "b", "expires": future, "secure": False, "httpOnly": False},
        ]
        health = asyncio.run(mgr.get_cookie_health())
        assert health["total"] == 2
        assert health["secure"] == 1
        assert health["http_only"] == 1
        assert health["expired"] == 0

    def test_degraded_with_expired(self):
        mgr = CookieManager()
        past = int(datetime.now(timezone.utc).timestamp()) - 3600
        mgr.cookies = [
            {"name": "expired", "expires": past},
        ]
        health = asyncio.run(mgr.get_cookie_health())
        assert health["status"] == "degraded"
        assert health["expired"] == 1


class TestCookieManagerSaveLoad:
    def test_save_plain_and_load(self):
        mgr = CookieManager()
        mgr.cookies = [{"name": "test", "value": "val", "domain": "example.com"}]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            result = asyncio.run(mgr.save_cookies_to_file(path))
            assert result["status"] == "success"
            mgr2 = CookieManager()
            loaded = asyncio.run(mgr2.load_cookies(path))
            assert loaded["status"] == "success"
            assert loaded["cookies_loaded"] == 1
        finally:
            Path(path).unlink(missing_ok=True)

    def test_save_and_load_with_encryption(self):
        mgr = CookieManager()
        key = "this-is-a-32-byte-secret-key-xx!"
        mgr.cookies = [
            {"name": "secure_cookie", "value": "secret", "domain": ".example.com"}
        ]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            result = asyncio.run(mgr.save_cookies_to_file(path, encryption_key=key))
            assert result["encrypted"] is True
            mgr2 = CookieManager()
            loaded = asyncio.run(mgr2.load_cookies(path, encryption_key=key))
            assert loaded["status"] == "success"
            assert loaded["cookies_loaded"] == 1
        finally:
            Path(path).unlink(missing_ok=True)

    def test_encrypted_file_fails_without_key(self):
        mgr = CookieManager()
        key = "this-is-a-32-byte-secret-key-xx!"
        mgr.cookies = [{"name": "x", "value": "y"}]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            asyncio.run(mgr.save_cookies_to_file(path, encryption_key=key))
            mgr2 = CookieManager()
            loaded = asyncio.run(mgr2.load_cookies(path))
            assert loaded["status"] == "error"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_encrypted_file_fails_with_wrong_key(self):
        mgr = CookieManager()
        key = "this-is-a-32-byte-secret-key-xx!"
        mgr.cookies = [{"name": "x", "value": "y"}]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            asyncio.run(mgr.save_cookies_to_file(path, encryption_key=key))
            mgr2 = CookieManager()
            loaded = asyncio.run(
                mgr2.load_cookies(path, encryption_key="wrong-key-is-wrong!!")
            )
            assert loaded["status"] == "error"
        finally:
            Path(path).unlink(missing_ok=True)

    def test_save_no_cookies(self):
        mgr = CookieManager()
        result = asyncio.run(mgr.save_cookies_to_file("/tmp/nonexist/cookies.json"))
        assert result["status"] == "no_cookies"

    def test_key_too_short_raises(self):
        mgr = CookieManager()
        with pytest.raises(ValueError, match="too short"):
            mgr._get_cipher("short")

    def test_load_nonexistent_file(self):
        mgr = CookieManager()
        result = asyncio.run(mgr.load_cookies("/tmp/nonexistent_cookies.json"))
        assert result["status"] == "error"

    def test_load_invalid_path(self):
        mgr = CookieManager()
        result = asyncio.run(mgr.load_cookies(""))
        assert result["status"] == "error"


class _FakeContext:
    def __init__(self, cookies):
        self._cookies = cookies
        self.calls = 0

    async def cookies(self):
        self.calls += 1
        return list(self._cookies)


class TestCookieManagerLiveContextSync:
    def test_save_refreshes_stale_in_memory_cookies(self, tmp_path):
        live = [{"name": "live", "value": "1", "domain": "example.com"}]
        ctx = _FakeContext(live)
        mgr = CookieManager(browser_context=ctx)
        mgr.cookies = [{"name": "stale", "value": "old", "domain": "example.com"}]
        path = str(tmp_path / "cookies.json")
        result = asyncio.run(mgr.save_cookies_to_file(path))
        assert result["status"] == "success"
        assert result["saved"] == 1
        assert ctx.calls == 1
        assert mgr.cookies == live
        with open(path) as f:
            payload = json.load(f)
        assert payload["cookies"] == live

    def test_save_succeeds_when_only_live_context_has_cookies(self, tmp_path):
        ctx = _FakeContext([{"name": "live", "value": "1"}])
        mgr = CookieManager(browser_context=ctx)
        result = asyncio.run(mgr.save_cookies_to_file(str(tmp_path / "c.json")))
        assert result["status"] == "success"
        assert result["saved"] == 1

    def test_save_no_context_keeps_no_cookies(self, tmp_path):
        mgr = CookieManager()
        result = asyncio.run(mgr.save_cookies_to_file(str(tmp_path / "c.json")))
        assert result["status"] == "no_cookies"

    def test_save_live_empty_context_is_no_cookies(self, tmp_path):
        mgr = CookieManager(browser_context=_FakeContext([]))
        mgr.cookies = [{"name": "stale"}]
        result = asyncio.run(mgr.save_cookies_to_file(str(tmp_path / "c.json")))
        assert result["status"] == "no_cookies"

    def test_agent_browser_wrapper_saves_live_cookies(self, tmp_path):
        from core.agent_browser import AgentBrowser

        live = [{"name": "live", "value": "1", "domain": "example.com"}]
        ctx = _FakeContext(live)
        browser = AgentBrowser(session_name="cookie-live-sync-test")
        browser.browser = ctx
        browser.cookie_manager = CookieManager()
        browser.cookie_manager.cookies = [{"name": "stale"}]
        path = str(tmp_path / "wrapped.json")
        result = asyncio.run(browser.save_cookies_to_file(path))
        assert result["status"] == "success"
        assert ctx.calls == 1
        with open(path) as f:
            assert json.load(f)["cookies"] == live

    def test_get_cookie_health_refreshes_from_context(self):
        future = int(datetime.now(timezone.utc).timestamp()) + 86400
        ctx = _FakeContext([{"name": "live", "expires": future, "secure": True}])
        mgr = CookieManager(browser_context=ctx)
        mgr.cookies = []
        health = asyncio.run(mgr.get_cookie_health())
        assert health["total"] == 1
        assert health["secure"] == 1


class TestCookieManagerClear:
    def test_clear_cookies_idempotent(self):
        mgr = CookieManager()
        mgr.cookies = [{"name": "a"}]
        result = asyncio.run(mgr.clear_cookies())
        assert result["status"] == "success"
        assert len(mgr.cookies) == 0
        # Idempotent
        result2 = asyncio.run(mgr.clear_cookies())
        assert result2["status"] == "success"


class TestEncryptDecrypt:
    def test_encrypt_decrypt_roundtrip(self):
        mgr = CookieManager()
        key = "this-is-a-32-byte-secret-key-xx!"
        plain = b"hello world"
        token = mgr.encrypt_data(plain, key)
        assert token is not None
        assert token != plain
        decrypted = mgr.decrypt_data(token, key)
        assert decrypted == plain

    def test_decrypt_with_wrong_key(self):
        mgr = CookieManager()
        key1 = "key1-is-a-32-byte-secret-!!!!aby"
        key2 = "key2-is-a-32-byte-secret!!!!!aby"
        token = mgr.encrypt_data(b"data", key1)
        result = mgr.decrypt_data(token, key2)
        assert result is None

    def test_encrypt_without_key_returns_none(self):
        mgr = CookieManager()
        assert mgr.encrypt_data(b"data", None) is None

    def test_key_rotation_try_decrypt(self):
        mgr = CookieManager()
        key_old = "old-key-is-a-32-byte-secret-!!ab"
        key_new = "new-key-is-a-32-byte-secret-!!ab"
        token = mgr.encrypt_data(b"rotated-data", key_old)
        result = mgr._try_decrypt_with_keys(token, [key_new, key_old])
        assert result == b"rotated-data"

    def test_key_rotation_all_fail(self):
        mgr = CookieManager()
        key_old = "old-key-is-a-32-byte-secret-!!ab"
        token = mgr.encrypt_data(b"data", key_old)
        result = mgr._try_decrypt_with_keys(token, ["wrong-key-is-a-32-char-key-xx!ab"])
        assert result is None


class TestPlaintextBundleIntegrity:
    def test_forged_resigned_bundle_not_claimed_verified(self, tmp_path):
        mgr = CookieManager()
        mgr.create_resilient_session("sess-a")
        mgr.cookie_managers["sess-a"].browser_context = _FakeContext(
            [{"name": "c", "value": "orig", "domain": "example.com"}]
        )
        bundle_path = tmp_path / "bundle.json"
        exported = asyncio.run(
            mgr.export_session_bundle("sess-a", str(bundle_path))
        )
        assert exported["status"] == "success"

        bundle = json.loads(bundle_path.read_text())
        bundle["cookies"][0]["value"] = "forged"
        # Re-sign exactly as an attacker with only the bundle can: the key
        # is derived from bundle-supplied name + bundle-stored salt.
        payload = {
            k: v for k, v in bundle.items() if k not in ("integrity", "_hmac_salt")
        }
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
        bundle["integrity"] = _compute_hmac(
            "",
            raw,
            session_name=bundle["meta"]["name"],
            salt=bytes.fromhex(bundle["_hmac_salt"]),
        )
        bundle_path.write_text(json.dumps(bundle))

        importer = CookieManager()
        result = asyncio.run(
            importer.import_session_bundle(str(bundle_path), "imported-a")
        )

        # Honest-labelling route: accepted, but never claimed verified.
        assert result["status"] == "success"
        assert result["integrity_verified"] is False
        assert result["integrity"] == "unverified"


class TestMalformedBundleImport:
    def test_list_bundle_returns_error_dict(self, tmp_path):
        bundle_path = tmp_path / "bundle.json"
        bundle_path.write_text(json.dumps([1, 2, 3]))
        result = asyncio.run(
            CookieManager().import_session_bundle(str(bundle_path), "x")
        )
        assert result["status"] == "error"

    def test_non_dict_meta_returns_error_dict(self, tmp_path):
        bundle_path = tmp_path / "bundle.json"
        bundle_path.write_text(json.dumps({"meta": "x", "cookies": []}))
        result = asyncio.run(
            CookieManager().import_session_bundle(str(bundle_path), "x")
        )
        assert result["status"] == "error"


class TestSessionOrchestratorIsolation:
    def test_sessions_have_distinct_managers_and_cookie_jars(self, tmp_path):
        orch = SessionOrchestrator()
        orch.create_resilient_session("orch-a")
        orch.create_resilient_session("orch-b")
        assert orch.cookie_managers["orch-a"] is not orch.cookie_managers["orch-b"]
        assert orch.cookie_managers["orch-a"] is not orch.cm
        assert orch.cookie_managers["orch-b"] is not orch.cm

        cookies_path = tmp_path / "cookies.json"
        cookies_path.write_text(
            json.dumps([{"name": "only-a", "value": "1", "domain": "example.com"}])
        )
        asyncio.run(orch.start_session("orch-a", cookies_path=str(cookies_path)))

        assert [c["name"] for c in orch.cookie_managers["orch-a"].cookies] == [
            "only-a"
        ]
        assert orch.cookie_managers["orch-b"].cookies == []
