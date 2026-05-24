"""
TLS Fingerprint JA3/JA4 Support
Addresses #75: Add deeper low-level TLS fingerprinting support (JA3/JA4 style) as an optional backend.

Provides JA3/JA4 string generation and comparison for TLS fingerprint analysis.
"""

import hashlib
from typing import Dict, List, Any


class JA3Fingerprint:
    """Generate and analyze JA3 TLS fingerprints.

    JA3 string format: SSLVersion,Cipher,SSLExtension,EllipticCurve,EllipticCurvePointFormat
    Reference: https://github.com/salesforce/ja3
    """

    # Chrome 124 TLS fingerprint components
    CHROME_124 = {
        "ssl_version": "772",  # TLS 1.3
        "ciphers": [
            "4865",
            "4866",
            "4867",
            "4868",  # TLS 1.3 cipher suites
            "49195",
            "49199",
            "49196",
            "49200",  # TLS 1.2 ECDHE-ECDSA/AES
            "52392",
            "52393",  # TLS 1.2 ECDHE-ECDSA/CHACHA20
            "49171",
            "49172",
            "49161",
            "49162",  # TLS 1.2 ECDHE-RSA
            "49187",
            "49188",
            "49177",
            "49178",  # TLS 1.2 DHE
            "156",
            "157",
            "47",
            "53",  # TLS 1.2 AES128/256
        ],
        "extensions": [
            "0",
            "11",
            "10",
            "35",
            "16",
            "22",
            "23",
            "13",
            "43",
            "45",
            "51",
            "17513",
            "27",
            "18",
            "65281",
            "65037",
        ],
        "curves": ["29", "23", "24"],  # x25519, secp256r1, secp384r1
        "point_formats": ["0"],  # uncompressed
    }

    FIREFOX_125 = {
        "ssl_version": "772",
        "ciphers": [
            "4865",
            "4867",
            "4866",
            "4868",
            "49195",
            "49196",
            "49199",
            "49200",
            "52393",
            "52392",
            "49171",
            "49172",
            "49161",
            "49162",
            "156",
            "157",
            "47",
            "53",
        ],
        "extensions": [
            "0",
            "11",
            "10",
            "16",
            "22",
            "23",
            "13",
            "43",
            "45",
            "51",
            "27",
            "17513",
            "65037",
            "18",
            "65281",
        ],
        "curves": ["29", "23", "24"],
        "point_formats": ["0"],
    }

    @classmethod
    def generate_ja3(
        cls,
        ssl_version: str,
        ciphers: List[str],
        extensions: List[str],
        curves: List[str],
        point_formats: List[str],
    ) -> str:
        """Generate JA3 string from TLS components."""
        return f"{ssl_version},{','.join(ciphers)},{','.join(extensions)},{','.join(curves)},{','.join(point_formats)}"

    @classmethod
    def generate_ja3_hash(cls, ja3_string: str) -> str:
        """Generate MD5 hash of JA3 string."""
        return hashlib.md5(ja3_string.encode()).hexdigest()

    @classmethod
    def get_chrome_ja3(cls) -> Dict[str, str]:
        """Get Chrome 124 JA3 fingerprint."""
        ja3_str = cls.generate_ja3(
            cls.CHROME_124["ssl_version"],
            cls.CHROME_124["ciphers"],
            cls.CHROME_124["extensions"],
            cls.CHROME_124["curves"],
            cls.CHROME_124["point_formats"],
        )
        return {
            "ja3_string": ja3_str,
            "ja3_hash": cls.generate_ja3_hash(ja3_str),
            "browser": "Chrome 124",
        }

    @classmethod
    def get_firefox_ja3(cls) -> Dict[str, str]:
        """Get Firefox 125 JA3 fingerprint."""
        ja3_str = cls.generate_ja3(
            cls.FIREFOX_125["ssl_version"],
            cls.FIREFOX_125["ciphers"],
            cls.FIREFOX_125["extensions"],
            cls.FIREFOX_125["curves"],
            cls.FIREFOX_125["point_formats"],
        )
        return {
            "ja3_string": ja3_str,
            "ja3_hash": cls.generate_ja3_hash(ja3_str),
            "browser": "Firefox 125",
        }

    @classmethod
    def compare_ja3(cls, ja3_a: str, ja3_b: str) -> Dict[str, Any]:
        """Compare two JA3 strings and return differences."""
        parts_a = ja3_a.split(",")
        parts_b = ja3_b.split(",")

        if len(parts_a) != 5 or len(parts_b) != 5:
            return {"error": "Invalid JA3 string format"}

        return {
            "match": ja3_a == ja3_b,
            "ssl_version_match": parts_a[0] == parts_b[0],
            "cipher_count_a": len(parts_a[1].split(",")),
            "cipher_count_b": len(parts_b[1].split(",")),
            "extension_count_a": len(parts_a[2].split(",")),
            "extension_count_b": len(parts_b[2].split(",")),
            "hash_a": cls.generate_ja3_hash(ja3_a),
            "hash_b": cls.generate_ja3_hash(ja3_b),
        }


class JA4Fingerprint:
    """Generate JA4 TLS fingerprints (next-gen after JA3).

    JA4 format: {protocol}_{tls_version}_{sni}_{alpn}_{ciphers}_{extensions}_{signature_algorithms}
    Reference: https://github.com/FoxIO-LLC/ja4
    """

    @classmethod
    def generate_ja4(
        cls,
        protocol: str = "q",
        tls_version: str = "13",
        sni: str = "d",
        alpn: str = "h2",
        ciphers: List[str] = None,
        extensions: List[str] = None,
        sig_algs: List[str] = None,
    ) -> str:
        """Generate JA4 fingerprint string."""
        ciphers = ciphers or ["1301", "1302", "1303"]
        extensions = extensions or ["0000", "0005", "000a"]
        sig_algs = sig_algs or ["0403", "0804", "0401"]

        # Take first 2 and last 2 ciphers/extensions
        cipher_part = (
            "".join(sorted(ciphers[:2] + ciphers[-2:]))
            if len(ciphers) >= 4
            else "".join(sorted(ciphers))
        )
        ext_part = (
            "".join(sorted(extensions[:2] + extensions[-2:]))
            if len(extensions) >= 4
            else "".join(sorted(extensions))
        )
        sig_part = (
            "".join(sorted(sig_algs[:2] + sig_algs[-2:]))
            if len(sig_algs) >= 4
            else "".join(sorted(sig_algs))
        )

        return f"{protocol}{tls_version}{sni}{alpn[0]}{len(ciphers):02d}{len(extensions):02d}{cipher_part}_{ext_part}_{sig_part}"

    @classmethod
    def get_chrome_ja4(cls) -> Dict[str, str]:
        """Get Chrome-like JA4 fingerprint."""
        ja4 = cls.generate_ja4(
            ciphers=[
                "1301",
                "1302",
                "1303",
                "c02b",
                "c02f",
                "c02c",
                "c030",
                "cca9",
                "cca8",
                "c013",
                "c014",
                "009c",
                "009d",
                "002f",
                "0035",
            ],
            extensions=[
                "0000",
                "0005",
                "000a",
                "000b",
                "0010",
                "0017",
                "001b",
                "0023",
                "002d",
                "002f",
                "0033",
                "4469",
                "0015",
                "0012",
                "ff01",
                "0000",
            ],
            sig_algs=["0403", "0804", "0401", "0503", "0805", "0501", "0806", "0601"],
        )
        return {
            "ja4_string": ja4,
            "browser": "Chrome 124",
        }
