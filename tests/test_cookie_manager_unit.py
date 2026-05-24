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
        key = "this-is-a-32-byte-secret-key!!"
        mgr.cookies = [{"name": "secure_cookie", "value": "secret", "domain": ".example.com"}]
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
        key = "this-is-a-32-byte-secret-key!!"
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
        key = "this-is-a-32-byte-secret-key!!"
        mgr.cookies = [{"name": "x", "value": "y"}]
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            asyncio.run(mgr.save_cookies_to_file(path, encryption_key=key))
            mgr2 = CookieManager()
            loaded = asyncio.run(mgr2.load_cookies(path, encryption_key="wrong-key-is-wrong!!"))
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
        key = "this-is-a-32-byte-secret-key!!"
        plain = b"hello world"
        token = mgr.encrypt_data(plain, key)
        assert token is not None
        assert token != plain
        decrypted = mgr.decrypt_data(token, key)
        assert decrypted == plain

    def test_decrypt_with_wrong_key(self):
        mgr = CookieManager()
        key1 = "key1-is-a-32-byte-secret!!!!!"
        key2 = "key2-is-a-32-byte-secret!!!!!"
        token = mgr.encrypt_data(b"data", key1)
        result = mgr.decrypt_data(token, key2)
        assert result is None

    def test_encrypt_without_key_returns_none(self):
        mgr = CookieManager()
        assert mgr.encrypt_data(b"data", None) is None

    def test_key_rotation_try_decrypt(self):
        mgr = CookieManager()
        key_old = "old-key-is-a-32-byte-secret!!"
        key_new = "new-key-is-a-32-byte-secret!!"
        token = mgr.encrypt_data(b"rotated-data", key_old)
        result = mgr._try_decrypt_with_keys(token, [key_new, key_old])
        assert result == b"rotated-data"

    def test_key_rotation_all_fail(self):
        mgr = CookieManager()
        key_old = "old-key-is-a-32-byte-secret!!"
        token = mgr.encrypt_data(b"data", key_old)
        result = mgr._try_decrypt_with_keys(token, ["wrong-key-is-a-32-char-key!!"])
        assert result is None
