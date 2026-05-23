import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from workflows.action_interpreter import normalize_step_params, validate_step_params
from workflows.schema import Workflow, load_workflow
from workflows.variable_resolver import VariableResolver


@dataclass
class ExecutionResult:
    success: bool
    steps_executed: int
    total_steps: int
    failed_step: Optional[int] = None
    failed_step_type: Optional[str] = None
    error_message: Optional[str] = None
    screenshots: List[str] = field(default_factory=list)
    summary: str = ""
    execution_time: float = 0.0
    backend_used: str = "bridge"
    recovery_used: bool = False
    checkpoint: Dict[str, Any] = field(default_factory=dict)


class WorkflowPlayer:
    def __init__(self, browser, variable_resolver: Optional[VariableResolver] = None):
        self.browser = browser
        self.resolver = variable_resolver or VariableResolver()
        self.checkpoint: Dict[str, Any] = {"completed_steps": [], "last_url": "", "variables": {}}

    async def execute(
        self, workflow: Workflow, runtime_vars: Optional[Dict[str, Any]] = None
    ) -> ExecutionResult:
        start_time = time.monotonic()
        total_steps = len(workflow.steps)
        screenshots: List[str] = []
        steps_executed = 0
        recovery_used = False

        run_vars = dict(runtime_vars or {})
        resolved_workflow = self.resolver.resolve_workflow(workflow, run_vars)

        for i, step in enumerate(resolved_workflow.steps):
            step_type = step.type
            params = normalize_step_params(step_type, step.params)

            errors = validate_step_params(step_type, params)
            if errors:
                elapsed = time.monotonic() - start_time
                return ExecutionResult(
                    success=False,
                    steps_executed=steps_executed,
                    total_steps=total_steps,
                    failed_step=i,
                    failed_step_type=step_type,
                    error_message="; ".join(errors),
                    screenshots=screenshots,
                    execution_time=elapsed,
                    recovery_used=recovery_used,
                    checkpoint=self.checkpoint,
                )

            try:
                await self._dispatch_step(step_type, params, run_vars)
                steps_executed += 1
                self.checkpoint["completed_steps"].append(i)
                try:
                    self.checkpoint["last_url"] = self._get_current_url()
                except Exception:
                    pass
            except Exception as e:
                screenshot_path = await self._take_step_screenshot(step_type, i)
                if screenshot_path:
                    screenshots.append(screenshot_path)
                elapsed = time.monotonic() - start_time
                return ExecutionResult(
                    success=False,
                    steps_executed=steps_executed,
                    total_steps=total_steps,
                    failed_step=i,
                    failed_step_type=step_type,
                    error_message=str(e),
                    screenshots=screenshots,
                    execution_time=elapsed,
                    recovery_used=recovery_used,
                    checkpoint=self.checkpoint,
                )

        elapsed = time.monotonic() - start_time
        return ExecutionResult(
            success=True,
            steps_executed=steps_executed,
            total_steps=total_steps,
            screenshots=screenshots,
            summary=f"Workflow '{workflow.name}' completed: {steps_executed}/{total_steps} steps executed successfully",
            execution_time=elapsed,
            recovery_used=recovery_used,
            checkpoint=self.checkpoint,
        )

    async def _dispatch_step(self, step_type: str, params: Dict[str, Any], run_vars: Dict[str, Any]):
        timeout_ms = params.get("timeout", 30000)
        timeout_s = timeout_ms / 1000.0

        if step_type == "navigate":
            await self._step_navigate(params, timeout_s)
        elif step_type == "click":
            await self._step_click(params, timeout_s)
        elif step_type == "fill":
            await self._step_fill(params, timeout_s)
        elif step_type == "type":
            await self._step_type(params, timeout_s)
        elif step_type == "select":
            await self._step_select(params, timeout_s)
        elif step_type == "verify":
            await self._step_verify(params, timeout_s)
        elif step_type == "wait":
            await self._step_wait(params)
        elif step_type == "wait_for_element":
            await self._step_wait_for_element(params, timeout_s)
        elif step_type == "scroll":
            await self._step_scroll(params)
        elif step_type == "screenshot":
            await self._step_screenshot(params)
        elif step_type == "execute_js":
            await self._step_execute_js(params)
        elif step_type == "conditional":
            await self._step_conditional(params, run_vars)
        elif step_type == "run_workflow":
            await self._step_run_workflow(params, run_vars)
        else:
            raise ValueError(f"Unknown step type: {step_type}")

    async def _step_navigate(self, params: Dict[str, Any], timeout_s: float):
        url = params["url"]
        platform = params.get("platform", "unknown")
        try:
            if hasattr(self.browser, "safe_goto"):
                await asyncio.wait_for(
                    self.browser.safe_goto(url, platform=platform),
                    timeout=timeout_s,
                )
            elif hasattr(self.browser, "goto"):
                await asyncio.wait_for(
                    self.browser.goto(url),
                    timeout=timeout_s,
                )
            else:
                await self._evaluate(f'window.location.href = "{url}"')
        except asyncio.TimeoutError:
            raise TimeoutError(f"Navigation to {url} timed out after {timeout_s}s")

    async def _step_click(self, params: Dict[str, Any], timeout_s: float):
        selector = params["selector"]
        fallbacks: List[str] = params.get("selector_fallbacks", [])
        selectors_to_try = [selector] + fallbacks
        last_error: Optional[Exception] = None

        for sel in selectors_to_try:
            try:
                if hasattr(self.browser, "safe_click"):
                    await asyncio.wait_for(
                        self.browser.safe_click(sel),
                        timeout=timeout_s,
                    )
                else:
                    await asyncio.wait_for(
                        self._evaluate(f'document.querySelector("{sel}").click()'),
                        timeout=timeout_s,
                    )
                wait_after = params.get("wait_after", 0)
                if wait_after:
                    await asyncio.sleep(wait_after / 1000.0)
                return
            except Exception as e:
                last_error = e
                continue

        raise last_error or RuntimeError(f"Click failed for selector: {selector}")

    async def _step_fill(self, params: Dict[str, Any], timeout_s: float):
        selector = params["selector"]
        value = params["value"]

        if hasattr(self.browser, "safe_type"):
            await asyncio.wait_for(
                self.browser.safe_type(selector, value),
                timeout=timeout_s,
            )
        else:
            await self._evaluate(
                f'document.querySelector("{selector}").value = {repr(value)}'
            )

        if params.get("submit"):
            await self._evaluate(
                f'document.querySelector("{selector}").form.submit()'
            )

    async def _step_type(self, params: Dict[str, Any], timeout_s: float):
        selector = params["selector"]
        value = params["value"]
        delay_ms = params.get("delay_ms", 50)

        if hasattr(self.browser, "safe_type"):
            await asyncio.wait_for(
                self.browser.safe_type(selector, value),
                timeout=timeout_s,
            )
        else:
            for char in value:
                await self._evaluate(
                    f'document.querySelector("{selector}").value += {repr(char)}'
                )
                await asyncio.sleep(delay_ms / 1000.0)

        if params.get("submit"):
            await self._evaluate(
                f'document.querySelector("{selector}").form.submit()'
            )

    async def _step_select(self, params: Dict[str, Any], timeout_s: float):
        selector = params["selector"]
        value = params["value"]
        await asyncio.wait_for(
            self._evaluate(
                f'document.querySelector("{selector}").value = {repr(value)}'
            ),
            timeout=timeout_s,
        )

    async def _step_verify(self, params: Dict[str, Any], timeout_s: float):
        selector = params["selector"]
        expected_text = params.get("text")
        visible = params.get("visible", True)

        async def check():
            exists = await self._evaluate(
                f'!!document.querySelector("{selector}")'
            )
            if not exists:
                raise RuntimeError(f"Verify failed: selector '{selector}' not found")

            if expected_text is not None:
                actual = await self._evaluate(
                    f'document.querySelector("{selector}").textContent'
                )
                if expected_text not in str(actual):
                    raise RuntimeError(
                        f"Verify failed: expected text '{expected_text}' not found in '{actual}'"
                    )

            if visible:
                displayed = await self._evaluate(
                    f'document.querySelector("{selector}").offsetParent !== null'
                )
                if not displayed:
                    raise RuntimeError(f"Verify failed: selector '{selector}' is not visible")

        await asyncio.wait_for(check(), timeout=timeout_s)

    async def _step_wait(self, params: Dict[str, Any]):
        ms = params.get("ms", 1000)
        selector = params.get("selector")
        text = params.get("text")
        url = params.get("url")

        if selector:
            deadline = time.monotonic() + ms / 1000.0
            while time.monotonic() < deadline:
                exists = await self._evaluate(f'!!document.querySelector("{selector}")')
                if exists:
                    return
                await asyncio.sleep(0.1)
            raise TimeoutError(f"Wait for selector '{selector}' timed out after {ms}ms")
        elif text:
            deadline = time.monotonic() + ms / 1000.0
            while time.monotonic() < deadline:
                body_text = await self._evaluate("document.body.textContent")
                if text in str(body_text):
                    return
                await asyncio.sleep(0.1)
            raise TimeoutError(f"Wait for text '{text}' timed out after {ms}ms")
        elif url:
            deadline = time.monotonic() + ms / 1000.0
            while time.monotonic() < deadline:
                current = self._get_current_url()
                if url in current:
                    return
                await asyncio.sleep(0.1)
            raise TimeoutError(f"Wait for URL '{url}' timed out after {ms}ms")
        else:
            await asyncio.sleep(ms / 1000.0)

    async def _step_wait_for_element(self, params: Dict[str, Any], timeout_s: float):
        selector = params["selector"]
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            exists = await self._evaluate(f'!!document.querySelector("{selector}")')
            if exists:
                return
            await asyncio.sleep(0.1)
        raise TimeoutError(f"Wait for element '{selector}' timed out after {timeout_s}s")

    async def _step_scroll(self, params: Dict[str, Any]):
        selector = params.get("selector")
        direction = params.get("direction", "down")
        amount = params.get("amount", 300)

        if selector:
            await self._evaluate(
                f'document.querySelector("{selector}").scrollIntoView()'
            )
        else:
            delta_y = amount if direction == "down" else -amount
            await self._evaluate(f"window.scrollBy(0, {delta_y})")

    async def _step_screenshot(self, params: Dict[str, Any]):
        path = params.get("path", "")
        if not path and hasattr(self.browser, "screenshot_on_error"):
            path = await self.browser.screenshot_on_error("step")
        elif hasattr(self.browser, "page") and hasattr(self.browser.page, "screenshot"):
            full_page = params.get("full_page", False)
            result = await self.browser.page.screenshot(path=path or None, full_page=full_page)
            if isinstance(result, dict) and "path" in result:
                path = result["path"]
            elif isinstance(result, str):
                path = result
        return path

    async def _step_execute_js(self, params: Dict[str, Any]):
        code = params["code"]
        await self._evaluate(code)

    async def _step_conditional(self, params: Dict[str, Any], run_vars: Dict[str, Any]):
        condition = params["condition"]
        steps = params.get("steps", [])
        else_steps = params.get("else_steps", [])

        result = await self._evaluate(condition)

        branch = steps if result else else_steps
        for step_data in branch:
            step_type = step_data["type"]
            resolved_params = self._resolve_step_data_params(step_data, run_vars)
            step_params = normalize_step_params(step_type, resolved_params)
            await self._dispatch_step(step_type, step_params, run_vars)

    async def _step_run_workflow(self, params: Dict[str, Any], run_vars: Dict[str, Any]):
        path = params["path"]
        variables = params.get("variables", {})

        nested = load_workflow(path)
        merged_vars = dict(run_vars)
        merged_vars.update(variables)

        result = await self.execute(nested, merged_vars)
        if not result.success:
            raise RuntimeError(
                f"Nested workflow '{result.failed_step_type}' failed at step {result.failed_step}: {result.error_message}"
            )

    def _resolve_step_data_params(self, step_data: Dict[str, Any], run_vars: Dict[str, Any]) -> Dict[str, Any]:
        resolved = {}
        for key, value in step_data.items():
            if key == "type":
                continue
            if isinstance(value, str):
                resolved[key] = self.resolver.resolve(value, run_vars)
            elif isinstance(value, list):
                resolved[key] = [
                    self.resolver.resolve(v, run_vars) if isinstance(v, str) else v
                    for v in value
                ]
            elif isinstance(value, dict):
                resolved[key] = {
                    k: self.resolver.resolve(v, run_vars) if isinstance(v, str) else v
                    for k, v in value.items()
                }
            else:
                resolved[key] = value
        return resolved

    async def _evaluate(self, js: str):
        if hasattr(self.browser, "page") and hasattr(self.browser.page, "evaluate"):
            return await self.browser.page.evaluate(js)
        if hasattr(self.browser, "evaluate"):
            return await self.browser.evaluate(js)
        raise RuntimeError("Browser does not support evaluate()")

    def _get_current_url(self) -> str:
        if hasattr(self.browser, "page") and hasattr(self.browser.page, "url"):
            return self.browser.page.url
        if hasattr(self.browser, "url"):
            return self.browser.url
        return ""

    async def _take_step_screenshot(self, step_type: str, step_index: int) -> Optional[str]:
        name = f"error_step_{step_index}_{step_type}"
        try:
            if hasattr(self.browser, "screenshot_on_error"):
                return await self.browser.screenshot_on_error(name)
            if hasattr(self.browser, "page") and hasattr(self.browser.page, "screenshot"):
                buf = await self.browser.page.screenshot()
                if buf:
                    return f"screenshots/{name}_{int(time.time())}.png"
        except Exception:
            pass
        return None
