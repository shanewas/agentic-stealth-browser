import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RecoveryAction:
    action_type: str
    max_retries: int = 3
    backoff_seconds: float = 2.0
    take_screenshot: bool = True


@dataclass
class RecoveryResult:
    recovered: bool
    action_taken: str
    retries_used: int
    screenshot_paths: List[str]
    backend_used: str
    error_message: Optional[str] = None


class FallbackController:
    def __init__(self, browser, anti_block_orchestrator=None):
        self.browser = browser
        self.anti_block_orchestrator = anti_block_orchestrator

    async def handle_step_error(
        self,
        step_type: str,
        params: dict,
        error: Exception,
        step_index: int,
        recovery_config: Optional[RecoveryAction] = None,
    ) -> RecoveryResult:
        error_str = str(error).lower()

        if any(kw in error_str for kw in ("element", "not found", "selector", "queryselector")):
            return await self._handle_element_not_found_error(
                params=params,
                step_type=step_type,
                step_index=step_index,
                recovery_config=recovery_config,
            )

        if any(kw in error_str for kw in ("timeout", "timed out")):
            return await self._handle_timeout_error(
                params=params,
                step_type=step_type,
                step_index=step_index,
                recovery_config=recovery_config,
            )

        if await self.is_blocked():
            return await self._handle_block_detected(
                params=params,
                step_type=step_type,
                step_index=step_index,
                recovery_config=recovery_config,
            )

        return RecoveryResult(
            recovered=False,
            action_taken="abort",
            retries_used=0,
            screenshot_paths=[],
            backend_used="bridge",
            error_message=str(error),
        )

    async def handle_element_not_found(self, selector: str, params: dict) -> RecoveryResult:
        return await self._handle_element_not_found_error(
            params=params,
            step_type="unknown",
            step_index=-1,
            recovery_config=None,
        )

    async def _handle_element_not_found_error(
        self,
        params: dict,
        step_type: str,
        step_index: int,
        recovery_config: Optional[RecoveryAction] = None,
    ) -> RecoveryResult:
        backoffs = [1.0, 2.0, 4.0]
        max_retries = recovery_config.max_retries if recovery_config else 3
        take_screenshot = recovery_config.take_screenshot if recovery_config else True
        screenshot_paths: List[str] = []

        selector = params.get("selector", "")
        fallbacks: List[str] = params.get("selector_fallbacks", [])

        for attempt in range(max_retries):
            if attempt < len(backoffs):
                await asyncio.sleep(backoffs[attempt])

            if take_screenshot:
                path = await self._try_screenshot(step_index, attempt)
                if path:
                    screenshot_paths.append(path)

            try:
                if hasattr(self.browser, "safe_click"):
                    await self.browser.safe_click(selector)
                else:
                    await self._evaluate(f'document.querySelector({json.dumps(selector)}).click()')
                return RecoveryResult(
                    recovered=True,
                    action_taken="retry",
                    retries_used=attempt + 1,
                    screenshot_paths=screenshot_paths,
                    backend_used="bridge",
                )
            except Exception:
                pass

        for fallback_sel in fallbacks:
            try:
                if hasattr(self.browser, "safe_click"):
                    await self.browser.safe_click(fallback_sel)
                else:
                    await self._evaluate(f'document.querySelector({json.dumps(fallback_sel)}).click()')
                return RecoveryResult(
                    recovered=True,
                    action_taken="fallback_to_stealth",
                    retries_used=max_retries,
                    screenshot_paths=screenshot_paths,
                    backend_used="stealth",
                )
            except Exception:
                pass

        return RecoveryResult(
            recovered=False,
            action_taken="abort",
            retries_used=max_retries,
            screenshot_paths=screenshot_paths,
            backend_used="bridge",
            error_message=f"Element not found: {selector}",
        )

    async def handle_timeout(self, step_type: str, params: dict) -> RecoveryResult:
        return await self._handle_timeout_error(
            params=params,
            step_type=step_type,
            step_index=-1,
            recovery_config=None,
        )

    async def _handle_timeout_error(
        self,
        params: dict,
        step_type: str,
        step_index: int,
        recovery_config: Optional[RecoveryAction] = None,
    ) -> RecoveryResult:
        take_screenshot = recovery_config.take_screenshot if recovery_config else True
        screenshot_paths: List[str] = []

        doubled_timeout = params.get("timeout", 30000) * 2
        timeout_s = doubled_timeout / 1000.0

        if take_screenshot:
            path = await self._try_screenshot(step_index, 0)
            if path:
                screenshot_paths.append(path)

        try:
            if step_type == "navigate":
                url = params.get("url", "")
                if hasattr(self.browser, "safe_goto"):
                    await asyncio.wait_for(
                        self.browser.safe_goto(url, platform=params.get("platform", "unknown")),
                        timeout=timeout_s,
                    )
                elif hasattr(self.browser, "goto"):
                    await asyncio.wait_for(
                        self.browser.goto(url),
                        timeout=timeout_s,
                    )
                else:
                    await self._evaluate(f'window.location.href = {json.dumps(url)}')
            elif step_type in ("click", "fill", "type", "verify", "wait_for_element"):
                selector = params.get("selector", "")
                if step_type == "click" and hasattr(self.browser, "safe_click"):
                    await asyncio.wait_for(
                        self.browser.safe_click(selector),
                        timeout=timeout_s,
                    )
                elif step_type in ("fill", "type") and hasattr(self.browser, "safe_type"):
                    value = params.get("value", "")
                    await asyncio.wait_for(
                        self.browser.safe_type(selector, value),
                        timeout=timeout_s,
                    )
                elif step_type in ("verify", "wait_for_element"):
                    await asyncio.sleep(timeout_s)
                else:
                    await asyncio.sleep(timeout_s)
            else:
                await asyncio.sleep(timeout_s)

            return RecoveryResult(
                recovered=True,
                action_taken="retry",
                retries_used=1,
                screenshot_paths=screenshot_paths,
                backend_used="bridge",
            )
        except Exception as e:
            if self.anti_block_orchestrator is not None:
                try:
                    recovery_ctx = self._make_recovery_ctx(params, step_index, str(e))
                    await self.anti_block_orchestrator.recover(recovery_ctx)
                    return RecoveryResult(
                        recovered=True,
                        action_taken="fallback_to_stealth",
                        retries_used=2,
                        screenshot_paths=screenshot_paths,
                        backend_used="stealth",
                    )
                except Exception:
                    pass

        return RecoveryResult(
            recovered=False,
            action_taken="abort",
            retries_used=1,
            screenshot_paths=screenshot_paths,
            backend_used="bridge",
            error_message=f"Timeout on {step_type}",
        )

    async def _handle_block_detected(
        self,
        params: dict,
        step_type: str,
        step_index: int,
        recovery_config: Optional[RecoveryAction] = None,
    ) -> RecoveryResult:
        screenshot_paths: List[str] = []
        retries_used = 0

        if self.anti_block_orchestrator is not None:
            recovery_ctx = self._make_recovery_ctx(params, step_index, "block/challenge detected")
            try:
                await self.anti_block_orchestrator.recover(recovery_ctx)
                retries_used = 1
                return RecoveryResult(
                    recovered=True,
                    action_taken="fallback_to_stealth",
                    retries_used=retries_used,
                    screenshot_paths=screenshot_paths,
                    backend_used="stealth",
                )
            except Exception as e:
                return RecoveryResult(
                    recovered=False,
                    action_taken="abort",
                    retries_used=retries_used,
                    screenshot_paths=screenshot_paths,
                    backend_used="bridge",
                    error_message=str(e),
                )

        return RecoveryResult(
            recovered=False,
            action_taken="abort",
            retries_used=0,
            screenshot_paths=screenshot_paths,
            backend_used="bridge",
            error_message="Block/challenge detected but no orchestrator available",
        )

    async def is_blocked(self) -> bool:
        try:
            url = self._get_current_url()
            if any(ind in url.lower() for ind in ("challenge", "blocked", "captcha", "verify", "accessdenied")):
                return True

            if self.anti_block_orchestrator is not None and hasattr(self.anti_block_orchestrator, "detect_block"):
                from recovery.anti_block_orchestrator import RecoveryContext, BlockType
                ctx = RecoveryContext(
                    platform="unknown",
                    url=url,
                    attempt=1,
                )
                page = self._get_page()
                if page and hasattr(page, "content"):
                    content_preview = await asyncio.wait_for(page.content(), timeout=3.0)
                else:
                    content_preview = ""
                result = self.anti_block_orchestrator.detect_block(
                    content_preview, url, ctx
                )
                if result != BlockType.NONE:
                    return True

            return False
        except Exception:
            return False

    def _make_recovery_ctx(self, params: dict, step_index: int, error_str: str):
        from recovery.anti_block_orchestrator import RecoveryContext
        return RecoveryContext(
            platform=params.get("platform", "unknown"),
            url=self._get_current_url(),
            attempt=1,
            last_error=error_str,
        )

    def _get_current_url(self) -> str:
        if hasattr(self.browser, "page") and hasattr(self.browser.page, "url"):
            return self.browser.page.url
        if hasattr(self.browser, "url"):
            return self.browser.url
        return ""

    def _get_page(self):
        if hasattr(self.browser, "page"):
            return self.browser.page
        return None

    async def _evaluate(self, js: str):
        if hasattr(self.browser, "page") and hasattr(self.browser.page, "evaluate"):
            return await self.browser.page.evaluate(js)
        if hasattr(self.browser, "evaluate"):
            return await self.browser.evaluate(js)
        raise RuntimeError("Browser does not support evaluate()")

    async def _try_screenshot(self, step_index: int, attempt: int) -> Optional[str]:
        try:
            name = f"recovery_step_{step_index}_attempt_{attempt}"
            if hasattr(self.browser, "screenshot_on_error"):
                return await self.browser.screenshot_on_error(name)
            if hasattr(self.browser, "page") and hasattr(self.browser.page, "screenshot"):
                buf = await self.browser.page.screenshot()
                if buf:
                    return f"screenshots/{name}_{int(time.time())}.png"
        except Exception:
            pass
        return None
