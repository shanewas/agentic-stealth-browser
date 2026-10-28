"""Lifecycle/teardown regression tests for AgentBrowser.

Covers the teardown-state model shared by launch(), attach_over_cdp(),
rotation relaunch, switch_to_page() and close(): close() must always leave
the instance in the clean __init__ state. All Playwright objects are fakes;
no live browser is started.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

pytestmark = pytest.mark.asyncio

from core.agent_browser import AgentBrowser, RecoveryError, TeardownMode
from recovery.anti_block_orchestrator import (
    AntiBlockOrchestrator,
    RecoveryAction,
    RecoveryContext,
)


# ---------------------------------------------------------------------------
# Fakes (existing test style: small local stand-ins, monkeypatched seams)
# ---------------------------------------------------------------------------


class FakePage:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class FakeContext:
    def __init__(self, *, fail_init=False, fail_new_page=False):
        self.pages = []
        self.closed = False
        self.browser = None
        self._fail_init = fail_init
        self._fail_new_page = fail_new_page

    async def close(self):
        self.closed = True

    async def add_init_script(self, script):
        if self._fail_init:
            raise RuntimeError("init boom")

    async def new_page(self):
        if self._fail_new_page:
            raise RuntimeError("new_page boom")
        page = FakePage()
        self.pages.append(page)
        return page


class FakeChromium:
    def __init__(self, context=None, exc=None):
        self._context = context
        self._exc = exc

    async def launch_persistent_context(self, **kwargs):
        if self._exc is not None:
            raise self._exc
        return self._context


class FakePW:
    def __init__(self, context=None, exc=None):
        self.chromium = FakeChromium(context, exc)
        self.stop_count = 0

    async def stop(self):
        self.stop_count += 1


class FakeStarter:
    def __init__(self, pw):
        self._pw = pw

    async def start(self):
        return self._pw


class FakeTLS:
    def log_fingerprint_choice(self):
        pass

    def get_launch_args(self):
        return []


class FakeHuman:
    def __init__(self, page, rng=None, device_profile=None):
        self.page = page

    async def initialize_mouse_tracker(self):
        pass


class FakeLogger:
    def __init__(self, *args, **kwargs):
        self.actions = []
        self.errors = []

    def log_action(self, *args, **kwargs):
        self.actions.append(args)

    def log_error(self, *args, **kwargs):
        self.errors.append(args)

    def close(self):
        pass


class FakeRecoveryRef:
    def __init__(self, browser=None):
        self.browser = browser
        self.session_name = None
        self._get_page = None

    def set_current_session_name(self, name):
        self.session_name = name


class FakeRemoteBrowser:
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True


class FakePool:
    def __init__(self):
        self.released = []

    async def release_context(self, ctx):
        self.released.append(ctx)
        await ctx.close()


def _patch_collaborators(monkeypatch):
    """Patch the heavy collaborators launch()/rotation build, not the SUT."""
    monkeypatch.setattr("core.agent_browser.get_stealth_script", lambda **kw: "s")
    monkeypatch.setattr(
        "core.agent_browser.get_tls_manager", lambda *a, **k: FakeTLS()
    )
    monkeypatch.setattr(
        "core.agent_browser.check_stealth_compatibility", lambda *a, **k: {}
    )
    monkeypatch.setattr("core.agent_browser.HumanBehavior", FakeHuman)
    monkeypatch.setattr(
        "core.agent_browser.BehaviorOrchestrator", lambda human, rng=None: human
    )
    monkeypatch.setattr(
        "core.agent_browser.StealthScraper",
        lambda page, human, orchestrator: (page, human),
    )
    monkeypatch.setattr("core.agent_browser.AuditLogger", FakeLogger)
    monkeypatch.setattr(
        "core.agent_browser.AntiBlockOrchestrator",
        lambda **kw: FakeRecoveryRef(browser=kw.get("browser")),
    )


def _make_browser(name):
    return AgentBrowser(session_name=name, anonymous=True, ephemeral=True)


# ---------------------------------------------------------------------------
# #3: classic launch sets TeardownMode.LAUNCHED; close() fallback
# ---------------------------------------------------------------------------


async def test_classic_launch_failure_after_context_creation_is_closed(monkeypatch):
    _patch_collaborators(monkeypatch)
    ctx = FakeContext(fail_init=True)
    pw = FakePW(context=ctx)
    monkeypatch.setattr(
        "core.agent_browser.async_playwright", lambda: FakeStarter(pw)
    )
    ab = _make_browser("t3-fail-after-ctx")

    with pytest.raises(RuntimeError, match="init boom"):
        await ab.launch()
    assert ab._teardown_mode == TeardownMode.LAUNCHED
    assert ab.browser is ctx

    await ab.close()
    assert ctx.closed is True
    assert pw.stop_count == 1
    assert ab.browser is None and ab._teardown_mode is None


async def test_classic_launch_success_sets_launched_and_close_cleans(monkeypatch):
    _patch_collaborators(monkeypatch)
    ctx = FakeContext()
    pw = FakePW(context=ctx)
    monkeypatch.setattr(
        "core.agent_browser.async_playwright", lambda: FakeStarter(pw)
    )
    ab = _make_browser("t3-success")

    await ab.launch()
    assert ab._teardown_mode == TeardownMode.LAUNCHED
    assert ab._owns_page is True

    await ab.close()
    assert ctx.closed is True
    assert pw.stop_count == 1
    await ab.close()  # idempotent
    assert pw.stop_count == 1


async def test_close_fallback_closes_modeless_non_attached_context():
    ab = _make_browser("t3-fallback")
    ctx = FakeContext()
    ab.browser = ctx
    ab.browser_context = ctx
    ab._teardown_mode = None
    ab._using_pool = False
    ab._attached = False

    await ab.close()
    assert ctx.closed is True
    assert ab.browser is None


async def test_close_fallback_leaves_modeless_attached_context_alone():
    ab = _make_browser("t3-fallback-attached")
    ctx = FakeContext()
    remote = FakeRemoteBrowser()
    ab.browser = ctx
    ab._teardown_mode = None
    ab._attached = True
    ab._remote_browser = remote

    await ab.close()
    assert ctx.closed is False  # adopted/external context is never closed
    assert remote.closed is True
    assert ab._attached is False


# ---------------------------------------------------------------------------
# #4: launch() twice must not leak/orphan the first launch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "attr,value",
    [
        ("browser", object()),
        ("page", FakePage()),
        ("_pw", FakePW()),
        ("_remote_browser", object()),
        ("_attached", True),
    ],
)
async def test_second_launch_rejected_without_touching_first(attr, value):
    ab = _make_browser("t4-double-launch")
    setattr(ab, attr, value)
    with pytest.raises(RuntimeError, match="already has an active browser"):
        await ab.launch()
    assert getattr(ab, attr) is value  # first launch's handles untouched
    setattr(ab, attr, None if attr != "_attached" else False)
    await ab.close()


# ---------------------------------------------------------------------------
# #5: rotation relaunch stages, swaps atomically, raises typed failure
# ---------------------------------------------------------------------------


def _rotation_browser(tmp_path, monkeypatch, staged_ctx=None, staged_exc=None):
    _patch_collaborators(monkeypatch)
    ab = _make_browser("t5-rotation")
    old_page, old_ctx = FakePage(), FakeContext()
    old_ctx.pages = [old_page]
    ab.session = {"name": "old", "user_data_dir": str(tmp_path / "old")}
    ab.browser = old_ctx
    ab.browser_context = old_ctx
    ab.page = old_page
    ab._owns_page = True
    ab._pw = FakePW(context=staged_ctx, exc=staged_exc)
    ab._launch_options = {"headless": True, "slow_mo": 0, "headed": False}
    ab.logger = FakeLogger()
    ab.recovery = FakeRecoveryRef(browser=old_ctx)
    ab.human, ab.orchestrator, ab.scraper = object(), object(), object()
    new_meta = {"name": "rotated", "user_data_dir": str(tmp_path / "rotated")}
    return ab, old_ctx, old_page, new_meta


async def test_rotation_launch_failure_raises_and_keeps_old_session(
    tmp_path, monkeypatch
):
    ab, old_ctx, _old_page, new_meta = _rotation_browser(
        tmp_path, monkeypatch, staged_exc=RuntimeError("relaunch boom")
    )

    with pytest.raises(RecoveryError, match="rotation_relaunch_failed"):
        await ab._perform_rotation_relaunch(new_meta)

    assert old_ctx.closed is True  # old browser really was closed first
    assert ab.session["name"] == "old"  # new session NOT adopted on failure
    assert ab.browser is None and ab.page is None  # explicitly dead
    assert ab.human is None and ab.orchestrator is None and ab.scraper is None
    assert ab.recovery.browser is None
    assert ab._teardown_mode is None


async def test_rotation_new_page_failure_closes_only_staged_context(
    tmp_path, monkeypatch
):
    staged = FakeContext(fail_new_page=True)
    ab, _old_ctx, _old_page, new_meta = _rotation_browser(
        tmp_path, monkeypatch, staged_ctx=staged
    )

    with pytest.raises(RecoveryError, match="rotation_relaunch_failed"):
        await ab._perform_rotation_relaunch(new_meta)

    assert staged.closed is True
    assert ab.session["name"] == "old"
    assert ab.browser is None and ab.page is None


async def test_rotation_success_swaps_all_references(tmp_path, monkeypatch):
    staged = FakeContext()
    ab, old_ctx, _old_page, new_meta = _rotation_browser(
        tmp_path, monkeypatch, staged_ctx=staged
    )

    await ab._perform_rotation_relaunch(new_meta)

    assert old_ctx.closed is True
    assert ab.browser is staged and ab.browser_context is staged
    assert ab.page is staged.pages[0]
    assert ab.session is new_meta
    assert ab.human.page is ab.page
    assert ab.recovery.browser is staged
    assert ab.recovery.session_name == "rotated"
    assert ab._teardown_mode == TeardownMode.LAUNCHED
    await ab.close()


async def test_recovery_caller_counts_failed_relaunch_hook_as_failed_rotation():
    session_manager = MagicMock()
    session_manager.create_session.return_value = {"name": "new-session"}
    orch = AntiBlockOrchestrator(session_manager=session_manager)
    orch._update_recovery_history = MagicMock(wraps=orch._update_recovery_history)

    async def failing_hook(sess_meta, proxy_name):
        raise RecoveryError("rotation_relaunch_failed: boom")

    orch._rotation_relaunch_hook = failing_hook
    ctx = RecoveryContext(
        platform="linkedin",
        url="https://linkedin.com/feed",
        attempt=1,
        http_status=429,
    )

    result = await orch.recover(ctx)

    assert result is False
    orch._update_recovery_history.assert_called_with(
        ctx, RecoveryAction.ROTATE_SESSION_ONLY, success=False
    )


# ---------------------------------------------------------------------------
# #6: switch_to_page membership + ownership
# ---------------------------------------------------------------------------


async def test_switch_to_page_rejects_foreign_page(monkeypatch):
    _patch_collaborators(monkeypatch)
    ab = _make_browser("t6-foreign")
    ctx = FakeContext()
    member = FakePage()
    ctx.pages = [member]
    ab.browser = ctx
    ab.page = member
    foreign = FakePage()

    with pytest.raises(ValueError, match="does not belong"):
        await ab.switch_to_page(foreign)
    assert ab.page is member  # unchanged on rejection

    assert await ab.switch_to_page(foreign, adopt_foreign_page=True) is True
    assert ab.page is foreign
    assert ab._owns_page is False  # adoption never transfers ownership
    await ab.close()


async def test_switch_to_page_ownership_only_for_created_pages(monkeypatch):
    _patch_collaborators(monkeypatch)
    ab = _make_browser("t6-ownership")
    ctx = FakeContext()
    preexisting = FakePage()
    ctx.pages = [preexisting]
    ab.browser = ctx

    assert await ab.switch_to_page(preexisting) is True
    assert ab._owns_page is False  # member, but this instance did not create it

    created = await ab.new_page()
    assert await ab.switch_to_page(created) is True
    assert ab._owns_page is True  # created by this instance via new_page()

    assert await ab.switch_to_page(preexisting) is True
    assert ab._owns_page is False
    await ab.close()


async def test_close_does_not_close_switched_preexisting_page():
    ab = _make_browser("t6-close-survives")
    ctx = FakeContext()
    user_page = FakePage()
    ctx.pages = [user_page]
    remote = FakeRemoteBrowser()
    ab.browser = ctx
    ab.page = user_page
    ab._owns_page = False
    ab._teardown_mode = TeardownMode.ATTACHED_ADOPTED_CTX
    ab._remote_browser = remote

    await ab.close()
    assert user_page.closed is False
    assert ctx.closed is False
    assert remote.closed is True


# ---------------------------------------------------------------------------
# #10: pooled-then-attached reuse must stop the attach Playwright driver
# ---------------------------------------------------------------------------


async def test_close_resets_pool_state_and_stops_later_attach_driver():
    ab = _make_browser("t10-pooled-then-attached")
    pool = FakePool()
    pooled_ctx = FakeContext()
    ab.browser = pooled_ctx
    ab.page = FakePage()
    ab._owns_page = True
    ab._using_pool = True
    ab._pool = pool
    ab._teardown_mode = TeardownMode.POOLED

    await ab.close()
    assert pool.released == [pooled_ctx]
    assert ab._using_pool is False
    assert ab._teardown_mode is None

    # Same instance reused for attach: it now owns a Playwright driver.
    pw = FakePW()
    attach_ctx = FakeContext()
    remote = FakeRemoteBrowser()
    ab._pw = pw
    ab.browser = attach_ctx
    ab.page = FakePage()
    ab._owns_page = True
    ab._attached = True
    ab._attached_cdp_url = "http://127.0.0.1:9222"
    ab._remote_browser = remote
    ab._teardown_mode = TeardownMode.ATTACHED_OWNED_CTX

    await ab.close()
    assert pw.stop_count == 1  # attach driver not leaked via the pool branch
    assert attach_ctx.closed is True
    assert remote.closed is True
    assert ab._attached is False and ab._attached_cdp_url is None
    assert ab._using_pool is False and ab._pw is None

    await ab.close()  # double-close stays safe
    assert pw.stop_count == 1


# ---------------------------------------------------------------------------
# #11: close() unregisters the atexit callback
# ---------------------------------------------------------------------------


async def test_close_unregisters_atexit_callback(monkeypatch):
    import atexit as atexit_module

    calls = []
    real_unregister = atexit_module.unregister

    def spy(callback):
        calls.append(callback)
        return real_unregister(callback)

    monkeypatch.setattr(atexit_module, "unregister", spy)
    ab = _make_browser("t11-atexit")
    assert ab._atexit_registered is True
    callback = ab._atexit_callback
    assert callback is not None

    await ab.close()
    assert calls == [callback]
    assert ab._atexit_registered is False
    assert ab._atexit_callback is None

    await ab.close()  # double-close must stay safe, no second unregister
    assert calls == [callback]
