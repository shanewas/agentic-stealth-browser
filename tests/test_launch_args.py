"""
Unit tests for launch argument helpers (issue #373).
Tests _build_launch_args and _merge_custom_options for:
- Stable deterministic ordering (no set() reordering)
- Order-preserving deduplication (first occurrence wins)
- CDP flag appending with dedup
- Custom option merge with key protection
- Edge cases (empty, None, duplicates across sources)
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.agent_browser import _build_launch_args, _merge_custom_options


class TestBuildLaunchArgs:
    """Tests for _build_launch_args stable-order deduplication."""

    def test_basic_merge_no_duplicates(self):
        base = ["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        extra = ["--disable-features=IsolateOrigins,site-per-process"]
        result = _build_launch_args(base, extra)
        assert result == [
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
        ]

    def test_dedup_first_occurrence_wins(self):
        base = ["--arg-a", "--arg-b"]
        extra = ["--arg-b", "--arg-c"]
        result = _build_launch_args(base, extra)
        assert result == ["--arg-a", "--arg-b", "--arg-c"]

    def test_full_duplicate_set(self):
        base = ["--foo"]
        extra = ["--foo"]
        result = _build_launch_args(base, extra)
        assert result == ["--foo"]

    def test_stable_order_across_calls(self):
        base = ["--z", "--a"]
        extra = ["--m"]
        r1 = _build_launch_args(base, extra)
        r2 = _build_launch_args(base, extra)
        assert r1 == r2 == ["--z", "--a", "--m"]

    def test_cdp_flags_appended(self):
        base = ["--no-sandbox"]
        extra = ["--disable-blink-features=AutomationControlled"]
        cdp = ["--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0"]
        result = _build_launch_args(base, extra, cdp_flags=cdp)
        assert result == [
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--remote-debugging-address=127.0.0.1",
            "--remote-debugging-port=0",
        ]

    def test_cdp_flags_deduped(self):
        base = ["--no-sandbox", "--remote-debugging-port=0"]
        extra = []
        cdp = ["--remote-debugging-port=0", "--remote-debugging-address=127.0.0.1"]
        result = _build_launch_args(base, extra, cdp_flags=cdp)
        assert result == [
            "--no-sandbox",
            "--remote-debugging-port=0",
            "--remote-debugging-address=127.0.0.1",
        ]

    def test_cdp_flags_none(self):
        base = ["--a"]
        extra = ["--b"]
        result = _build_launch_args(base, extra, cdp_flags=None)
        assert result == ["--a", "--b"]

    def test_empty_base_args(self):
        result = _build_launch_args([], ["--a", "--b"])
        assert result == ["--a", "--b"]

    def test_empty_extra_args(self):
        result = _build_launch_args(["--a", "--b"], [])
        assert result == ["--a", "--b"]

    def test_both_empty(self):
        result = _build_launch_args([], [])
        assert result == []

    def test_base_args_none(self):
        result = _build_launch_args(None, ["--a"])
        assert result == ["--a"]

    def test_extra_args_none(self):
        result = _build_launch_args(["--a"], None)
        assert result == ["--a"]

    def test_duplicate_across_base_extra_and_cdp(self):
        base = ["--no-sandbox"]
        extra = ["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        cdp = ["--no-sandbox", "--remote-debugging-port=0"]
        result = _build_launch_args(base, extra, cdp_flags=cdp)
        assert result == [
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--remote-debugging-port=0",
        ]

    def test_realistic_scenario(self):
        base = [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--no-sandbox",
        ]
        tls_args = [
            "--disable-features=IsolateOrigins,site-per-process",
            "--no-sandbox",
            "--some-tls-flag",
        ]
        result = _build_launch_args(base, tls_args)
        assert result == [
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--no-sandbox",
            "--some-tls-flag",
        ]


class TestMergeCustomOptions:
    """Tests for _merge_custom_options key-protecting merge."""

    def test_basic_merge(self):
        target = {"a": 1}
        custom = {"b": 2, "c": 3}
        _merge_custom_options(target, custom)
        assert target == {"a": 1, "b": 2, "c": 3}

    def test_protected_keys_skipped(self):
        target = {"a": 1}
        custom = {"a": 999, "b": 2}
        _merge_custom_options(target, custom, protected_keys=("a",))
        assert target == {"a": 1, "b": 2}

    def test_multiple_protected_keys(self):
        target = {"x": 0, "y": 0}
        custom = {"x": 1, "y": 2, "z": 3}
        _merge_custom_options(target, custom, protected_keys=("x", "y"))
        assert target == {"x": 0, "y": 0, "z": 3}

    def test_returns_target(self):
        target = {"a": 1}
        result = _merge_custom_options(target, {"b": 2}, protected_keys=())
        assert result is target

    def test_custom_options_empty(self):
        target = {"a": 1}
        _merge_custom_options(target, {})
        assert target == {"a": 1}

    def test_custom_options_none(self):
        target = {"a": 1}
        _merge_custom_options(target, None)
        assert target == {"a": 1}

    def test_no_protected_keys(self):
        target = {"a": 1}
        custom = {"a": 2, "b": 3}
        _merge_custom_options(target, custom, protected_keys=())
        assert target == {"a": 2, "b": 3}

    def test_realistic_launch_pooled(self):
        context_opts = {"viewport": {"w": 1366}, "user_agent": "Mozilla/5.0"}
        custom = {
            "user_data_dir": "/should/be/protected",
            "headless": False,
            "slow_mo": 100,
            "bypass_csp": True,
            "ignore_default_args": ["--disable-gpu"],
        }
        _merge_custom_options(
            context_opts, custom,
            protected_keys=("user_data_dir", "headless", "slow_mo"),
        )
        assert context_opts == {
            "viewport": {"w": 1366},
            "user_agent": "Mozilla/5.0",
            "bypass_csp": True,
            "ignore_default_args": ["--disable-gpu"],
        }

    def test_realistic_launch_classic(self):
        lp_kwargs = {"user_data_dir": "/data", "headless": True, "slow_mo": 0}
        custom = {
            "user_data_dir": "/evil/override",
            "headless": False,
            "bypass_csp": True,
        }
        _merge_custom_options(
            lp_kwargs, custom,
            protected_keys=("user_data_dir",),
        )
        assert lp_kwargs == {
            "user_data_dir": "/data",
            "headless": False,
            "slow_mo": 0,
            "bypass_csp": True,
        }
