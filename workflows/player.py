import asyncio
import hashlib
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath
from typing import Any, Dict, List, Optional, Tuple

from sessions.validation import resolve_contained_path
from workflows.action_interpreter import normalize_step_params, validate_step_params
from workflows.schema import Workflow, load_workflow
from workflows.selector_generator import SelectorGenerator
from workflows.variable_resolver import VariableResolver


logger = logging.getLogger(__name__)

MIN_RECORDED_DURATION_SECONDS = 1e-9


def workflow_checkpoint_identity(workflow: Workflow) -> Dict[str, str]:
    """Identity binding a checkpoint to one workflow's step list."""
    payload = json.dumps(
        [{"type": step.type, "params": step.params} for step in workflow.steps],
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return {
        "workflow_name": workflow.name,
        "steps_hash": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
    }


def _identity_from_checkpoint(
    checkpoint: Dict[str, Any],
) -> Optional[Tuple[str, str]]:
    identity = checkpoint.get("workflow_identity")
    name = checkpoint.get("workflow_name")
    steps_hash = checkpoint.get("steps_hash") or checkpoint.get("workflow_hash")
    if isinstance(identity, dict):
        name = name or identity.get("workflow_name") or identity.get("name")
        steps_hash = (
            steps_hash or identity.get("steps_hash") or identity.get("workflow_hash")
        )
    elif isinstance(identity, str) and ":" in identity:
        name, steps_hash = identity.split(":", 1)
    workflow_id = checkpoint.get("workflow_id")
    if not name and isinstance(workflow_id, str) and ":" in workflow_id:
        name, steps_hash = workflow_id.split(":", 1)
    if isinstance(name, str) and isinstance(steps_hash, str) and name and steps_hash:
        return (name, steps_hash)
    return None


def _validated_checkpoint(raw: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return None
    completed = raw.get("completed_steps")
    if not isinstance(completed, list) or any(
        not isinstance(item, int) or isinstance(item, bool) for item in completed
    ):
        return None
    last_url = raw.get("last_url", "")
    if not isinstance(last_url, str):
        return None
    variables = raw.get("variables", {})
    if not isinstance(variables, dict):
        return None
    validated = dict(raw)
    validated["completed_steps"] = list(completed)
    validated["last_url"] = last_url
    validated["variables"] = dict(variables)
    return validated


def _elapsed_since(start_time: float) -> float:
    return max(time.monotonic() - start_time, MIN_RECORDED_DURATION_SECONDS)


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
    recovery_actions: List[Dict[str, Any]] = field(default_factory=list)
    auto_healed_selectors: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class RehearsalResult:
    success: bool
    total_steps: int
    steps_validated: int
    warnings: List[str] = field(default_factory=list)
    screenshots: List[str] = field(default_factory=list)
    selectors_used: List[Dict[str, Any]] = field(default_factory=list)
    execution_time: float = 0.0
    summary: str = ""


class WorkflowPlayer:
    def __init__(
        self,
        browser,
        variable_resolver: Optional[VariableResolver] = None,
        workflows_root: Optional[Any] = None,
        screenshots_dir: Optional[Any] = None,
    ):
        self.browser = browser
        self.resolver = variable_resolver or VariableResolver()
        # Explicit containment root for nested run_workflow refs. When unset,
        # the directory of the workflow file that references the nested
        # workflow is the root (in-memory workflows then need this set).
        self.workflows_root: Optional[Path] = (
            Path(workflows_root) if workflows_root is not None else None
        )
        # Dedicated directory screenshot steps may write to.
        self.screenshots_dir: Path = (
            Path(screenshots_dir) if screenshots_dir is not None else Path("screenshots")
        )
        self._workflow_dir_stack: List[Optional[Path]] = []
        self.checkpoint: Dict[str, Any] = {
            "completed_steps": [],
            "last_url": "",
            "variables": {},
        }
        self.recovery: Optional[Any] = None
        self.backend: str = "bridge"
        self._workflow_stack: List[str] = []
        self.output_variables: Dict[str, Any] = {}
        self._checkpoint_frames: Dict[str, Dict[str, Any]] = {}
        self._checkpoint_path: Optional[str] = None
        self.checkpoint_warning: Optional[str] = None

    def set_recovery_controller(self, controller):
        self.recovery = controller

    def load_checkpoint(self, path: str) -> bool:
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return False
        if not isinstance(data, dict) or "checkpoint" not in data:
            return False
        validated = _validated_checkpoint(data.get("checkpoint"))
        if validated is None:
            return False
        backend = data.get("backend", "bridge")
        if not isinstance(backend, str):
            return False
        frames = validated.get("frames")
        if isinstance(frames, dict):
            for frame in frames.values():
                checked_frame = _validated_checkpoint(frame)
                if checked_frame is None:
                    continue
                identity = _identity_from_checkpoint(checked_frame)
                if identity is not None:
                    key = f"{identity[0]}:{identity[1]}"
                    self._checkpoint_frames[key] = checked_frame
        self.checkpoint = validated
        self.backend = backend
        self._checkpoint_path = str(path)
        return True

    def save_checkpoint(self, path: Optional[str] = None) -> str:
        if path is None:
            path = f"checkpoints/checkpoint_{int(time.time())}.json"
        path_str = str(path)
        parent = Path(path_str).parent
        parent.mkdir(parents=True, exist_ok=True)
        export_checkpoint = dict(self.checkpoint)
        if self._checkpoint_frames:
            export_checkpoint["frames"] = {
                key: {
                    field: value
                    for field, value in frame.items()
                    if field != "frames"
                }
                for key, frame in self._checkpoint_frames.items()
            }
        data = {
            "checkpoint": export_checkpoint,
            "backend": self.backend,
            "saved_at": time.time(),
        }
        fd, tmp_path = tempfile.mkstemp(
            dir=str(parent), prefix=".checkpoint-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path_str)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
        return path_str

    def _persist_checkpoint(self) -> None:
        if self._workflow_stack or not self._checkpoint_path:
            return
        try:
            self.save_checkpoint(self._checkpoint_path)
        except Exception:
            pass

    def _referencing_workflow_dir(self, workflow: Workflow) -> Optional[Path]:
        if self.workflows_root is not None:
            return self.workflows_root.resolve()
        if workflow.source_path:
            return Path(workflow.source_path).resolve().parent
        return None

    @staticmethod
    def _effective_run_vars(
        workflow: Workflow, runtime_vars: Optional[Dict[str, Any]]
    ) -> Tuple[Dict[str, Any], List[str]]:
        """Declared defaults seeded first; runtime vars win.

        Returns (effective_vars, missing_required_names).
        """
        effective: Dict[str, Any] = {}
        missing: List[str] = []
        for name, vdef in (workflow.variables or {}).items():
            if vdef.default is not None:
                effective[name] = vdef.default
            elif vdef.required and name not in (runtime_vars or {}):
                missing.append(name)
        effective.update(runtime_vars or {})
        return effective, missing

    async def execute(
        self, workflow: Workflow, runtime_vars: Optional[Dict[str, Any]] = None
    ) -> ExecutionResult:
        self._workflow_dir_stack.append(self._referencing_workflow_dir(workflow))
        try:
            return await self._execute(workflow, runtime_vars)
        finally:
            self._workflow_dir_stack.pop()

    async def _execute(
        self, workflow: Workflow, runtime_vars: Optional[Dict[str, Any]] = None
    ) -> ExecutionResult:
        start_time = time.monotonic()
        total_steps = len(workflow.steps)
        screenshots: List[str] = []
        steps_executed = 0
        recovery_used = False
        recovery_actions: List[Dict[str, Any]] = []
        auto_healed_selectors: List[Dict[str, Any]] = []

        identity = workflow_checkpoint_identity(workflow)
        frame_key = f"{identity['workflow_name']}:{identity['steps_hash']}"
        frame = self._checkpoint_frames.get(frame_key)
        if frame is None:
            source = self.checkpoint if isinstance(self.checkpoint, dict) else {}
            source_identity = _identity_from_checkpoint(source)
            expected_identity = (identity["workflow_name"], identity["steps_hash"])
            if source_identity is not None and source_identity != expected_identity:
                self.checkpoint_warning = (
                    f"Ignoring checkpoint for workflow '{source_identity[0]}' "
                    f"(steps_hash={source_identity[1]}): it does not match "
                    f"workflow '{identity['workflow_name']}' "
                    f"(steps_hash={identity['steps_hash']})"
                )
                logger.warning(self.checkpoint_warning)
                frame = {
                    "completed_steps": [],
                    "last_url": "",
                    "variables": {},
                }
            else:
                checked_source = _validated_checkpoint(source)
                frame = (
                    dict(checked_source)
                    if checked_source is not None
                    else {"completed_steps": [], "last_url": "", "variables": {}}
                )
            frame["workflow_name"] = identity["workflow_name"]
            frame["steps_hash"] = identity["steps_hash"]
            frame["workflow_identity"] = dict(identity)
            frame.pop("frames", None)
            self._checkpoint_frames[frame_key] = frame
        if not self._workflow_stack:
            self.checkpoint = frame

        completed = set(frame.get("completed_steps", []))

        run_vars, missing_required = self._effective_run_vars(workflow, runtime_vars)
        if missing_required:
            return ExecutionResult(
                success=False,
                steps_executed=0,
                total_steps=total_steps,
                failed_step=0,
                failed_step_type=None,
                error_message=(
                    "Missing required workflow variable(s): "
                    + ", ".join(missing_required)
                ),
                screenshots=screenshots,
                execution_time=_elapsed_since(start_time),
                checkpoint=frame,
            )
        resolved_workflow = self.resolver.resolve_workflow(workflow, run_vars)

        for i, step in enumerate(resolved_workflow.steps):
            step_type = step.type
            params = normalize_step_params(step_type, step.params)

            if i in completed:
                steps_executed += 1
                continue

            errors = validate_step_params(step_type, params)
            if errors:
                elapsed = _elapsed_since(start_time)
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
                    checkpoint=frame,
                    recovery_actions=recovery_actions,
                    auto_healed_selectors=auto_healed_selectors,
                )

            try:
                await self._dispatch_step(step_type, params, run_vars)
                steps_executed += 1
                frame["completed_steps"].append(i)
                try:
                    frame["last_url"] = self._get_current_url()
                except Exception:
                    pass
                self._persist_checkpoint()
            except Exception as e:
                healed_succeeded = False
                if step_type in ("click", "fill", "type", "verify", "wait_for_element"):
                    healed = self._try_auto_heal(params)
                    if healed:
                        for healed_selector in healed:
                            try:
                                healed_params = dict(params)
                                healed_params["selector"] = healed_selector
                                await self._dispatch_step(
                                    step_type, healed_params, run_vars
                                )
                                steps_executed += 1
                                frame["completed_steps"].append(i)
                                self._persist_checkpoint()
                                auto_healed_selectors.append(
                                    {
                                        "step_index": i,
                                        "step_type": step_type,
                                        "original_selector": params.get("selector", ""),
                                        "healed_selector": healed_selector,
                                    }
                                )
                                healed_succeeded = True
                                break
                            except Exception:
                                continue

                if healed_succeeded:
                    continue

                if i not in frame["completed_steps"]:
                    if self.recovery is not None:
                        recovery_cfg_raw = params.get("recovery")
                        if recovery_cfg_raw and isinstance(recovery_cfg_raw, dict):
                            from workflows.recovery import (
                                RecoveryAction as RecoveryActionCfg,
                            )

                            recovery_cfg = RecoveryActionCfg(
                                action_type=recovery_cfg_raw.get(
                                    "action_type", "retry"
                                ),
                                max_retries=recovery_cfg_raw.get("max_retries", 3),
                                backoff_seconds=recovery_cfg_raw.get("backoff", 2.0),
                                take_screenshot=recovery_cfg_raw.get(
                                    "take_screenshot", True
                                ),
                            )
                        else:
                            recovery_cfg = None

                        recovery_result = await self.recovery.handle_step_error(
                            step_type=step_type,
                            params=params,
                            error=e,
                            step_index=i,
                            recovery_config=recovery_cfg,
                        )

                        recovery_used = True
                        recovery_actions.append(
                            {
                                "step_index": i,
                                "step_type": step_type,
                                "recovered": recovery_result.recovered,
                                "action_taken": recovery_result.action_taken,
                                "retries_used": recovery_result.retries_used,
                                "backend_used": recovery_result.backend_used,
                                "error": str(e),
                            }
                        )

                        if recovery_result.recovered:
                            steps_executed += 1
                            frame["completed_steps"].append(i)
                            self._persist_checkpoint()
                            if recovery_result.backend_used == "stealth":
                                self.backend = "stealth"
                            continue

                screenshot_path = await self._take_step_screenshot(step_type, i)
                if screenshot_path:
                    screenshots.append(screenshot_path)
                elapsed = _elapsed_since(start_time)
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
                    checkpoint=frame,
                    recovery_actions=recovery_actions,
                    auto_healed_selectors=auto_healed_selectors,
                )

        elapsed = _elapsed_since(start_time)
        return ExecutionResult(
            success=True,
            steps_executed=steps_executed,
            total_steps=total_steps,
            screenshots=screenshots,
            summary=f"Workflow '{workflow.name}' completed: {steps_executed}/{total_steps} steps executed successfully",
            execution_time=elapsed,
            recovery_used=recovery_used,
            checkpoint=frame,
            recovery_actions=recovery_actions,
            auto_healed_selectors=auto_healed_selectors,
        )

    def _try_auto_heal(self, params: Dict[str, Any]) -> List[str]:
        selector = params.get("selector", "")
        if not selector:
            return []
        return SelectorGenerator.auto_heal_selector(selector)

    async def rehearse(
        self, workflow: Workflow, runtime_vars: Optional[Dict[str, Any]] = None
    ) -> RehearsalResult:
        start_time = time.monotonic()
        from workflows.schema import validate_workflow_steps

        warnings: List[str] = []
        screenshots: List[str] = []
        selectors_used: List[Dict[str, Any]] = []
        steps_validated = 0

        validation_warnings = validate_workflow_steps(workflow)
        warnings.extend(validation_warnings)

        run_vars = dict(runtime_vars or {})
        resolved_workflow = self.resolver.resolve_workflow(workflow, run_vars)

        for i, step in enumerate(resolved_workflow.steps):
            step_type = step.type
            params = normalize_step_params(step_type, step.params)

            if step_type == "navigate":
                url = params.get("url", "")
                warnings.append(f"Step {i} ({step_type}): would navigate to {url}")
                steps_validated += 1
                try:
                    screenshot_path = await self._take_step_screenshot(step_type, i)
                    if screenshot_path:
                        screenshots.append(screenshot_path)
                except Exception:
                    pass

            elif step_type == "click":
                selector = params.get("selector", "")
                warnings.append(f"Step {i} ({step_type}): would click {selector}")
                selectors_used.append(
                    {
                        "step_index": i,
                        "step_type": step_type,
                        "selector": selector,
                        "fallbacks": params.get("selector_fallbacks", []),
                    }
                )
                try:
                    exists = await self._evaluate(
                        f"!!document.querySelector({json.dumps(selector)})"
                    )
                    if exists:
                        steps_validated += 1
                    if not exists:
                        warnings.append(
                            f"Step {i} ({step_type}): selector '{selector}' NOT FOUND on current page"
                        )
                except Exception as e:
                    warnings.append(
                        f"Step {i} ({step_type}): could not verify selector: {e}"
                    )

            elif step_type == "fill" or step_type == "type":
                selector = params.get("selector", "")
                value = params.get("value", "")
                warnings.append(
                    f"Step {i} ({step_type}): would fill {selector} with '{value}'"
                )
                selectors_used.append(
                    {
                        "step_index": i,
                        "step_type": step_type,
                        "selector": selector,
                    }
                )
                try:
                    exists = await self._evaluate(
                        f"!!document.querySelector({json.dumps(selector)})"
                    )
                    if exists:
                        steps_validated += 1
                    if not exists:
                        warnings.append(
                            f"Step {i} ({step_type}): selector '{selector}' NOT FOUND on current page"
                        )
                except Exception as e:
                    warnings.append(
                        f"Step {i} ({step_type}): could not verify selector: {e}"
                    )

            elif step_type == "verify":
                selector = params.get("selector", "")
                text = params.get("text", "")
                warnings.append(
                    f"Step {i} ({step_type}): would verify {selector} "
                    f"{'contains ' + text if text else 'exists'}"
                )
                selectors_used.append(
                    {
                        "step_index": i,
                        "step_type": step_type,
                        "selector": selector,
                    }
                )
                steps_validated += 1

            elif step_type == "screenshot":
                warnings.append(f"Step {i} ({step_type}): would take screenshot")
                steps_validated += 1
                try:
                    screenshot_path = await self._take_step_screenshot(step_type, i)
                    if screenshot_path:
                        screenshots.append(screenshot_path)
                except Exception:
                    pass

            elif step_type == "run_workflow":
                path = params.get("path", "")
                warnings.append(
                    f"Step {i} ({step_type}): would run nested workflow from {path}"
                )
                steps_validated += 1

            elif step_type == "conditional":
                condition = params.get("condition", "")
                steps_count = len(params.get("steps", []))
                else_count = len(params.get("else_steps", []))
                warnings.append(
                    f"Step {i} ({step_type}): condition '{condition}' with "
                    f"{steps_count} steps (else: {else_count})"
                )
                steps_validated += 1

            elif step_type == "wait":
                ms_val = params.get("ms", 1000)
                wait_reason = (
                    params.get("selector")
                    or params.get("text")
                    or params.get("url")
                    or f"{ms_val}ms"
                )
                warnings.append(f"Step {i} ({step_type}): would wait for {wait_reason}")
                steps_validated += 1

            elif step_type == "wait_for_element":
                selector = params.get("selector", "")
                warnings.append(f"Step {i} ({step_type}): would wait for {selector}")
                steps_validated += 1

            elif step_type == "scroll":
                direction = params.get("direction", "down")
                amount = params.get("amount", 300)
                warnings.append(
                    f"Step {i} ({step_type}): would scroll {direction} {amount}px"
                )
                steps_validated += 1

            elif step_type == "select":
                selector = params.get("selector", "")
                value = params.get("value", "")
                warnings.append(
                    f"Step {i} ({step_type}): would select {value} on {selector}"
                )
                steps_validated += 1

            elif step_type == "execute_js":
                code = params.get("code", "")
                warnings.append(
                    f"Step {i} ({step_type}): would execute JS ({len(code)} chars)"
                )
                steps_validated += 1

            else:
                warnings.append(
                    f"Step {i} ({step_type}): unknown step type in rehearsal"
                )

        elapsed = _elapsed_since(start_time)
        success = not any(
            "NOT FOUND" in warning or "unknown step type" in warning
            for warning in warnings
        )
        return RehearsalResult(
            success=success,
            total_steps=len(resolved_workflow.steps),
            steps_validated=steps_validated,
            warnings=warnings,
            screenshots=screenshots,
            selectors_used=selectors_used,
            execution_time=elapsed,
            summary=f"Rehearsal complete: {steps_validated}/{len(resolved_workflow.steps)} steps validated, {len(warnings)} warnings",
        )

    async def _dispatch_step(
        self, step_type: str, params: Dict[str, Any], run_vars: Dict[str, Any]
    ):
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
                await self._evaluate(f"window.location.href = {json.dumps(url)}")
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
                        self._evaluate(
                            f"document.querySelector({json.dumps(sel)}).click()"
                        ),
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
                f"document.querySelector({json.dumps(selector)}).value = {json.dumps(value)}"
            )

        if params.get("submit"):
            await self._evaluate(
                f"document.querySelector({json.dumps(selector)}).form.submit()"
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
                    f"document.querySelector({json.dumps(selector)}).value += {json.dumps(char)}"
                )
                await asyncio.sleep(delay_ms / 1000.0)

        if params.get("submit"):
            await self._evaluate(
                f"document.querySelector({json.dumps(selector)}).form.submit()"
            )

    async def _step_select(self, params: Dict[str, Any], timeout_s: float):
        selector = params["selector"]
        value = params["value"]
        await asyncio.wait_for(
            self._evaluate(
                f"document.querySelector({json.dumps(selector)}).value = {json.dumps(value)}"
            ),
            timeout=timeout_s,
        )

    async def _step_verify(self, params: Dict[str, Any], timeout_s: float):
        selector = params["selector"]
        expected_text = params.get("text")
        visible = params.get("visible", True)

        async def check():
            exists = await self._evaluate(
                f"!!document.querySelector({json.dumps(selector)})"
            )
            if not exists:
                raise RuntimeError(f"Verify failed: selector '{selector}' not found")

            if expected_text is not None:
                actual = await self._evaluate(
                    f"document.querySelector({json.dumps(selector)}).textContent"
                )
                if expected_text not in str(actual):
                    raise RuntimeError(
                        f"Verify failed: expected text '{expected_text}' not found in '{actual}'"
                    )

            if visible:
                displayed = await self._evaluate(
                    f"document.querySelector({json.dumps(selector)}).offsetParent !== null"
                )
                if not displayed:
                    raise RuntimeError(
                        f"Verify failed: selector '{selector}' is not visible"
                    )

        await asyncio.wait_for(check(), timeout=timeout_s)

    async def _step_wait(self, params: Dict[str, Any]):
        ms = params.get("ms", 1000)
        selector = params.get("selector")
        text = params.get("text")
        url = params.get("url")

        if selector:
            deadline = time.monotonic() + ms / 1000.0
            while time.monotonic() < deadline:
                exists = await self._evaluate(
                    f"!!document.querySelector({json.dumps(selector)})"
                )
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
            exists = await self._evaluate(
                f"!!document.querySelector({json.dumps(selector)})"
            )
            if exists:
                return
            await asyncio.sleep(0.1)
        raise TimeoutError(
            f"Wait for element '{selector}' timed out after {timeout_s}s"
        )

    async def _step_scroll(self, params: Dict[str, Any]):
        selector = params.get("selector")
        direction = params.get("direction", "down")
        # Defensive cast: amount is interpolated into JS below, so it must
        # be a real int here even if a caller bypassed validate_step_params.
        amount = int(params.get("amount", 300))

        if selector:
            await self._evaluate(
                f"document.querySelector({json.dumps(selector)}).scrollIntoView()"
            )
        else:
            delta_y = amount if direction == "down" else -amount
            await self._evaluate(f"window.scrollBy(0, {delta_y})")

    async def _step_screenshot(self, params: Dict[str, Any]):
        path = params.get("path", "")
        if path:
            # Workflow-controlled name must stay under screenshots_dir as a
            # .png; sessions.validation is stdlib-only, so no import cycle.
            contained = resolve_contained_path(
                self.screenshots_dir, path, required_suffix=".png"
            )
            contained.parent.mkdir(parents=True, exist_ok=True)
            path = str(contained)
        if not path and hasattr(self.browser, "screenshot_on_error"):
            path = await self.browser.screenshot_on_error("step")
        elif hasattr(self.browser, "page") and hasattr(self.browser.page, "screenshot"):
            full_page = params.get("full_page", False)
            result = await self.browser.page.screenshot(
                path=path or None, full_page=full_page
            )
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

        # NOTE (H2): `condition` is arbitrary JavaScript evaluated in the
        # page, exactly like an execute_js step's `code`. The player has no
        # policy/approval seam of its own — it never consults one for
        # execute_js either; that gate lives in the production replay path
        # (production/mcp_handlers.py: PolicyEngine.check_step /
        # ApprovalGate.check_sensitive over _expand_replay_steps). To block
        # side-effecting conditions there, that expansion should emit the
        # condition as an execute_js leaf so a blocked-JS policy denies it.
        # Until then, branch steps below get the same validate_step_params
        # gate as top-level steps.
        result = await self._evaluate(condition)

        branch = steps if result else else_steps
        for step_data in branch:
            if not isinstance(step_data, dict) or not step_data.get("type"):
                raise ValueError(
                    f"Conditional branch step is missing required field 'type': {step_data!r}"
                )
            step_type = step_data["type"]
            resolved_params = self._resolve_step_data_params(step_data, run_vars)
            step_params = normalize_step_params(step_type, resolved_params)
            errors = validate_step_params(step_type, step_params)
            if errors:
                raise ValueError(
                    f"Invalid conditional branch step ({step_type}): "
                    + "; ".join(errors)
                )
            await self._dispatch_step(step_type, step_params, run_vars)

    def _resolve_nested_workflow_path(self, ref: Any) -> Path:
        """Resolve a run_workflow ref inside its containment root.

        The root is the configured workflows_root, else the directory of
        the workflow file making the reference. Absolute refs and any
        resolution escaping the root (including via symlinks) are rejected.
        """
        if not isinstance(ref, str) or not ref.strip():
            raise ValueError("run_workflow 'path' must be a non-empty string")
        if Path(ref).is_absolute() or PureWindowsPath(ref).drive or "\\" in ref:
            raise ValueError(
                f"run_workflow path must be relative to the workflow root: {ref!r}"
            )
        root = self._workflow_dir_stack[-1] if self._workflow_dir_stack else None
        if root is None:
            raise ValueError(
                "run_workflow cannot resolve "
                f"{ref!r}: no workflows_root configured and the referencing "
                "workflow was not loaded from a file"
            )
        resolved_root = Path(root).resolve()
        candidate = (resolved_root / ref).resolve()
        if candidate == resolved_root or not candidate.is_relative_to(resolved_root):
            raise ValueError(
                f"run_workflow path escapes the workflow root: {ref!r}"
            )
        return candidate

    async def _step_run_workflow(
        self, params: Dict[str, Any], run_vars: Dict[str, Any]
    ):
        path = params["path"]
        variables = params.get("variables", {})
        output_as = params.get("output_as")

        # Canonical (resolved) spelling keys the cycle stack, so a.yaml,
        # ./a.yaml and sub/../a.yaml are the same entry.
        resolved_path = self._resolve_nested_workflow_path(path)
        canonical = str(resolved_path)

        if canonical in self._workflow_stack:
            chain = " -> ".join(self._workflow_stack + [canonical])
            raise RuntimeError(f"Cycle detected in workflow chain: {chain}")

        nested = load_workflow(canonical)
        merged_vars = dict(run_vars)
        merged_vars.update(variables)

        self._workflow_stack.append(canonical)
        try:
            result = await self.execute(nested, merged_vars)
            if not result.success:
                raise RuntimeError(
                    f"Nested workflow '{result.failed_step_type}' failed at step {result.failed_step}: {result.error_message}"
                )
            if output_as:
                self.output_variables[output_as] = {
                    "success": result.success,
                    "steps_executed": result.steps_executed,
                    "total_steps": result.total_steps,
                }
        finally:
            self._workflow_stack.pop()

    def _resolve_step_data_params(
        self, step_data: Dict[str, Any], run_vars: Dict[str, Any]
    ) -> Dict[str, Any]:
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

    async def _take_step_screenshot(
        self, step_type: str, step_index: int
    ) -> Optional[str]:
        name = f"error_step_{step_index}_{step_type}"
        try:
            if hasattr(self.browser, "screenshot_on_error"):
                return await self.browser.screenshot_on_error(name)
            if hasattr(self.browser, "page") and hasattr(
                self.browser.page, "screenshot"
            ):
                buf = await self.browser.page.screenshot()
                if buf:
                    return f"screenshots/{name}_{int(time.time())}.png"
        except Exception:
            pass
        return None
