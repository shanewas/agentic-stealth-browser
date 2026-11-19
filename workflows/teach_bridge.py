"""Teach-mode event bridge: live human actions -> WorkflowRecorder (#445).

Implements Option A from the #445 spike (injected listeners):

- Capture-phase DOM listeners (click, input/change, keydown for
  Enter/Tab only, scroll throttled, submit) are installed via
  ``add_init_script`` and report through an exposed binding.
- Navigation steps come from a CDP session (``Page.frameNavigated``).
- Event shaping lives here, not in the recorder: binding reports and CDP
  events are translated into the dict shape
  :meth:`WorkflowRecorder.on_cdp_event` already consumes.

Teach mode is an operator-driven demo mode, not a stealth run: the
injected listeners add a page-visible JS surface while teaching, so
teach and stealth are mutually exclusive modes.

Raw input values are passed only into the recorder (which parameterizes
secret-looking inputs via ``_is_secret_element`` / ``_detect_variable``);
they are never logged here.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, Optional

from workflows.recorder import WorkflowRecorder

logger = logging.getLogger(__name__)

BINDING_NAME = "__asbTeachReport"

# Capture-phase listeners. Element info is gathered in-page because the
# listener sees the real event target. Values are reported raw; the
# recorder is responsible for redaction/parameterization.
_INIT_SCRIPT = r"""
(() => {
  if (window.__asbTeachInstalled) return;
  window.__asbTeachInstalled = true;
  const report = (payload) => {
    try {
      const fn = window.__asbTeachReport;
      if (typeof fn === 'function') fn(payload);
    } catch (e) { /* teach is best-effort; never break the page */ }
  };
  const elementInfo = (el) => {
    if (!el || el.nodeType !== 1) return {};
    const attrs = {};
    try {
      for (const a of el.attributes || []) attrs[a.name] = a.value;
    } catch (e) {}
    let cls = '';
    try { cls = typeof el.className === 'string' ? el.className : ''; } catch (e) {}
    let text = '';
    try { text = (el.textContent || '').slice(0, 200); } catch (e) {}
    return {
      tagName: el.tagName || '',
      id: el.id || '',
      className: cls,
      textContent: text,
      attributes: attrs,
    };
  };
  document.addEventListener('click', (ev) => {
    report({ type: 'click', element: elementInfo(ev.target) });
  }, true);
  const onValue = (ev) => {
    const el = ev.target;
    report({
      type: 'input',
      element: elementInfo(el),
      value: el && 'value' in el ? String(el.value) : '',
    });
  };
  document.addEventListener('input', onValue, true);
  document.addEventListener('change', onValue, true);
  document.addEventListener('keydown', (ev) => {
    if (ev.key !== 'Enter' && ev.key !== 'Tab') return;
    report({ type: 'keydown', key: ev.key, element: elementInfo(ev.target) });
  }, true);
  let lastScrollY = window.scrollY || 0;
  let lastScrollX = window.scrollX || 0;
  let scrollTimer = null;
  document.addEventListener('scroll', () => {
    if (scrollTimer) return;
    scrollTimer = setTimeout(() => {
      scrollTimer = null;
      const y = window.scrollY || 0;
      const x = window.scrollX || 0;
      const dy = y - lastScrollY;
      const dx = x - lastScrollX;
      lastScrollY = y; lastScrollX = x;
      if (dy !== 0 || dx !== 0) report({ type: 'scroll', deltaX: dx, deltaY: dy });
    }, 150);
  }, true);
  document.addEventListener('submit', (ev) => {
    report({ type: 'submit', element: elementInfo(ev.target) });
  }, true);
})();
"""


def _element_params(element: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Flatten a binding element report into recorder params fields."""
    element = element or {}
    attrs = element.get("attributes") or {}
    if not isinstance(attrs, dict):
        attrs = {}
    params: Dict[str, Any] = {
        "tagName": element.get("tagName", ""),
        "id": element.get("id", ""),
        "className": element.get("className", ""),
        "textContent": element.get("textContent", ""),
        "attributes": dict(attrs),
    }
    # _element_info_from_params also picks these up from top-level params.
    for key in ("autocomplete", "name"):
        if key in attrs and key not in params:
            params[key] = attrs[key]
    return params


def shape_binding_report(report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Translate one binding report into a recorder ``on_cdp_event`` dict.

    Returns ``None`` for reports the recorder has no use for.
    Event shaping lives in the bridge, not the recorder.
    """
    if not isinstance(report, dict):
        return None
    rtype = report.get("type")
    element = report.get("element")

    if rtype == "click":
        params = _element_params(element)
        params["type"] = "click"
        return {"method": "Input.dispatchMouseEvent", "params": params}

    if rtype == "input":
        params = _element_params(element)
        params["text"] = report.get("value", "")
        return {"method": "Input.insertText", "params": params}

    if rtype == "keydown":
        key = report.get("key")
        if key not in ("Enter", "Tab"):
            return None
        params = _element_params(element)
        params["type"] = "keyDown"
        params["key"] = key
        return {"method": "Input.dispatchKeyEvent", "params": params}

    if rtype == "scroll":
        return {
            "method": "Input.dispatchMouseEvent",
            "params": {
                "type": "mouseWheel",
                "deltaX": report.get("deltaX", 0),
                "deltaY": report.get("deltaY", 0),
            },
        }

    if rtype == "submit":
        # The recorder has no submit event; a form submission is the
        # result of acting on the form, so shape it as a click on the
        # form element to keep the step in the workflow.
        params = _element_params(element)
        params["type"] = "click"
        return {"method": "Input.dispatchMouseEvent", "params": params}

    return None


def shape_cdp_event(
    method: str, params: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Translate a CDP session event into a recorder dict (navigation only)."""
    if method == "Page.frameNavigated":
        return {"method": method, "params": params or {}}
    return None


class TeachSession:
    """Owns one teach capture: page/context, CDP session, recorder, timer.

    Usage::

        session = TeachSession(recorder=WorkflowRecorder())
        await session.start(page, capture_seconds=60)
        ...  # human drives the page
        await session.stop("completed")
        yaml_text = session.recorder.to_workflow_yaml()

    ``stop()`` is idempotent and is called on completion, timeout,
    cancellation, and page/session close. Tests assert cleanup via
    :attr:`active_listener_count`, :attr:`is_active`, and
    :attr:`cleanup_state`.
    """

    def __init__(
        self,
        recorder: Optional[WorkflowRecorder] = None,
        binding_name: str = BINDING_NAME,
    ):
        self.recorder = recorder if recorder is not None else WorkflowRecorder()
        self.binding_name = binding_name
        self._page: Any = None
        self._context: Any = None
        self._cdp_session: Any = None
        self._timer_task: Optional[asyncio.Task] = None
        self._active = False
        self._binding_installed = False
        self._cdp_listener_count = 0
        self._stop_reason: Optional[str] = None
        self._stop_count = 0
        self._events_forwarded = 0
        # Bound handlers kept so listeners can be removed on stop().
        self._cdp_handler: Optional[Callable[..., Any]] = None
        self._page_close_handler: Optional[Callable[..., Any]] = None

    # -- introspection for tests / callers ---------------------------------

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def active_listener_count(self) -> int:
        """Number of live subscriptions (CDP listeners + page-close hook)."""
        count = self._cdp_listener_count
        if self._page_close_handler is not None:
            count += 1
        return count

    @property
    def stop_reason(self) -> Optional[str]:
        return self._stop_reason

    @property
    def events_forwarded(self) -> int:
        return self._events_forwarded

    @property
    def cleanup_state(self) -> Dict[str, Any]:
        return {
            "active": self._active,
            "stop_reason": self._stop_reason,
            "stop_count": self._stop_count,
            "cdp_session_attached": self._cdp_session is not None,
            "cdp_listener_count": self._cdp_listener_count,
            "active_listener_count": self.active_listener_count,
            "binding_installed": self._binding_installed,
            "timer_pending": self._timer_task is not None
            and not self._timer_task.done(),
            "events_forwarded": self._events_forwarded,
        }

    # -- event intake -------------------------------------------------------

    def handle_binding_report(self, *args: Any) -> None:
        """Binding callback. Playwright calls ``callback(source, arg)``;
        tests may call ``handle_binding_report(report)`` directly."""
        if not self._active:
            return
        report = args[-1] if args else None
        shaped = shape_binding_report(report) if isinstance(report, dict) else None
        if shaped is not None:
            self.recorder.on_cdp_event(shaped)
            self._events_forwarded += 1

    def handle_cdp_event(
        self, method: str, params: Optional[Dict[str, Any]] = None
    ) -> None:
        if not self._active:
            return
        shaped = shape_cdp_event(method, params)
        if shaped is not None:
            self.recorder.on_cdp_event(shaped)
            self._events_forwarded += 1

    def _on_frame_navigated(self, params: Any = None) -> None:
        # Playwright CDP handlers receive the params dict directly.
        self.handle_cdp_event(
            "Page.frameNavigated", params if isinstance(params, dict) else {}
        )

    def _on_page_close(self, *_args: Any) -> None:
        task = asyncio.ensure_future(self.stop("session-close"))
        task.add_done_callback(lambda _t: None)

    # -- lifecycle ----------------------------------------------------------

    async def start(
        self, page: Any, capture_seconds: Optional[float] = 60
    ) -> "TeachSession":
        if self._active:
            raise RuntimeError("TeachSession already active")
        self._page = page
        self._context = getattr(page, "context", None)
        self._active = True
        self._stop_reason = None

        await self._install_binding()
        await self._install_init_script()
        await self._attach_cdp()
        self._hook_page_close()

        if capture_seconds:
            self._timer_task = asyncio.ensure_future(
                self._timeout(float(capture_seconds))
            )
        return self

    async def _timeout(self, seconds: float) -> None:
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        await self.stop("timeout")

    async def _install_binding(self) -> None:
        callback = self.handle_binding_report
        for target in (self._context, self._page):
            if target is None:
                continue
            expose = getattr(target, "expose_binding", None)
            if expose is None:
                continue
            try:
                result = expose(self.binding_name, callback)
                if asyncio.iscoroutine(result):
                    await result
                self._binding_installed = True
                return
            except Exception:
                logger.debug(
                    "teach binding install failed on %r", target, exc_info=True
                )
        logger.debug("teach: no expose_binding available; binding not installed")

    async def _install_init_script(self) -> None:
        script = _INIT_SCRIPT.replace(BINDING_NAME, self.binding_name)
        for target in (self._context, self._page):
            if target is None:
                continue
            add_script = getattr(target, "add_init_script", None)
            if add_script is None:
                continue
            try:
                result = add_script(script)
                if asyncio.iscoroutine(result):
                    await result
                return
            except Exception:
                logger.debug(
                    "teach init script install failed on %r", target, exc_info=True
                )

    async def _attach_cdp(self) -> None:
        context = self._context
        if context is None:
            return
        new_session = getattr(context, "new_cdp_session", None)
        if new_session is None:
            return
        try:
            result = new_session(self._page)
            if asyncio.iscoroutine(result):
                result = await result
            self._cdp_session = result
        except Exception:
            logger.debug("teach CDP session attach failed", exc_info=True)
            self._cdp_session = None
            return
        self._cdp_handler = self._on_frame_navigated
        try:
            self._cdp_session.on("Page.frameNavigated", self._cdp_handler)
            self._cdp_listener_count = 1
        except Exception:
            logger.debug("teach CDP listener subscribe failed", exc_info=True)
            self._cdp_handler = None
        try:
            send_result = self._cdp_session.send("Page.enable")
            if asyncio.iscoroutine(send_result):
                await send_result
        except Exception:
            logger.debug("teach Page.enable failed", exc_info=True)

    def _hook_page_close(self) -> None:
        page = self._page
        on = getattr(page, "on", None) if page is not None else None
        if on is None:
            return
        self._page_close_handler = self._on_page_close
        try:
            on("close", self._page_close_handler)
        except Exception:
            logger.debug("teach page-close hook failed", exc_info=True)
            self._page_close_handler = None

    async def stop(self, reason: str = "completed") -> None:
        """Idempotent cleanup: listeners, CDP session, timer task."""
        if not self._active and self._stop_count > 0:
            return
        if not self._active and self._cdp_session is None and self._timer_task is None:
            # Never started: still record the stop so callers can rely on it.
            self._stop_reason = reason
            self._stop_count += 1
            return
        self._active = False
        self._stop_reason = reason
        self._stop_count += 1

        # Cancel the capture-window timer (unless stop was called by it).
        timer, self._timer_task = self._timer_task, None
        if (
            timer is not None
            and not timer.done()
            and timer is not asyncio.current_task()
        ):
            timer.cancel()
            try:
                await timer
            except (asyncio.CancelledError, Exception):
                pass

        # Remove the page-close hook.
        if self._page_close_handler is not None and self._page is not None:
            remove = getattr(self._page, "remove_listener", None)
            if remove is not None:
                try:
                    remove("close", self._page_close_handler)
                except Exception:
                    logger.debug("teach page-close unhook failed", exc_info=True)
            self._page_close_handler = None

        # Remove CDP listeners and detach the session.
        session, self._cdp_session = self._cdp_session, None
        if session is not None:
            if self._cdp_handler is not None:
                remove = getattr(session, "remove_listener", None)
                if remove is not None:
                    try:
                        remove("Page.frameNavigated", self._cdp_handler)
                    except Exception:
                        logger.debug("teach CDP listener removal failed", exc_info=True)
                self._cdp_handler = None
            self._cdp_listener_count = 0
            detach = getattr(session, "detach", None)
            if detach is not None:
                try:
                    result = detach()
                    if asyncio.iscoroutine(result):
                        await result
                except Exception:
                    logger.debug("teach CDP detach failed", exc_info=True)

    async def wait(self) -> None:
        """Wait until the capture window ends (timeout or external stop)."""
        timer = self._timer_task
        if timer is not None:
            try:
                await timer
            except asyncio.CancelledError:
                pass

    async def __aenter__(self) -> "TeachSession":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.stop("cancelled" if exc and exc[0] is not None else "completed")
