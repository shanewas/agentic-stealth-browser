"""UA / client-hints coherence with the bundled Chromium.

Regression coverage for the v3.1.0 stealth gate failure: persona profiles
pin Chrome/124 while Playwright's bundled Chromium is much newer, so the
UA string contradicted navigator.userAgentData (124 vs 149) and the pair
was flagged by every detector that compares them.
"""

import re

from stealth.headers import (
    align_client_hints,
    align_user_agent,
    bundled_chrome_version,
    get_extra_http_headers,
    get_realistic_headers,
)
from stealth.profiles import DEFAULT_PERSONA

PINNED_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
FAKE_VERSION = "149.0.7827.55"


def test_align_user_agent_rewrites_major():
    out = align_user_agent(PINNED_UA, FAKE_VERSION)
    assert "Chrome/149.0.0.0" in out
    assert "124" not in out


def test_align_user_agent_noops_without_version(monkeypatch):
    import stealth.headers as headers

    monkeypatch.setattr(headers, "bundled_chrome_version", lambda: None)
    assert align_user_agent(PINNED_UA, None) == PINNED_UA


def test_align_client_hints_rewrites_brands_but_not_grease():
    headers = {
        "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "Sec-Ch-Ua-Full-Version-List": '"Chromium";v="124.0.6367.60", "Google Chrome";v="124.0.6367.60", "Not-A.Brand";v="99.0.0.0"',
    }
    out = align_client_hints(headers, FAKE_VERSION)
    assert '"Chromium";v="149"' in out["Sec-Ch-Ua"]
    assert '"Google Chrome";v="149"' in out["Sec-Ch-Ua"]
    assert '"Not-A.Brand";v="99"' in out["Sec-Ch-Ua"]
    assert f'"Chromium";v="{FAKE_VERSION}"' in out["Sec-Ch-Ua-Full-Version-List"]
    assert '"Not-A.Brand";v="99.0.0.0"' in out["Sec-Ch-Ua-Full-Version-List"]


def test_extra_headers_match_bundled_major():
    version = bundled_chrome_version()
    if not version:
        return  # Playwright metadata unavailable in this environment
    major = version.split(".")[0]
    headers = get_extra_http_headers()
    assert f'"Chromium";v="{major}"' in headers["Sec-Ch-Ua"]
    realistic = get_realistic_headers()
    assert f"Chrome/{major}.0.0.0" in realistic["User-Agent"]


def test_persona_launch_overrides_are_aligned():
    version = bundled_chrome_version()
    if not version:
        return
    major = version.split(".")[0]
    ua = DEFAULT_PERSONA.to_launch_overrides()["user_agent"]
    found = re.search(r"Chrome/(\d+)\.", ua)
    assert found and found.group(1) == major
