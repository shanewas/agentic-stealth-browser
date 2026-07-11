"""P0 regression gate — grades the engine's measured signals against a real-Chrome
reference and hard pass criteria. This is the permanent CI merge-gate: every
hardening phase (real Chrome, Patchright, curl_cffi, trusted input) must move a
row here from red to green and keep every other row green.

Two files drive it:
  - reference-chrome-<major>.json  — captured from a HAND-DRIVEN real Chrome of the
                                     matching major on a real machine. "Match" always
                                     means "match this reference", never a hardcoded const.
  - baseline.json                  — the engine's current output, refreshed each run.

Skips (not fails) when no browser/env is available, so it's safe in CI on machines
without a display/browser; run with STEALTH_HARNESS_LIVE=1 on a real browser env to
actually grade.

Pass criteria (from the TLS+CDP plan §3). Phases flip these green in order:
  P1 CDP:      webdriver is undefined (NOT false)
  P1 headless: renderer is NOT software (SwiftShader/llvmpipe) ; plugins > 0
  P1 TLS:      ja4 == reference ; akamai_h2 == reference ; PQ keyshare present
  P1 coherence:ua_major == uaData_major == reference major
  P3 input:    isTrusted true on mousemove AND wheel
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _load(name):
    p = HERE / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _reference():
    # pick the newest reference-chrome-*.json present
    refs = sorted(HERE.glob("reference-chrome-*.json"))
    return json.loads(refs[-1].read_text(encoding="utf-8")) if refs else None


@pytest.fixture(scope="module")
def measured():
    if os.environ.get("STEALTH_HARNESS_LIVE") != "1":
        pytest.skip("STEALTH_HARNESS_LIVE!=1 — set it on a real browser env to grade stealth")
    from tests.stealth_harness.collect import collect
    try:
        data = asyncio.run(collect())
    except Exception as e:  # engine/browser not installed on this box
        pytest.skip(f"harness could not launch the engine: {e}")
    # refresh the rolling baseline for humans to diff
    (HERE / "baseline.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


# --- P1 CDP -----------------------------------------------------------------

def test_webdriver_is_undefined_not_false(measured):
    # `false` means "patched but present" — real Chrome has it UNDEFINED.
    assert measured["probes"].get("webdriver") in (None, "undefined"), measured["probes"].get("webdriver")


# --- P1 headless tells ------------------------------------------------------

def test_renderer_is_not_software(measured):
    assert not measured["engine"].get("renderer_is_software"), \
        f"software renderer is a headless/GPU-less tell: {measured['probes'].get('webglRenderer')}"


def test_plugins_present(measured):
    assert (measured["probes"].get("pluginsLength") or 0) > 0


# --- P1 TLS -----------------------------------------------------------------

@pytest.mark.skipif(_reference() is None, reason="no reference-chrome-*.json captured yet")
def test_ja4_matches_reference(measured):
    ref = _reference()
    assert measured["tls"].get("ja4") == ref["tls"]["ja4"], \
        f"JA4 {measured['tls'].get('ja4')} != reference {ref['tls']['ja4']}"


@pytest.mark.skipif(_reference() is None, reason="no reference-chrome-*.json captured yet")
def test_http2_matches_reference(measured):
    ref = _reference()
    assert measured["tls"].get("akamai_h2_hash") == ref["tls"]["akamai_h2_hash"]


def test_post_quantum_keyshare_present(measured):
    # Real Chrome sends X25519MLKEM768; bundled Chromium of the wrong build won't.
    assert measured["tls"].get("has_pq_keyshare") is True


# --- P1 coherence -----------------------------------------------------------

def test_ua_major_matches_uadata(measured):
    assert measured["engine"].get("ua_matches_uaData"), \
        f"UA major {measured['engine'].get('ua_major')} != uaData {measured['engine'].get('uaData_major')}"


@pytest.mark.skipif(_reference() is None, reason="no reference-chrome-*.json captured yet")
def test_ua_major_matches_reference(measured):
    ref = _reference()
    assert measured["engine"].get("ua_major") == ref["engine"]["ua_major"]


# --- P3 trusted input -------------------------------------------------------

def test_mouse_events_are_trusted(measured):
    ti = measured["trusted_input"]
    assert ti.get("mousemove") is True and ti.get("wheel") is True, \
        f"synthetic input is untrusted (isTrusted=false): {ti}"
