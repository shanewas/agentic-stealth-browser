"""
TLS Fingerprint Spoofing Module
Provides realistic, region-aligned TLS ClientHello *profiles* (ciphers, extensions, curves, sig algos) for anti-detection.
Wired into AgentBrowser launch via recommended_args + region selection.

Limitation (resolves #114): Stock Playwright/Chromium does not allow direct control over the raw TLS ClientHello bytes on the wire.
This module reduces entropy and aligns high-level signals via launch flags (e.g. --enable-quic, --tls13-variant) and profile data.
It does NOT achieve bit-perfect wire-level ClientHello spoofing.
For stronger guarantees, users should layer utls (Go) + custom proxy or patched Chromium builds.
See also README table and https://github.com/shanewas/agentic-stealth-browser/issues/114

This module handles profile selection, logging, and launch arg recommendations. High-quality profiles based on real Chrome 124+.
"""

from typing import Dict, Any, Optional
from enum import Enum
from audit.logger import AuditLogger


class Region(Enum):
    US = "us"
    EU = "eu"
    JAPAN = "japan"
    KOREA = "korea"
    GLOBAL = "global"


class TLSFingerprintManager:
    """
    Manages realistic TLS fingerprints aligned with region profiles.
    Uses stable, high-quality fingerprints that match real Chrome instances.
    """

    # Realistic TLS profiles (based on common Chrome 124+ fingerprints)
    PROFILES = {
        Region.US: {
            "name": "chrome_124_windows_us",
            "description": "Windows 10/11, Chrome 124, US East Coast",
            "ciphers": [
                "TLS_AES_128_GCM_SHA256",
                "TLS_AES_256_GCM_SHA384",
                "TLS_CHACHA20_POLY1305_SHA256",
                "ECDHE-ECDSA-AES128-GCM-SHA256",
                "ECDHE-RSA-AES128-GCM-SHA256",
                "ECDHE-ECDSA-AES256-GCM-SHA384",
                "ECDHE-RSA-AES256-GCM-SHA384",
                "ECDHE-ECDSA-CHACHA20-POLY1305",
                "ECDHE-RSA-CHACHA20-POLY1305",
                "ECDHE-RSA-AES128-SHA",
                "ECDHE-RSA-AES256-SHA",
                "AES128-GCM-SHA256",
                "AES256-GCM-SHA384",
                "AES128-SHA",
                "AES256-SHA"
            ],
            "extensions": [
                "server_name", "extended_master_secret", "renegotiation_info",
                "supported_groups", "ec_point_formats", "session_ticket",
                "application_layer_protocol_negotiation", "status_request",
                "signature_algorithms", "signed_certificate_timestamp",
                "key_share", "psk_key_exchange_modes", "supported_versions",
                "compress_certificate", "application_settings"
            ],
            "elliptic_curves": ["X25519", "secp256r1", "secp384r1"],
            "signature_algorithms": [
                "ecdsa_secp256r1_sha256", "rsa_pss_rsae_sha256",
                "rsa_pkcs1_sha256", "ecdsa_secp384r1_sha384",
                "rsa_pss_rsae_sha384", "rsa_pkcs1_sha384",
                "rsa_pss_rsae_sha512", "rsa_pkcs1_sha512"
            ],
            "recommended_args": [
                "--enable-quic",
                "--tls13-variant=final",
            ]
        },
        Region.EU: {
            "name": "chrome_124_windows_eu",
            "description": "Windows 11, Chrome 124, Western Europe",
            "ciphers": [
                "TLS_AES_128_GCM_SHA256",
                "TLS_AES_256_GCM_SHA384",
                "TLS_CHACHA20_POLY1305_SHA256",
                "ECDHE-ECDSA-AES128-GCM-SHA256",
                "ECDHE-RSA-AES128-GCM-SHA256",
                "ECDHE-ECDSA-AES256-GCM-SHA384",
                "ECDHE-RSA-AES256-GCM-SHA384",
                "ECDHE-ECDSA-CHACHA20-POLY1305",
                "ECDHE-RSA-CHACHA20-POLY1305"
            ],
            "extensions": [
                "server_name", "extended_master_secret", "renegotiation_info",
                "supported_groups", "ec_point_formats", "session_ticket",
                "application_layer_protocol_negotiation", "status_request",
                "signature_algorithms", "key_share", "supported_versions"
            ],
            "elliptic_curves": ["X25519", "secp256r1", "secp384r1"],
            "signature_algorithms": [
                "ecdsa_secp256r1_sha256", "rsa_pss_rsae_sha256",
                "rsa_pkcs1_sha256", "ecdsa_secp384r1_sha384"
            ],
            "recommended_args": [
                "--enable-quic",
            ]
        },
        Region.JAPAN: {
            "name": "chrome_124_windows_japan",
            "description": "Windows 10, Chrome 124, Japan",
            "ciphers": [
                "TLS_AES_128_GCM_SHA256",
                "TLS_AES_256_GCM_SHA384",
                "TLS_CHACHA20_POLY1305_SHA256",
                "ECDHE-ECDSA-AES128-GCM-SHA256",
                "ECDHE-RSA-AES128-GCM-SHA256",
                "ECDHE-ECDSA-AES256-GCM-SHA384",
                "ECDHE-RSA-AES256-GCM-SHA384",
                "ECDHE-ECDSA-CHACHA20-POLY1305",
                "ECDHE-RSA-CHACHA20-POLY1305",
                "ECDHE-RSA-AES128-SHA256"
            ],
            "extensions": [
                "server_name", "extended_master_secret", "renegotiation_info",
                "supported_groups", "ec_point_formats", "session_ticket",
                "application_layer_protocol_negotiation", "status_request",
                "signature_algorithms", "key_share", "supported_versions",
                "compress_certificate"
            ],
            "elliptic_curves": ["X25519", "secp256r1", "secp384r1"],
            "signature_algorithms": [
                "ecdsa_secp256r1_sha256", "rsa_pss_rsae_sha256",
                "rsa_pkcs1_sha256", "ecdsa_secp384r1_sha384"
            ],
            "recommended_args": [
                "--enable-quic",
                "--tls13-variant=final",
            ]
        },
        Region.KOREA: {
            "name": "chrome_124_windows_korea",
            "description": "Windows 11, Chrome 124, South Korea",
            "ciphers": [
                "TLS_AES_128_GCM_SHA256",
                "TLS_AES_256_GCM_SHA384",
                "TLS_CHACHA20_POLY1305_SHA256",
                "ECDHE-ECDSA-AES128-GCM-SHA256",
                "ECDHE-RSA-AES128-GCM-SHA256",
                "ECDHE-ECDSA-AES256-GCM-SHA384",
                "ECDHE-RSA-AES256-GCM-SHA384"
            ],
            "extensions": [
                "server_name", "extended_master_secret", "renegotiation_info",
                "supported_groups", "ec_point_formats", "session_ticket",
                "application_layer_protocol_negotiation", "status_request",
                "signature_algorithms", "key_share", "supported_versions"
            ],
            "elliptic_curves": ["X25519", "secp256r1"],
            "signature_algorithms": [
                "ecdsa_secp256r1_sha256", "rsa_pss_rsae_sha256",
                "rsa_pkcs1_sha256"
            ],
            "recommended_args": [
                "--enable-quic",
            ]
        },
        Region.GLOBAL: {
            "name": "chrome_124_windows_generic",
            "description": "Generic high-entropy Windows Chrome profile",
            "ciphers": [
                "TLS_AES_128_GCM_SHA256",
                "TLS_AES_256_GCM_SHA384",
                "TLS_CHACHA20_POLY1305_SHA256",
                "ECDHE-ECDSA-AES128-GCM-SHA256",
                "ECDHE-RSA-AES128-GCM-SHA256",
                "ECDHE-ECDSA-AES256-GCM-SHA384",
                "ECDHE-RSA-AES256-GCM-SHA384",
                "ECDHE-ECDSA-CHACHA20-POLY1305",
                "ECDHE-RSA-CHACHA20-POLY1305"
            ],
            "extensions": [
                "server_name", "extended_master_secret", "renegotiation_info",
                "supported_groups", "ec_point_formats", "session_ticket",
                "application_layer_protocol_negotiation", "status_request",
                "signature_algorithms", "key_share", "supported_versions"
            ],
            "elliptic_curves": ["X25519", "secp256r1", "secp384r1"],
            "signature_algorithms": [
                "ecdsa_secp256r1_sha256", "rsa_pss_rsae_sha256",
                "rsa_pkcs1_sha256", "ecdsa_secp384r1_sha384"
            ],
            "recommended_args": [
                "--enable-quic",
                "--tls13-variant=final",
            ]
        }
    }

    def __init__(self, region: Region = Region.GLOBAL, session_name: Optional[str] = None):
        self.region = region
        self.session_name = session_name or "default"
        self.logger = AuditLogger(session_name or "tls")
        self.current_profile = self.PROFILES.get(region, self.PROFILES[Region.GLOBAL])

    def get_profile(self) -> Dict[str, Any]:
        """Returns the current TLS profile for the selected region."""
        return self.current_profile

    def get_launch_args(self) -> list:
        """Returns recommended Chromium launch arguments for this TLS profile."""
        args = self.current_profile.get("recommended_args", [])
        # Add some entropy reduction
        args.extend([
            "--disable-blink-features=AutomationControlled",
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ])
        return args

    def log_fingerprint_choice(self):
        """Logs the chosen TLS fingerprint for audit purposes."""
        profile = self.current_profile
        self.logger.log_action(
            action="tls_fingerprint_selected",
            details={
                "region": self.region.value,
                "profile_name": profile["name"],
                "description": profile["description"],
                "cipher_count": len(profile["ciphers"]),
                "extension_count": len(profile["extensions"])
            }
        )

    @staticmethod
    def get_region_for_locale(locale: str) -> Region:
        """Maps locale to recommended TLS region."""
        locale = locale.lower()
        if "ja" in locale or "jp" in locale:
            return Region.JAPAN
        elif "ko" in locale or "kr" in locale:
            return Region.KOREA
        elif any(x in locale for x in ["de", "fr", "es", "it", "nl"]):
            return Region.EU
        elif "en-us" in locale or "en" in locale:
            return Region.US
        return Region.GLOBAL

    def explain_limitations(self) -> str:
        """Explicit documentation of TLS capabilities vs limits (for #114).
        Call this in debug/audit flows for evidence.
        """
        return ("High-quality region-aligned cipher/extension/curve profiles + launch arg recommendations. "
                "Does NOT provide true low-level ClientHello wire spoofing in stock Playwright. "
                "See module docstring and issue #114 for details on utls/proxy options.")


# Convenience function
def get_tls_manager(region: str = "global", session_name: Optional[str] = None) -> TLSFingerprintManager:
    region_map = {
        "us": Region.US,
        "eu": Region.EU,
        "japan": Region.JAPAN,
        "korea": Region.KOREA,
        "global": Region.GLOBAL
    }
    r = region_map.get(region.lower(), Region.GLOBAL)
    return TLSFingerprintManager(r, session_name)