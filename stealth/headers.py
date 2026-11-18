"""
Header & TLS Fingerprint Alignment
Makes the browser look like a real Chrome instance at the network level
"""

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional


@lru_cache(maxsize=1)
def bundled_chrome_version() -> Optional[str]:
    """Full version of the Chromium build Playwright will launch.

    Playwright ships the version in its driver package (browsers.json), so
    this is known before launch and tracks the installed Playwright instead
    of a hardcoded string. Returns None when it cannot be determined.
    """
    try:
        import playwright

        path = Path(playwright.__file__).parent / "driver" / "package" / "browsers.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data.get("browsers", []):
            if entry.get("name") == "chromium" and entry.get("browserVersion"):
                return str(entry["browserVersion"])
    except Exception:
        pass
    return None


def align_user_agent(user_agent: str, version: Optional[str] = None) -> str:
    """Rewrite a UA string's Chrome token to the bundled Chromium major.

    Persona profiles pin a Chrome version for their identity; if that pin
    drifts from the browser actually launched, the UA string contradicts
    navigator.userAgentData (which the browser generates from its real
    version) and the pair is trivially detectable. The reduced-UA form
    Chrome/<major>.0.0.0 is what current Chrome itself sends.
    """
    version = version or bundled_chrome_version()
    if not version:
        return user_agent
    major = version.split(".")[0]
    if not major.isdigit():
        return user_agent
    return re.sub(
        r"(HeadlessChrome|Chrome)/\d+(?:\.\d+){0,3}",
        rf"\1/{major}.0.0.0",
        user_agent,
    )


def align_client_hints(
    headers: Dict[str, str], version: Optional[str] = None
) -> Dict[str, str]:
    """Rewrite Sec-Ch-Ua / Sec-Ch-Ua-Full-Version-List to the bundled Chromium.

    Only the Chromium and Google Chrome brands are touched; the Not-A.Brand
    entry is a deliberate GREASE value and must stay as-is.
    """
    version = version or bundled_chrome_version()
    if not version:
        return headers
    major = version.split(".")[0]
    if not major.isdigit():
        return headers
    out = dict(headers)
    if "Sec-Ch-Ua" in out:
        ua = out["Sec-Ch-Ua"]
        ua = re.sub(r'("Chromium";v=")\d+(")', rf"\g<1>{major}\g<2>", ua)
        ua = re.sub(r'("Google Chrome";v=")\d+(")', rf"\g<1>{major}\g<2>", ua)
        out["Sec-Ch-Ua"] = ua
    if "Sec-Ch-Ua-Full-Version-List" in out:
        fvl = out["Sec-Ch-Ua-Full-Version-List"]
        fvl = re.sub(r'("Chromium";v=")[\d.]+(")', rf"\g<1>{version}\g<2>", fvl)
        fvl = re.sub(r'("Google Chrome";v=")[\d.]+(")', rf"\g<1>{version}\g<2>", fvl)
        out["Sec-Ch-Ua-Full-Version-List"] = fvl
    if "User-Agent" in out:
        out["User-Agent"] = align_user_agent(out["User-Agent"], version)
    return out


def get_realistic_headers() -> Dict[str, str]:
    """Return headers that closely match real Chrome on Windows (improved client hints for #231)"""
    return align_client_hints(
        {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Ch-Ua-Platform-Version": '"15.0.0"',
            "Sec-Ch-Ua-Full-Version-List": '"Chromium";v="124.0.6367.60", "Google Chrome";v="124.0.6367.60", "Not-A.Brand";v="99.0.0.0"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        }
    )


def get_extra_http_headers() -> Dict[str, str]:
    """Additional headers for Playwright context.

    Improved for #231: More complete and consistent client hints.
    These should match the User-Agent and TLS fingerprint used in the same session.
    """
    return align_client_hints(
        {
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Ch-Ua-Platform-Version": '"15.0.0"',
            "Sec-Ch-Ua-Full-Version-List": '"Chromium";v="124.0.6367.60", "Google Chrome";v="124.0.6367.60", "Not-A.Brand";v="99.0.0.0"',
        }
    )
