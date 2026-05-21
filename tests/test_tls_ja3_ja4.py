"""
Tests for TLS JA3/JA4 fingerprinting.
Addresses #75: TLS fingerprinting JA3/JA4 support.
"""

import pytest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from stealth.tls_ja3_ja4 import JA3Fingerprint, JA4Fingerprint


class TestJA3Fingerprint:
    """JA3 fingerprint tests."""

    def test_generate_ja3_string(self):
        ja3 = JA3Fingerprint.generate_ja3(
            "772", ["4865", "4866"], ["0", "11"], ["29"], ["0"]
        )
        assert ja3 == "772,4865,4866,0,11,29,0"

    def test_generate_ja3_hash(self):
        ja3_str = "772,4865,4866,0,11,29,0"
        ja3_hash = JA3Fingerprint.generate_ja3_hash(ja3_str)
        assert len(ja3_hash) == 32  # MD5 hex length

    def test_chrome_ja3_has_required_fields(self):
        chrome = JA3Fingerprint.get_chrome_ja3()
        assert "ja3_string" in chrome
        assert "ja3_hash" in chrome
        assert "browser" in chrome
        assert "Chrome" in chrome["browser"]

    def test_firefox_ja3_has_required_fields(self):
        firefox = JA3Fingerprint.get_firefox_ja3()
        assert "ja3_string" in firefox
        assert "ja3_hash" in firefox
        assert "browser" in firefox
        assert "Firefox" in firefox["browser"]

    def test_chrome_and_firefox_have_different_ja3(self):
        chrome = JA3Fingerprint.get_chrome_ja3()
        firefox = JA3Fingerprint.get_firefox_ja3()
        assert chrome["ja3_hash"] != firefox["ja3_hash"]

    def test_compare_ja3_same_strings(self):
        # Proper JA3 format: sslVersion,cipher,extension,curve,pointFormat
        ja3 = "772,4865,0,29,0"
        result = JA3Fingerprint.compare_ja3(ja3, ja3)
        assert result["match"] is True
        assert result["ssl_version_match"] is True

    def test_compare_ja3_different_strings(self):
        ja3_a = "772,4865,0,29,0"
        ja3_b = "772,4866,0,29,0"
        result = JA3Fingerprint.compare_ja3(ja3_a, ja3_b)
        assert result["match"] is False

    def test_compare_ja3_invalid_format(self):
        result = JA3Fingerprint.compare_ja3("invalid", "also-invalid")
        assert "error" in result


class TestJA4Fingerprint:
    """JA4 fingerprint tests."""

    def test_generate_ja4_string(self):
        ja4 = JA4Fingerprint.generate_ja4()
        assert ja4 is not None
        assert len(ja4) > 0

    def test_ja4_format_starts_correctly(self):
        ja4 = JA4Fingerprint.generate_ja4()
        assert ja4.startswith("q13d")

    def test_chrome_ja4_has_required_fields(self):
        chrome = JA4Fingerprint.get_chrome_ja4()
        assert "ja4_string" in chrome
        assert "browser" in chrome

    def test_different_ciphers_produce_different_ja4(self):
        ja4_a = JA4Fingerprint.generate_ja4(ciphers=["1301", "1302", "1303", "1304"])
        ja4_b = JA4Fingerprint.generate_ja4(ciphers=["1305", "1306", "1307", "1308"])
        assert ja4_a != ja4_b
