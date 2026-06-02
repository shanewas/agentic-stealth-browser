"""Catalog of the six canary detection sites."""

from typing import TypedDict


class CanarySite(TypedDict):
    key: str
    name: str
    url: str
    platform: str
    expected_signals: list[str]


SITES: list[CanarySite] = [
    {
        "key": "sannysoft",
        "name": "Sannysoft Bot Detector",
        "url": "https://bot.sannysoft.com",
        "platform": "generic",
        "expected_signals": [
            "webdriver",
            "headless",
            "automation controlled",
            "failed",
        ],
    },
    {
        "key": "browserleaks",
        "name": "BrowserLeaks",
        "url": "https://browserleaks.com",
        "platform": "generic",
        "expected_signals": [
            "bot detected",
            "automation",
            "webdriver",
            "headless",
        ],
    },
    {
        "key": "pixelscan",
        "name": "Pixelscan",
        "url": "https://pixelscan.net",
        "platform": "generic",
        "expected_signals": [
            "bot detected",
            "automation",
            "inconsistent",
            "suspicious",
        ],
    },
    {
        "key": "nowsecure",
        "name": "NowSecure (Cloudflare)",
        "url": "https://nowsecure.nl",
        "platform": "cloudflare",
        "expected_signals": [
            "captcha",
            "challenge",
            "access denied",
            "blocked",
            "verify you are human",
        ],
    },
    {
        "key": "fingerprint_demo",
        "name": "Fingerprint.com Demo",
        "url": "https://fingerprint.com/demo",
        "platform": "generic",
        "expected_signals": [
            "bot detected",
            "automation",
            "blocked",
            "access denied",
            "unusual activity",
        ],
    },
    {
        "key": "creepjs",
        "name": "CreepJS",
        "url": "https://creepjs.com",
        "platform": "generic",
        "expected_signals": [
            "lies detected",
            "bot detected",
            "headless",
            "failed tests",
        ],
    },
]

SITE_KEYS: list[str] = [s["key"] for s in SITES]