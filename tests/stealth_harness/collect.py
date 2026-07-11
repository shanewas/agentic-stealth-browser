"""P0 stealth measurement harness — the "ruler" every hardening phase is graded by.

Drives the real AgentBrowser through the fingerprint surfaces that hard anti-bot
systems actually gate on, and returns a flat dict of measured signals. Nothing in
here asserts pass/fail — that's the reference-comparison layer (test_stealth.py).
Capture on the CURRENT engine to get baseline.json, and on a hand-driven real
Chrome of the same major to get reference-chrome-<major>.json.

Surfaces measured:
  - TLS/JA3/JA4/HTTP2   via tls.peet.ws/api/all (navigated by the PAGE, so we
                        fingerprint the exact customer path, not an out-of-band client)
  - CDP / automation    navigator.webdriver, chrome object, permissions/plugins
  - Headless tells      WebGL renderer (SwiftShader/llvmpipe = GPU-less tell), UA
  - Client-hints        Sec-CH-UA vs UA major coherence
  - Trusted input       isTrusted on a synthesized mouse move + wheel

Set STEALTH_HARNESS_LIVE=1 to allow the outbound calls (they hit third-party
detector endpoints — an explicit opt-in so CI doesn't call out silently).
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Detector surfaces. tls.peet.ws is the JA3/JA4/H2 oracle. The CreepJS /
# rebrowser-bot-detector pages are richer but need vendoring to localhost for
# determinism (P0.1) — start with the TLS oracle + in-page probes, which need no
# external assets and already cover the load-bearing signals.
TLS_ORACLE = "https://tls.peet.ws/api/all"

_PROBE_JS = r"""
() => {
  const g = (f) => { try { return f(); } catch (e) { return "ERR:" + e.message; } };
  // WebGL renderer — the killer tell on a GPU-less box (SwiftShader/llvmpipe).
  const webglRenderer = g(() => {
    const c = document.createElement("canvas");
    const gl = c.getContext("webgl") || c.getContext("experimental-webgl");
    if (!gl) return "no-webgl";
    const ext = gl.getExtension("WEBGL_debug_renderer_info");
    return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : "no-ext";
  });
  const uaData = g(() => {
    const b = (navigator.userAgentData && navigator.userAgentData.brands) || [];
    const chrome = b.find(x => /chrome/i.test(x.brand));
    return chrome ? chrome.version : null;
  });
  return {
    webdriver: g(() => navigator.webdriver),          // must be undefined, not false
    hasChromeObj: g(() => !!window.chrome),
    pluginsLength: g(() => navigator.plugins.length),  // 0 = headless tell
    hardwareConcurrency: g(() => navigator.hardwareConcurrency),
    deviceMemory: g(() => navigator.deviceMemory),
    platform: g(() => navigator.platform),
    languages: g(() => (navigator.languages || []).join(",")),
    userAgent: g(() => navigator.userAgent),
    uaDataChromeMajor: uaData ? String(uaData).split(".")[0] : null,
    webglRenderer,
    hasSwiftShader: g(() => /swiftshader|llvmpipe|software|angle.*(swiftshader)/i.test(
      (() => {
        const c = document.createElement("canvas");
        const gl = c.getContext("webgl") || c.getContext("experimental-webgl");
        if (!gl) return "";
        const ext = gl.getExtension("WEBGL_debug_renderer_info");
        return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : "";
      })())),
  };
}
"""

# Attaches listeners, then synthesizes a move + wheel and reports whether the
# events the page sees are trusted. After the P3 fix these must be true.
_TRUSTED_INPUT_JS = r"""
() => new Promise((resolve) => {
  const out = { mousemove: null, wheel: null };
  window.addEventListener("mousemove", (e) => { if (out.mousemove === null) out.mousemove = e.isTrusted; }, { once: true });
  window.addEventListener("wheel", (e) => { if (out.wheel === null) out.wheel = e.isTrusted; }, { once: true, passive: true });
  setTimeout(() => resolve(out), 400);
})
"""


def _ua_major(ua: str | None) -> str | None:
    if not ua:
        return None
    m = re.search(r"Chrome/(\d+)", ua)
    return m.group(1) if m else None


async def collect() -> dict:
    """Launch the engine and return measured stealth signals. Raises if the
    browser/engine can't start (caller decides whether to skip)."""
    if os.environ.get("STEALTH_HARNESS_LIVE") != "1":
        raise RuntimeError(
            "Set STEALTH_HARNESS_LIVE=1 to run — the harness makes outbound calls "
            "to third-party fingerprint detectors (tls.peet.ws etc.)."
        )

    from core.agent_browser import AgentBrowser

    result: dict = {"engine": {}, "tls": {}, "probes": {}, "trusted_input": {}}
    browser = AgentBrowser(anonymous=True, ephemeral=True, light_mode=True)
    try:
        await browser.launch(headless=True)
        page = browser.page

        # 1. TLS/JA3/JA4/H2 via the page itself.
        await page.goto(TLS_ORACLE, wait_until="domcontentloaded", timeout=30000)
        raw = await page.evaluate("() => document.body.innerText")
        try:
            tls = json.loads(raw)
            result["tls"] = {
                "ja3_hash": (tls.get("tls") or {}).get("ja3_hash"),
                "ja4": (tls.get("tls") or {}).get("ja4"),
                "ja4_r": (tls.get("tls") or {}).get("ja4_r"),
                "peetprint_hash": (tls.get("tls") or {}).get("peetprint_hash"),
                "akamai_h2_hash": (tls.get("http2") or {}).get("akamai_fingerprint_hash"),
                "user_agent_seen": tls.get("user_agent"),
                "has_pq_keyshare": "X25519MLKEM768" in raw or "4588" in raw,
            }
        except Exception as e:
            result["tls"] = {"parse_error": str(e), "raw_head": raw[:300]}

        # 2. In-page JS probes (CDP/headless/coherence signals).
        probes = await page.evaluate(_PROBE_JS)
        result["probes"] = probes

        # 3. Trusted-input check — synthesize a move + wheel via the engine's
        #    behavior layer if present, else a bare page.mouse move.
        listen = page.evaluate(_TRUSTED_INPUT_JS)
        try:
            await page.mouse.move(120, 140, steps=3)
            await page.mouse.wheel(0, 200)
        except Exception:
            pass
        result["trusted_input"] = await listen

        # 4. Derived coherence checks (cheap, decisive).
        ua = probes.get("userAgent")
        result["engine"] = {
            "ua_major": _ua_major(ua),
            "uaData_major": probes.get("uaDataChromeMajor"),
            "ua_matches_uaData": _ua_major(ua) == probes.get("uaDataChromeMajor"),
            "renderer_is_software": bool(probes.get("hasSwiftShader")),
        }
        return result
    finally:
        try:
            await browser.close()
        except Exception:
            pass


if __name__ == "__main__":
    import asyncio
    print(json.dumps(asyncio.run(collect()), indent=2))
