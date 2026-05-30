"""Hermes Browser Dashboard runtime and FastAPI app.

This module provides a single-user operator dashboard for one shared browser
session. The core classes are framework-light so tests can exercise the control
plane without launching Chromium.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote, urlparse

from fastapi import FastAPI, HTTPException, Request
from workflows.player import WorkflowPlayer
from workflows.schema import (
    Workflow,
    WorkflowStep,
    load_workflow,
    validate_workflow,
    workflow_to_yaml_str,
)


DEFAULT_STORAGE_ROOT = Path.home() / ".agentic-browser" / "hermes_dashboard"
SUPPORTED_BACKENDS = ("playwright-mcp", "agentic-stealth-mcp", "cdp-bridge")


@dataclass
class DashboardSettings:
    host: str = "127.0.0.1"
    port: int = 8443
    password: str = "change-me"
    secret_key: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    cookie_name: str = "hermes_dashboard_session"
    cookie_secure: bool = False
    idle_timeout_seconds: int = 30 * 60
    allowed_origins: List[str] = field(
        default_factory=lambda: ["http://127.0.0.1:8443", "http://localhost:8443"]
    )


@dataclass
class ActivityEvent:
    source: str
    event: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ts": self.ts,
            "source": self.source,
            "event": self.event,
            "message": self.message,
            "details": self.details,
        }


class ActivityStream:
    def __init__(self, max_events: int = 1000):
        self.max_events = max_events
        self._events: List[ActivityEvent] = []

    def append(
        self, source: str, event: str, message: str, **details: Any
    ) -> ActivityEvent:
        item = ActivityEvent(
            source=source, event=event, message=message, details=details
        )
        self._events.append(item)
        if len(self._events) > self.max_events:
            self._events = self._events[-self.max_events :]
        return item

    def list(
        self, limit: int = 100, source: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        events = self._events
        if source:
            events = [e for e in events if e.source == source]
        return [e.to_dict() for e in events[-limit:]]

    def export(self) -> Dict[str, Any]:
        return {
            "events": [e.to_dict() for e in self._events],
            "count": len(self._events),
        }


class DashboardBackendAdapter:
    name = "base"

    def __init__(self, manager: "BrowserRuntimeManager"):
        self.manager = manager

    @property
    def capabilities(self) -> Dict[str, Any]:
        return {
            "live_view": True,
            "workflow_replay": True,
            "recording": True,
            "requires_relaunch": False,
        }

    async def launch(self, profile: str, headless: bool = True) -> None:
        await self.manager._launch_browser(
            profile=profile, backend=self.name, headless=headless
        )

    async def close(self) -> None:
        await self.manager._close_browser()

    async def navigate(self, url: str) -> None:
        browser = self.manager.require_browser()
        if hasattr(browser, "safe_goto"):
            await browser.safe_goto(url)
            return
        page = self.manager.current_page()
        if page and hasattr(page, "goto"):
            await page.goto(url)
            return
        raise RuntimeError("Active backend cannot navigate")

    async def click(self, selector: str) -> None:
        browser = self.manager.require_browser()
        if hasattr(browser, "safe_click"):
            await browser.safe_click(selector)
            return
        page = self.manager.current_page()
        if page and hasattr(page, "click"):
            await page.click(selector)
            return
        if page and hasattr(page, "evaluate"):
            await page.evaluate(
                f"document.querySelector({json.dumps(selector)}).click()"
            )
            return
        raise RuntimeError("Active backend cannot click")

    async def fill(self, selector: str, value: str) -> None:
        browser = self.manager.require_browser()
        if hasattr(browser, "safe_type"):
            await browser.safe_type(selector, value)
            return
        page = self.manager.current_page()
        if page and hasattr(page, "fill"):
            await page.fill(selector, value)
            return
        if page and hasattr(page, "evaluate"):
            await page.evaluate(
                f"document.querySelector({json.dumps(selector)}).value = {json.dumps(value)}"
            )
            return
        raise RuntimeError("Active backend cannot fill")

    async def screenshot(self, path: Optional[str] = None) -> Optional[str]:
        browser = self.manager.require_browser()
        if hasattr(browser, "screenshot_on_error"):
            return await browser.screenshot_on_error("dashboard")
        page = self.manager.current_page()
        if page and hasattr(page, "screenshot"):
            await page.screenshot(path=path)
            return path
        return None


class PlaywrightMCPAdapter(DashboardBackendAdapter):
    name = "playwright-mcp"


class AgenticStealthMCPAdapter(DashboardBackendAdapter):
    name = "agentic-stealth-mcp"

    @property
    def capabilities(self) -> Dict[str, Any]:
        caps = super().capabilities
        caps.update({"stealth": True, "anti_block": True})
        return caps


class CDPBridgeAdapter(DashboardBackendAdapter):
    name = "cdp-bridge"

    async def launch(self, profile: str, headless: bool = True) -> None:
        await self.manager._launch_browser(
            profile=profile, backend=self.name, headless=headless, debug_cdp=True
        )

    @property
    def capabilities(self) -> Dict[str, Any]:
        caps = super().capabilities
        caps.update({"cdp_attach": True})
        return caps


class DashboardRecorder:
    def __init__(self) -> None:
        self.active = False
        self.name = "dashboard-demo"
        self.description = ""
        self.steps: List[WorkflowStep] = []
        self.metadata: Dict[str, Any] = {}

    def start(
        self,
        name: str,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.active = True
        self.name = name
        self.description = description
        self.steps = []
        self.metadata = dict(metadata or {})

    def stop(self) -> Workflow:
        self.active = False
        return Workflow(
            name=self.name,
            description=self.description,
            steps=list(self.steps),
            metadata=dict(self.metadata),
        )

    def record(self, step_type: str, **params: Any) -> None:
        if self.active:
            self.steps.append(WorkflowStep(type=step_type, params=params))


class BrowserRuntimeManager:
    def __init__(
        self,
        agent_browser_cls: Optional[type] = None,
        storage_root: Optional[Path] = None,
        activity: Optional[ActivityStream] = None,
    ):
        self.agent_browser_cls = agent_browser_cls
        self.storage_root = Path(storage_root or DEFAULT_STORAGE_ROOT)
        self.workflow_root = self.storage_root / "workflows"
        self.profile_root = self.storage_root / "profiles"
        self.run_root = self.storage_root / "runs"
        for path in (self.workflow_root, self.profile_root, self.run_root):
            path.mkdir(parents=True, exist_ok=True)
        self.activity = activity or ActivityStream()
        self.browser: Any = None
        self.active_profile = "default"
        self.active_backend = "playwright-mcp"
        self.control_mode = "shared"
        self.execution_state = "idle"
        self.intervention: Optional[Dict[str, Any]] = None
        self.recorder = DashboardRecorder()
        self.schedules: List[Dict[str, Any]] = []
        self.start_time: Optional[float] = None
        self.adapters = {
            "playwright-mcp": PlaywrightMCPAdapter(self),
            "agentic-stealth-mcp": AgenticStealthMCPAdapter(self),
            "cdp-bridge": CDPBridgeAdapter(self),
        }

    def _get_agent_browser_cls(self) -> type:
        if self.agent_browser_cls is not None:
            return self.agent_browser_cls
        from core.agent_browser import AgentBrowser

        return AgentBrowser

    async def _launch_browser(
        self, profile: str, backend: str, headless: bool = True, debug_cdp: bool = False
    ) -> None:
        await self._close_browser()
        cls = self._get_agent_browser_cls()
        self.profile_root.joinpath(profile).mkdir(parents=True, exist_ok=True)
        self.browser = cls(session_name=profile, anonymous=False, ephemeral=False)
        launch_kwargs = {"headless": headless, "debug_cdp": debug_cdp}
        if backend == "agentic-stealth-mcp":
            launch_kwargs.update({"preset": None, "region": "global"})
        await self.browser.launch(**launch_kwargs)
        self.active_profile = profile
        self.active_backend = backend
        self.start_time = time.time()
        self.activity.append(
            "system",
            "browser_started",
            f"Started {backend}",
            profile=profile,
            debug_cdp=debug_cdp,
        )

    async def _close_browser(self) -> None:
        if self.browser and hasattr(self.browser, "close"):
            await self.browser.close()
        self.browser = None
        self.start_time = None

    def require_browser(self) -> Any:
        if not self.browser:
            raise RuntimeError("Browser is not running")
        return self.browser

    def current_page(self) -> Any:
        browser = self.require_browser()
        if hasattr(browser, "page_getter"):
            return browser.page_getter()
        return getattr(browser, "page", None)

    async def start(
        self,
        profile: str = "default",
        backend: str = "playwright-mcp",
        headless: bool = True,
    ) -> Dict[str, Any]:
        self._ensure_backend(backend)
        await self.adapters[backend].launch(profile=profile, headless=headless)
        return await self.status()

    async def stop(self) -> Dict[str, Any]:
        await self._close_browser()
        self.activity.append("system", "browser_stopped", "Browser stopped")
        return await self.status()

    async def restart(self) -> Dict[str, Any]:
        profile, backend = self.active_profile, self.active_backend
        await self.start(profile=profile, backend=backend)
        self.activity.append(
            "system",
            "browser_restarted",
            "Browser restarted",
            profile=profile,
            backend=backend,
        )
        return await self.status()

    async def switch_backend(self, backend: str) -> Dict[str, Any]:
        self._ensure_backend(backend)
        warning = "Switch relaunches the managed browser while preserving the active profile name."
        await self.start(profile=self.active_profile, backend=backend)
        self.activity.append(
            "system", "backend_switched", f"Switched to {backend}", warning=warning
        )
        status = await self.status()
        status["warning"] = warning
        return status

    async def status(self) -> Dict[str, Any]:
        page_url = ""
        title = ""
        cdp = {"status": "disabled"}
        if self.browser:
            page = self.current_page()
            page_url = getattr(page, "url", "") if page else ""
            if page and hasattr(page, "title"):
                value = page.title()
                title = await value if asyncio.iscoroutine(value) else str(value)
            if hasattr(self.browser, "get_cdp_endpoint"):
                cdp = await self.browser.get_cdp_endpoint()
        uptime = (time.time() - self.start_time) if self.start_time else 0.0
        return {
            "running": self.browser is not None,
            "backend": self.active_backend,
            "profile": self.active_profile,
            "control_mode": self.control_mode,
            "execution_state": self.execution_state,
            "url": page_url,
            "title": title,
            "cdp": cdp,
            "live_view_url": devtools_url_from_cdp(cdp),
            "capabilities": {
                name: adapter.capabilities for name, adapter in self.adapters.items()
            },
            "intervention": self.intervention,
            "uptime_seconds": round(uptime, 1),
            "recording": self.recorder.active,
            "recording_name": self.recorder.name if self.recorder.active else None,
            "schedules_count": len(self.schedules),
        }

    async def navigate(self, url: str) -> Dict[str, Any]:
        await self.adapters[self.active_backend].navigate(url)
        self.recorder.record("navigate", url=url)
        self.activity.append("agent", "navigate", f"Navigated to {url}", url=url)
        return await self.status()

    async def click(self, selector: str) -> Dict[str, Any]:
        await self.adapters[self.active_backend].click(selector)
        self.recorder.record("click", selector=selector, selector_fallbacks=[])
        self.activity.append("agent", "click", f"Clicked {selector}", selector=selector)
        return await self.status()

    async def fill(self, selector: str, value: str) -> Dict[str, Any]:
        await self.adapters[self.active_backend].fill(selector, value)
        self.recorder.record("fill", selector=selector, value=value)
        self.activity.append("agent", "fill", f"Filled {selector}", selector=selector)
        return await self.status()

    def set_control_mode(self, mode: str) -> Dict[str, Any]:
        if mode not in {"agent", "human", "shared"}:
            raise ValueError("mode must be agent, human, or shared")
        self.control_mode = mode
        self.activity.append(
            "system", "control_mode", f"Control mode set to {mode}", mode=mode
        )
        return {"control_mode": mode}

    def pause(self, reason: str = "manual") -> Dict[str, Any]:
        self.execution_state = "paused"
        self.activity.append("system", "paused", "Execution paused", reason=reason)
        return {"execution_state": self.execution_state, "reason": reason}

    def resume(self) -> Dict[str, Any]:
        self.execution_state = "running"
        self.intervention = None
        self.activity.append("system", "resumed", "Execution resumed")
        return {"execution_state": self.execution_state}

    def request_intervention(self, reason: str, message: str = "") -> Dict[str, Any]:
        self.execution_state = "waiting_for_human"
        self.intervention = {
            "reason": reason,
            "message": message,
            "requested_at": time.time(),
        }
        self.activity.append(
            "system", "intervention_requested", message or reason, reason=reason
        )
        return {
            "execution_state": self.execution_state,
            "intervention": self.intervention,
        }

    def resolve_intervention(self, note: str = "") -> Dict[str, Any]:
        previous = self.intervention
        self.intervention = None
        self.execution_state = "resuming"
        self.activity.append(
            "human",
            "intervention_resolved",
            note or "Intervention resolved",
            previous=previous or {},
        )
        return {"execution_state": self.execution_state, "resolved": True}

    def start_recording(self, name: str, description: str = "") -> Dict[str, Any]:
        self.recorder.start(
            name=name,
            description=description,
            metadata={"profile": self.active_profile, "backend": self.active_backend},
        )
        self.activity.append(
            "system", "recording_started", f"Recording {name}", workflow=name
        )
        return {"recording": True, "workflow": name}

    def save_recording(self) -> Dict[str, Any]:
        workflow = self.recorder.stop()
        validation = validate_workflow(workflow)
        if not validation.valid:
            raise ValueError("; ".join(validation.errors))
        path = self.workflow_root / f"{safe_name(workflow.name)}.yaml"
        path.write_text(workflow_to_yaml_str(workflow), encoding="utf-8")
        self.activity.append(
            "system",
            "workflow_saved",
            f"Saved workflow {workflow.name}",
            path=str(path),
            steps=len(workflow.steps),
        )
        return {
            "workflow": workflow.name,
            "path": str(path),
            "steps": len(workflow.steps),
        }

    async def replay_workflow(
        self, workflow_path: str, variables: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        self.execution_state = "running"
        path = self._resolve_workflow_path(workflow_path)
        workflow = load_workflow(str(path))
        player = WorkflowPlayer(self.require_browser())
        result = await player.execute(workflow, runtime_vars=variables)
        self.execution_state = "completed" if result.success else "failed"
        payload = {
            "success": result.success,
            "steps_executed": result.steps_executed,
            "total_steps": result.total_steps,
            "failed_step": result.failed_step,
            "error_message": result.error_message,
            "checkpoint": result.checkpoint,
        }
        self.activity.append(
            "agent", "workflow_replayed", f"Replayed {workflow.name}", **payload
        )
        return payload

    def list_workflows(self) -> List[Dict[str, Any]]:
        items = []
        for path in sorted(self.workflow_root.glob("*.yaml")):
            items.append(
                {
                    "name": path.stem,
                    "path": str(path),
                    "modified_at": path.stat().st_mtime,
                }
            )
        return items

    def list_profiles(self) -> List[Dict[str, Any]]:
        self.profile_root.mkdir(parents=True, exist_ok=True)
        profiles = sorted(p.name for p in self.profile_root.iterdir() if p.is_dir())
        if "default" not in profiles:
            profiles.insert(0, "default")
        return [
            {"name": name, "active": name == self.active_profile} for name in profiles
        ]

    async def screenshot(self, full_page: bool = True) -> Dict[str, Any]:
        """Capture a screenshot of the current page and persist to runs/."""
        page = self.current_page()
        if page and hasattr(page, "screenshot"):
            ts = int(time.time())
            fname = f"screenshot-{self.active_profile}-{ts}.png"
            path = self.run_root / fname
            path.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(path), full_page=full_page)
            self.activity.append(
                "system",
                "screenshot_captured",
                f"Screenshot saved: {fname}",
                path=str(path),
            )
            return {"success": True, "path": str(path), "filename": fname}
        # Fallback to adapter
        result = await self.adapters[self.active_backend].screenshot()
        return {"success": bool(result), "path": result, "filename": None}

    def get_workflow_content(self, name_or_path: str) -> Dict[str, Any]:
        path = self._resolve_workflow_path(name_or_path)
        content = path.read_text(encoding="utf-8")
        return {"name": path.stem, "path": str(path), "content": content}

    def delete_workflow(self, name_or_path: str) -> Dict[str, Any]:
        path = self._resolve_workflow_path(name_or_path)
        path.unlink(missing_ok=True)
        self.activity.append("system", "workflow_deleted", f"Deleted {path.stem}")
        return {"deleted": str(path), "name": path.stem}

    def list_schedules(self) -> List[Dict[str, Any]]:
        return [dict(s) for s in self.schedules]

    def delete_schedule(self, schedule_id: str) -> Dict[str, Any]:
        before = len(self.schedules)
        self.schedules = [s for s in self.schedules if s.get("id") != schedule_id]
        deleted = len(self.schedules) < before
        if deleted:
            self.activity.append("system", "schedule_deleted", schedule_id)
        return {"deleted": deleted, "id": schedule_id}

    def create_schedule(
        self, workflow_path: str, profile: str, interval_seconds: int
    ) -> Dict[str, Any]:
        schedule = {
            "id": secrets.token_hex(6),
            "workflow_path": workflow_path,
            "profile": profile,
            "interval_seconds": max(1, int(interval_seconds)),
            "next_run_at": time.time() + max(1, int(interval_seconds)),
            "last_result": None,
        }
        self.schedules.append(schedule)
        self.activity.append(
            "system",
            "schedule_created",
            "Scheduled workflow",
            schedule_id=schedule["id"],
        )
        return schedule

    async def run_due_schedules_once(
        self, now: Optional[float] = None
    ) -> List[Dict[str, Any]]:
        now = now or time.time()
        results = []
        for schedule in self.schedules:
            if schedule["next_run_at"] <= now:
                if self.active_profile != schedule["profile"] or not self.browser:
                    await self.start(
                        profile=schedule["profile"], backend=self.active_backend
                    )
                result = await self.replay_workflow(schedule["workflow_path"])
                schedule["last_result"] = result
                schedule["next_run_at"] = now + schedule["interval_seconds"]
                results.append({"schedule_id": schedule["id"], "result": result})
        return results

    def _resolve_workflow_path(self, workflow_path: str) -> Path:
        candidate = Path(workflow_path)
        if not candidate.is_absolute():
            candidate = self.workflow_root / candidate
        resolved = candidate.resolve()
        root = self.workflow_root.resolve()
        if root != resolved and root not in resolved.parents:
            raise ValueError("Workflow path is outside dashboard workflow root")
        if not resolved.exists():
            raise FileNotFoundError(str(resolved))
        return resolved

    def _ensure_backend(self, backend: str) -> None:
        if backend not in self.adapters:
            raise ValueError(f"Unsupported backend: {backend}")


def safe_name(value: str) -> str:
    cleaned = "".join(
        ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in value.strip()
    )
    return cleaned.strip("-") or "workflow"


def devtools_url_from_cdp(cdp: Dict[str, Any]) -> Optional[str]:
    if cdp.get("status") != "enabled":
        return None
    endpoint = cdp.get("ws_endpoint")
    if not endpoint:
        return None
    parsed = urlparse(endpoint)
    ws_target = f"{parsed.netloc}{parsed.path}"
    return f"http://{parsed.netloc}/devtools/inspector.html?ws={quote(ws_target, safe='/:-')}"


class SessionAuth:
    def __init__(self, settings: DashboardSettings):
        self.settings = settings
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def verify_password(self, password: str) -> bool:
        return hmac.compare_digest(password, self.settings.password)

    def create_session(self) -> Dict[str, str]:
        session_id = secrets.token_urlsafe(24)
        csrf = secrets.token_urlsafe(24)
        self.sessions[session_id] = {"csrf": csrf, "last_seen": time.time()}
        return {"session_id": session_id, "signed": self.sign(session_id), "csrf": csrf}

    def sign(self, value: str) -> str:
        sig = hmac.new(
            self.settings.secret_key.encode("utf-8"),
            value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{value}.{sig}"

    def unsign(self, signed: str) -> Optional[str]:
        if "." not in signed:
            return None
        value, sig = signed.rsplit(".", 1)
        expected = hmac.new(
            self.settings.secret_key.encode("utf-8"),
            value.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return value if hmac.compare_digest(sig, expected) else None

    def get_session(self, signed: Optional[str]) -> Optional[Dict[str, Any]]:
        if not signed:
            return None
        session_id = self.unsign(signed)
        if not session_id:
            return None
        session = self.sessions.get(session_id)
        if not session:
            return None
        if time.time() - session["last_seen"] > self.settings.idle_timeout_seconds:
            self.sessions.pop(session_id, None)
            return None
        session["last_seen"] = time.time()
        session["id"] = session_id
        return session

    def destroy(self, signed: Optional[str]) -> None:
        session_id = self.unsign(signed or "")
        if session_id:
            self.sessions.pop(session_id, None)


# ======================= MODERN DASHBOARD TEMPLATES =======================

LOGIN_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Stealth Browser • Sign in</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%233b82f6' stroke-width='2'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' d='M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z'/%3E%3C/svg%3E">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&amp;family=JetBrains+Mono:wght@400;500&amp;display=swap');
    :root { --accent: #3b82f6; }
    body { font-family: 'Inter', system_ui, sans-serif; }
    .mono { font-family: 'JetBrains Mono', ui-monospace, monospace; }
    .glass { background: rgba(24, 24, 27, 0.85); backdrop-filter: blur(20px); }
  </style>
</head>
<body class="bg-zinc-950 text-zinc-200">
  <div class="min-h-screen flex items-center justify-center p-6">
    <div class="w-full max-w-md">
      <!-- Logo / Brand -->
      <div class="flex items-center justify-center gap-3 mb-8">
        <div class="w-10 h-10 rounded-xl bg-zinc-900 border border-zinc-800 flex items-center justify-center">
          <svg xmlns="http://www.w3.org/2000/svg" class="w-6 h-6 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
          </svg>
        </div>
        <div>
          <div class="font-semibold tracking-tighter text-2xl">Stealth Browser</div>
          <div class="text-[10px] text-zinc-500 -mt-1">HERMES DASHBOARD</div>
        </div>
      </div>

      <div class="glass border border-zinc-800 rounded-2xl p-8 shadow-2xl">
        <div class="mb-6">
          <div class="text-xl font-semibold tracking-tight">Welcome back</div>
          <div class="text-sm text-zinc-400 mt-1">Sign in to control the shared browser session.</div>
        </div>

        <form method="post" action="/login" class="space-y-4">
          <div>
            <label class="block text-xs font-medium text-zinc-400 mb-1.5 tracking-wider">PASSWORD</label>
            <div class="relative">
              <input 
                type="password" 
                name="password" 
                id="password"
                autocomplete="current-password"
                class="w-full bg-zinc-950 border border-zinc-800 focus:border-blue-500/70 focus:ring-1 focus:ring-blue-500/30 text-sm rounded-xl px-4 py-3 outline-none transition placeholder:text-zinc-600"
                placeholder="••••••••••••"
                required
                autofocus
              >
              <button type="button" onclick="togglePw(this)" class="absolute right-3 top-3.5 text-zinc-500 hover:text-zinc-300">
                <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>
              </button>
            </div>
          </div>

          <button type="submit"
            class="w-full bg-blue-600 hover:bg-blue-500 active:bg-blue-700 transition-colors text-white font-medium rounded-xl py-3 text-sm tracking-wider shadow-inner">
            SIGN IN TO DASHBOARD
          </button>
        </form>

        <div class="mt-6 text-center">
          <div class="text-[10px] text-zinc-500">Single-user operator console • Session cookies • CSRF protected</div>
        </div>
      </div>

      <div class="mt-6 text-center text-[10px] text-zinc-500">Agentic Stealth Browser • v2</div>
    </div>
  </div>

  <script>
    function togglePw(btn) {
      const input = document.getElementById('password');
      if (input.type === 'password') {
        input.type = 'text';
        btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 5.411m0 0L21 21" /></svg>';
      } else {
        input.type = 'password';
        btn.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" /></svg>';
      }
    }
    // subtle enter hint
    console.log('%c[Stealth] Hermes dashboard login ready', 'color:#3f3f46');
  </script>
</body>
</html>"""

DASHBOARD_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="csrf-token" content="{{ csrf }}">
  <title>Stealth Browser • Hermes</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='%233b82f6' stroke-width='2'%3E%3Cpath stroke-linecap='round' stroke-linejoin='round' d='M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z'/%3E%3C/svg%3E">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&amp;family=JetBrains+Mono:wght@400;500&amp;display=swap');
    :root { --accent: #3b82f6; }
    body { font-family: 'Inter', system_ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    .mono { font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace; }
    .dashboard-bg { background: #09090b; }
    .panel { background: #111113; border: 1px solid #27272a; }
    .section-title { font-size: 10px; letter-spacing: 1.5px; text-transform: uppercase; color: #52525b; font-weight: 600; }
    .status-dot { animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
    .nav-active { background: #18181b; border-color: #3b82f6; }
    .log-line { font-size: 11px; line-height: 1.35; }
    .log-line:hover { background: #18181b; }
    .action-btn { transition: all 0.05s cubic-bezier(0.23, 1, 0.32, 1); }
    .action-btn:active { transform: translateY(1px); }
    .modal { animation: modalPop 0.12s ease-out forwards; }
    @keyframes modalPop { from { opacity: 0; transform: scale(0.96) translateY(4px); } to { opacity: 1; transform: scale(1) translateY(0); } }
    .metric { font-variant-numeric: tabular-nums; }
    .stealth-pill { background: linear-gradient(90deg, #18181b, #27272a); }
    .iframe-container { background: #050507; }
    .x-divider { height: 1px; background: linear-gradient(to right, transparent, #27272a, transparent); }
    .wf-row { transition: background .05s ease; }
    .wf-row:hover { background: #18181b; }
    .toast { animation: toastIn 0.2s ease; }
    @keyframes toastIn { from { opacity:0; transform: translateY(8px) } }
    .subtle-scroll::-webkit-scrollbar { width: 5px; } .subtle-scroll::-webkit-scrollbar-thumb { background: #27272a; border-radius: 20px; }
    .header-gradient { background: #0a0a0b; }
  </style>
</head>
<body class="bg-zinc-950 text-zinc-200 dashboard-bg overflow-hidden">
  <!-- Top Navigation -->
  <header class="h-14 border-b border-zinc-800 header-gradient flex items-center justify-between px-4 z-50 flex-shrink-0">
    <div class="flex items-center gap-3">
      <!-- Brand -->
      <div class="flex items-center gap-2.5">
        <div class="w-8 h-8 rounded-xl bg-zinc-900 border border-zinc-700 flex items-center justify-center shadow-inner">
          <svg xmlns="http://www.w3.org/2000/svg" class="w-4.5 h-4.5 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2.25" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
          </svg>
        </div>
        <div class="leading-none">
          <span class="font-semibold tracking-[-1.2px] text-[17px]">Stealth</span>
          <span class="font-medium text-blue-400 tracking-tight text-[17px]">Browser</span>
        </div>
        <div class="px-1.5 py-px rounded text-[9px] font-mono bg-zinc-900 border border-zinc-800 text-blue-400/70">HERMES</div>
      </div>

      <!-- Global Status -->
      <div id="global-status" 
           class="ml-3 flex items-center gap-2 text-xs font-medium px-3 h-7 rounded-full border border-zinc-800 bg-zinc-900">
        <div class="flex items-center gap-1.5">
          <div id="status-dot" class="w-2 h-2 rounded-full bg-emerald-500 status-dot"></div>
          <span id="status-text" class="font-semibold text-emerald-400">CONNECTED</span>
        </div>
        <div class="w-px h-3 bg-zinc-700"></div>
        <span id="status-meta" class="text-zinc-400 font-mono text-[10px]"></span>
      </div>
    </div>

    <div class="flex items-center gap-2 text-sm">
      <!-- Profile -->
      <div class="flex items-center bg-zinc-900 border border-zinc-800 rounded-full pl-1 pr-2 py-1 text-xs">
        <div class="flex items-center gap-1.5 px-2">
          <span class="text-zinc-500">profile</span>
          <span id="header-profile" onclick="showProfileSwitcher()" 
                class="font-semibold cursor-pointer hover:text-blue-400 transition px-1.5 py-px rounded bg-zinc-950 border border-zinc-800">default</span>
        </div>
      </div>

      <!-- Backend -->
      <div onclick="showBackendSwitcher()" 
           class="flex items-center gap-1.5 px-3 h-8 rounded-full bg-zinc-900 border border-zinc-800 hover:border-zinc-700 cursor-pointer text-xs">
        <span class="text-zinc-500">backend</span>
        <span id="header-backend" class="font-medium text-amber-300">playwright-mcp</span>
      </div>

      <!-- User / Logout -->
      <div class="relative group">
        <button onclick="logout()" 
                class="flex items-center gap-2 pl-2.5 pr-3 h-8 rounded-full bg-zinc-900 border border-zinc-800 hover:bg-zinc-800 text-xs font-medium">
          <div class="w-5 h-5 rounded-full bg-zinc-700 flex items-center justify-center text-[10px] font-bold text-zinc-300">OP</div>
          <span>Operator</span>
          <svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5 text-zinc-400" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M17 16l4-4m0 0l-4-4m4 4H3" /></svg>
        </button>
      </div>
    </div>
  </header>

  <!-- Subtle toolbar / quick actions -->
  <div class="h-11 border-b border-zinc-800 bg-zinc-900/70 flex items-center px-3 gap-2 flex-shrink-0 text-sm">
    <div class="flex items-center gap-1.5">
      <button onclick="startBrowser()" 
              class="action-btn flex items-center gap-1.5 px-3 h-8 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow-sm active:scale-[0.985]">
        <svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132z" /><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 4.01V8" /></svg>
        START
      </button>
      <button onclick="restartBrowser()" 
              class="action-btn px-3 h-8 rounded-xl bg-amber-600/90 hover:bg-amber-500 text-white text-xs font-semibold border border-amber-700/50">RESTART</button>
      <button onclick="stopBrowser()" 
              class="action-btn px-3 h-8 rounded-xl bg-rose-600/90 hover:bg-rose-500 text-white text-xs font-semibold border border-rose-700/50">STOP</button>
    </div>

    <div class="w-px h-5 bg-zinc-700 mx-1"></div>

    <!-- Recording controls -->
    <div id="recording-controls" class="flex items-center gap-2">
      <button onclick="startRecording()" 
              class="action-btn flex items-center gap-1.5 px-3 h-8 text-xs rounded-xl bg-zinc-800 hover:bg-zinc-700 border border-zinc-700 font-medium">
        <span class="text-rose-400">●</span> RECORD
      </button>
      <div id="recording-indicator" class="hidden items-center gap-2 text-xs px-3 h-8 rounded-full bg-rose-950 border border-rose-900 text-rose-400">
        <span class="font-semibold">RECORDING</span> 
        <span id="recording-name" class="font-mono text-rose-300"></span>
        <button onclick="stopRecording()" class="ml-1 px-2 py-0.5 bg-rose-900 hover:bg-rose-800 rounded text-[10px] font-bold">STOP</button>
      </div>
    </div>

    <div class="flex-1"></div>

    <div class="text-[10px] text-zinc-500 font-mono pr-2" id="uptime"></div>
    
    <button onclick="captureScreenshot()" 
            class="flex items-center gap-1.5 text-xs px-3 h-8 rounded-xl border border-zinc-700 bg-zinc-900 hover:bg-zinc-800">
      <svg xmlns="http://www.w3.org/2000/svg" class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 9a2 2 0 012-2 2 2 0 012 2m-2 6h10M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h14a2 2 0 012 2v14a2 2 0 01-2 2h-4" /></svg>
      <span class="font-medium">Screenshot</span>
    </button>
  </div>

  <!-- Main Content -->
  <div class="flex h-[calc(100vh-90px)] overflow-hidden">
    
    <!-- LIVE VIEW -->
    <div class="flex-1 flex flex-col min-w-0 border-r border-zinc-800">
      <div class="flex items-center justify-between px-4 py-2 bg-zinc-900 border-b border-zinc-800 text-xs">
        <div class="flex items-center gap-3">
          <span class="font-semibold tracking-wider text-zinc-300">LIVE SESSION</span>
          <span id="live-url" onclick="copyCurrentUrl()" 
                class="mono max-w-[420px] truncate text-blue-400/80 hover:text-blue-400 cursor-pointer text-[11px] px-2 py-px bg-zinc-950 border border-zinc-800 rounded"></span>
        </div>
        <div class="flex items-center gap-2 text-[10px]">
          <button onclick="refreshLiveView()" class="px-2.5 py-1 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-400 flex items-center gap-1">
            <svg xmlns="http://www.w3.org/2000/svg" class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="3" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.058 11H1M12 3v2m0 16v2m9-9H15m-6 0a8 8 0 01-.937-1.073" /></svg>
            <span>REFRESH</span>
          </button>
          <a id="open-devtools" target="_blank" class="px-2.5 py-1 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-amber-300 flex items-center gap-1 hidden">
            OPEN DEVTOOLS
          </a>
        </div>
      </div>

      <!-- Iframe / Placeholder -->
      <div class="flex-1 relative iframe-container" id="live-container">
        <iframe id="live-iframe" class="w-full h-full bg-black" style="border:0" sandbox="allow-same-origin allow-scripts allow-forms allow-popups"></iframe>
        
        <!-- Placeholder overlay when not running -->
        <div id="live-placeholder" onclick="startBrowser()"
             class="hidden absolute inset-0 flex flex-col items-center justify-center bg-zinc-950/90 cursor-pointer">
          <div class="w-16 h-16 rounded-2xl border border-zinc-800 flex items-center justify-center mb-4">
            <svg xmlns="http://www.w3.org/2000/svg" class="w-8 h-8 text-zinc-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.75" d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
            </svg>
          </div>
          <div class="text-lg font-semibold tracking-tight text-zinc-400">No active browser</div>
          <div class="text-xs text-zinc-500 mt-1">Click anywhere or press Start to launch a session</div>
          <div class="mt-4 text-[10px] px-3 py-1 rounded-full border border-zinc-800 text-blue-400/70">CDP DevTools attached when using cdp-bridge</div>
        </div>
      </div>
    </div>

    <!-- RIGHT RAIL / CONTROLS -->
    <div class="w-80 lg:w-96 bg-zinc-900 flex flex-col border-l border-zinc-800 overflow-hidden flex-shrink-0">
      
      <!-- Quick Navigate -->
      <div class="p-3 border-b border-zinc-800">
        <div class="section-title mb-1.5 px-1">Navigate</div>
        <div class="flex gap-2">
          <input id="nav-url" type="text" placeholder="https://example.com" 
                 class="flex-1 bg-zinc-950 border border-zinc-700 focus:border-blue-500/60 text-sm rounded-xl px-3 py-2 outline-none mono placeholder:text-zinc-600"
                 onkeypress="if(event.key==='Enter') navigateToUrl()">
          <button onclick="navigateToUrl()" 
                  class="px-5 rounded-xl bg-blue-600 hover:bg-blue-500 active:bg-blue-700 font-semibold text-sm">GO</button>
        </div>
        <div class="flex gap-1 mt-2">
          <button onclick="quickAction('click')" class="flex-1 text-xs py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 border border-zinc-700">Click</button>
          <button onclick="quickAction('fill')" class="flex-1 text-xs py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 border border-zinc-700">Fill</button>
          <button onclick="quickAction('type')" class="flex-1 text-xs py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 border border-zinc-700">Type</button>
        </div>
      </div>

      <!-- Human Control -->
      <div class="p-3 border-b border-zinc-800">
        <div class="section-title mb-2 px-1 flex items-center justify-between">
          <span>CONTROL MODE</span>
        </div>
        <div class="flex text-xs font-medium border border-zinc-700 rounded-2xl p-px bg-zinc-950">
          <button data-mode="agent" onclick="setControlMode('agent')" id="mode-agent"
                  class="flex-1 py-1.5 rounded-[15px] hover:bg-zinc-900">Agent</button>
          <button data-mode="shared" onclick="setControlMode('shared')" id="mode-shared"
                  class="flex-1 py-1.5 rounded-[15px] bg-zinc-800">Shared</button>
          <button data-mode="human" onclick="setControlMode('human')" id="mode-human"
                  class="flex-1 py-1.5 rounded-[15px] hover:bg-zinc-900">Human</button>
        </div>
        
        <div class="mt-2">
          <button onclick="requestIntervention()" 
                  class="w-full text-xs py-2 rounded-2xl bg-orange-900/60 hover:bg-orange-900/80 border border-orange-800 text-orange-300 font-medium flex items-center justify-center gap-2">
            <span>REQUEST HUMAN INTERVENTION</span>
          </button>
        </div>
        
        <!-- Intervention banner -->
        <div id="intervention-banner" class="hidden mt-2 p-2 text-xs rounded-2xl bg-orange-950 border border-orange-900 text-orange-200">
          <div class="font-semibold">Waiting for human</div>
          <div id="intervention-reason" class="text-orange-300 text-[10px]"></div>
          <div class="mt-1.5 flex gap-2">
            <button onclick="resolveIntervention()" class="flex-1 py-1 bg-orange-800 hover:bg-orange-700 rounded-xl text-xs font-bold">RESOLVE</button>
          </div>
        </div>
      </div>

      <!-- Power & Backend quick -->
      <div class="p-3 border-b border-zinc-800 text-xs">
        <div class="section-title mb-1.5 px-1">BROWSER</div>
        <div class="grid grid-cols-3 gap-2">
          <button onclick="startBrowser()" class="action-btn py-2 bg-emerald-900/70 hover:bg-emerald-900 border border-emerald-800 rounded-2xl text-emerald-300 text-xs font-bold">START</button>
          <button onclick="restartBrowser()" class="action-btn py-2 bg-amber-900/70 hover:bg-amber-900 border border-amber-800 rounded-2xl text-amber-300 text-xs font-bold">RESTART</button>
          <button onclick="stopBrowser()" class="action-btn py-2 bg-rose-900/70 hover:bg-rose-900 border border-rose-800 rounded-2xl text-rose-300 text-xs font-bold">STOP</button>
        </div>
      </div>

      <!-- Workflows -->
      <div class="flex-1 flex flex-col min-h-0 border-b border-zinc-800">
        <div class="px-3 pt-3 pb-1 flex items-center justify-between">
          <div class="section-title px-1">WORKFLOWS</div>
          <button onclick="showRecordModal()" class="text-blue-400 hover:text-blue-300 text-xs font-semibold px-2 py-0.5 rounded-lg hover:bg-zinc-800">+ RECORD</button>
        </div>
        
        <div id="workflow-list" class="flex-1 overflow-auto px-1.5 subtle-scroll text-xs space-y-px py-1">
          <!-- Populated by JS -->
        </div>
      </div>

      <!-- Activity -->
      <div class="h-52 flex flex-col border-t border-zinc-800 bg-zinc-950/60">
        <div class="px-3 pt-2 pb-1 flex items-center justify-between flex-shrink-0">
          <div class="section-title px-1">ACTIVITY</div>
          <div class="flex items-center gap-2">
            <input id="activity-filter" oninput="filterActivity()" placeholder="filter..." 
                   class="bg-zinc-900 border border-zinc-800 text-[10px] w-20 rounded px-2 py-px outline-none placeholder:text-zinc-600">
            <button onclick="clearActivity()" class="text-zinc-500 hover:text-zinc-300 text-[10px]">CLEAR</button>
            <button onclick="exportActivity()" class="text-zinc-500 hover:text-zinc-300 text-[10px]">EXPORT</button>
          </div>
        </div>
        <div id="activity-log" class="flex-1 overflow-auto font-mono text-[10px] px-1.5 subtle-scroll text-zinc-400 space-y-px leading-tight">
          <!-- JS populated log lines -->
        </div>
      </div>
    </div>
  </div>

  <!-- Toast container -->
  <div id="toast-container" class="fixed bottom-4 right-4 z-[100] space-y-2"></div>

  <!-- Modals -->
  <!-- Record Modal -->
  <div id="modal-record" onclick="if(event.target.id==='modal-record') hideModals()" class="hidden fixed inset-0 bg-black/70 z-50 flex items-center justify-center">
    <div onclick="event.stopImmediatePropagation()" class="modal panel w-full max-w-md rounded-3xl p-6">
      <div class="font-semibold text-lg tracking-tight">Start Workflow Recording</div>
      <div class="text-xs text-zinc-400 mt-0.5">Actions performed via the dashboard will be captured.</div>
      <div class="mt-4 space-y-3">
        <div>
          <label class="text-xs text-zinc-400">WORKFLOW NAME</label>
          <input id="record-name" class="w-full mt-1 bg-zinc-950 border border-zinc-700 rounded-2xl px-4 py-2.5 text-sm" placeholder="linkedin-accept-invites" value="dashboard-session">
        </div>
        <div>
          <label class="text-xs text-zinc-400">DESCRIPTION (OPTIONAL)</label>
          <textarea id="record-desc" class="w-full mt-1 bg-zinc-950 border border-zinc-700 rounded-2xl px-4 py-2 text-sm h-16 resize-y" placeholder="Recorded from Hermes dashboard"></textarea>
        </div>
      </div>
      <div class="mt-5 flex gap-3">
        <button onclick="hideModals()" class="flex-1 py-2.5 rounded-2xl bg-zinc-800 hover:bg-zinc-700 text-sm font-medium">CANCEL</button>
        <button onclick="confirmStartRecording()" class="flex-1 py-2.5 rounded-2xl bg-blue-600 hover:bg-blue-500 text-sm font-semibold">BEGIN RECORDING</button>
      </div>
    </div>
  </div>

  <!-- Replay Variables Modal -->
  <div id="modal-replay" onclick="if(event.target.id==='modal-replay') hideModals()" class="hidden fixed inset-0 bg-black/70 z-50 flex items-center justify-center">
    <div onclick="event.stopImmediatePropagation()" class="modal panel w-full max-w-md rounded-3xl p-6">
      <div class="font-semibold">Replay Workflow</div>
      <div id="replay-workflow-name" class="text-blue-400 font-mono text-xs mt-1"></div>
      
      <div class="mt-4">
        <label class="text-xs text-zinc-400">VARIABLES (JSON)</label>
        <textarea id="replay-vars" class="w-full mono text-xs bg-zinc-950 border border-zinc-700 rounded-2xl p-3 h-28 mt-1">{"name": "Jane"}</textarea>
      </div>
      <div class="mt-4 flex gap-3">
        <button onclick="hideModals()" class="flex-1 py-2 rounded-2xl bg-zinc-800 text-sm">CANCEL</button>
        <button onclick="confirmReplay()" class="flex-1 py-2 rounded-2xl bg-emerald-600 hover:bg-emerald-500 text-sm font-semibold">REPLAY</button>
      </div>
    </div>
  </div>

  <!-- YAML Viewer -->
  <div id="modal-yaml" onclick="if(event.target.id==='modal-yaml') hideModals()" class="hidden fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4">
    <div onclick="event.stopImmediatePropagation()" class="modal panel w-full max-w-2xl rounded-3xl p-6">
      <div class="flex justify-between items-baseline">
        <div>
          <span class="font-semibold">Workflow</span> 
          <span id="yaml-name" class="font-mono text-blue-400"></span>
        </div>
        <button onclick="hideModals()" class="text-zinc-400 hover:text-white">✕</button>
      </div>
      <pre id="yaml-content" class="mt-3 text-xs bg-black border border-zinc-800 p-4 rounded-2xl overflow-auto max-h-[420px] mono text-emerald-300/90"></pre>
      <div class="text-[10px] text-right text-zinc-500 mt-1">Read-only • Stored in ~/.agentic-browser/hermes_dashboard/workflows/</div>
    </div>
  </div>

  <!-- Intervention Modal -->
  <div id="modal-intervention" onclick="if(event.target.id==='modal-intervention') hideModals()" class="hidden fixed inset-0 bg-black/70 z-50 flex items-center justify-center">
    <div onclick="event.stopImmediatePropagation()" class="modal panel w-full max-w-md rounded-3xl p-6">
      <div class="text-orange-400 font-semibold flex items-center gap-2">
        <span>Request Human Intervention</span>
      </div>
      <div class="mt-3 text-xs text-zinc-400">Pauses automation and notifies the operator.</div>
      
      <div class="mt-4 space-y-3 text-sm">
        <div>
          <label class="text-xs text-zinc-400">REASON</label>
          <select id="intervention-reason" class="w-full mt-1 bg-zinc-950 border border-zinc-700 rounded-2xl px-3 py-2">
            <option value="captcha">CAPTCHA / Challenge</option>
            <option value="login">Login Required</option>
            <option value="dom_uncertainty">DOM / Selector Uncertainty</option>
            <option value="rate_limit">Rate Limit / Throttle</option>
            <option value="manual_review">Manual Review</option>
            <option value="other">Other</option>
          </select>
        </div>
        <div>
          <label class="text-xs text-zinc-400">NOTE FOR OPERATOR</label>
          <textarea id="intervention-message" class="w-full mt-1 bg-zinc-950 border border-zinc-700 rounded-2xl px-3 py-2 h-20 text-sm" placeholder="Page shows unusual popup..."></textarea>
        </div>
      </div>
      <div class="mt-5 flex gap-3">
        <button onclick="hideModals()" class="flex-1 py-2.5 rounded-2xl bg-zinc-800 text-sm">CANCEL</button>
        <button onclick="confirmIntervention()" class="flex-1 py-2.5 rounded-2xl bg-orange-600 hover:bg-orange-500 text-sm font-semibold">REQUEST &amp; PAUSE</button>
      </div>
    </div>
  </div>

  <script>
    // ====================== SPA DASHBOARD JS ======================
    const csrfToken = document.querySelector('meta[name="csrf-token"]').content || '';
    let currentStatus = {};
    let allEvents = [];
    let filteredEvents = [];
    let pollInterval = null;
    let lastLiveUrl = '';

    function showToast(message, type = 'success') {
      const c = document.getElementById('toast-container');
      const el = document.createElement('div');
      const colors = type === 'error' ? 'bg-rose-900 border-rose-800 text-rose-200' : 'bg-zinc-900 border-zinc-700 text-zinc-200';
      el.className = `toast max-w-xs px-4 py-2.5 text-sm border rounded-2xl shadow-xl flex items-start gap-3 ${colors}`;
      el.innerHTML = `
        <div class="flex-1">${message}</div>
        <button class="text-xs opacity-60 hover:opacity-100" onclick="this.parentNode.remove()">×</button>
      `;
      c.appendChild(el);
      setTimeout(() => el.remove(), 4200);
    }

    async function apiCall(path, method = 'GET', body = null) {
      const opts = {
        method,
        headers: {
          'content-type': 'application/json',
          'x-csrf-token': csrfToken
        }
      };
      if (body) opts.body = JSON.stringify(body);
      const res = await fetch(path, opts);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || res.statusText);
      }
      return res.json();
    }

    function updateHeader(status) {
      const dot = document.getElementById('status-dot');
      const txt = document.getElementById('status-text');
      const meta = document.getElementById('status-meta');
      
      document.getElementById('header-profile').innerText = status.profile || 'default';
      document.getElementById('header-backend').innerText = status.backend || '—';

      if (status.running) {
        dot.className = 'w-2 h-2 rounded-full bg-emerald-500 status-dot';
        txt.className = 'font-semibold text-emerald-400';
        txt.innerText = 'RUNNING';
        meta.innerText = `${Math.floor((status.uptime_seconds || 0)/60)}m`;
      } else {
        dot.className = 'w-2 h-2 rounded-full bg-rose-500';
        txt.className = 'font-semibold text-rose-400';
        txt.innerText = 'STOPPED';
        meta.innerText = '';
      }
    }

    function updateLiveView(status) {
      const iframe = document.getElementById('live-iframe');
      const placeholder = document.getElementById('live-placeholder');
      const liveUrlEl = document.getElementById('live-url');
      const dtLink = document.getElementById('open-devtools');

      const url = status.url || '';
      liveUrlEl.innerText = url || 'about:blank';
      liveUrlEl.title = url;

      const hasLive = !!status.live_view_url;
      if (hasLive && status.live_view_url !== lastLiveUrl) {
        iframe.src = status.live_view_url;
        lastLiveUrl = status.live_view_url;
      }

      if (status.running) {
        placeholder.classList.add('hidden');
        iframe.classList.remove('hidden');
        dtLink.href = status.live_view_url || '#';
        dtLink.classList.remove('hidden');
      } else {
        placeholder.classList.remove('hidden');
        iframe.classList.add('hidden');
        dtLink.classList.add('hidden');
      }
    }

    function updateUptime(status) {
      const el = document.getElementById('uptime');
      if (!status.running || !status.uptime_seconds) {
        el.innerText = '';
        return;
      }
      const m = Math.floor(status.uptime_seconds / 60);
      const s = Math.floor(status.uptime_seconds % 60);
      el.innerText = `${m}m ${s}s`;
    }

    function updateIntervention(status) {
      const banner = document.getElementById('intervention-banner');
      const reasonEl = document.getElementById('intervention-reason');
      if (status.intervention) {
        banner.classList.remove('hidden');
        reasonEl.innerText = `${status.intervention.reason} — ${status.intervention.message || ''}`;
      } else {
        banner.classList.add('hidden');
      }
    }

    function updateRecording(status) {
      const ind = document.getElementById('recording-indicator');
      const nameEl = document.getElementById('recording-name');
      if (status.recording) {
        ind.classList.remove('hidden');
        ind.classList.add('flex');
        nameEl.innerText = status.recording_name || 'workflow';
      } else {
        ind.classList.add('hidden');
        ind.classList.remove('flex');
      }
    }

    function updateModeButtons(mode) {
      ['agent', 'shared', 'human'].forEach(m => {
        const btn = document.getElementById('mode-' + m);
        if (!btn) return;
        if (m === (mode || 'shared')) {
          btn.classList.add('bg-zinc-800', 'font-semibold');
        } else {
          btn.classList.remove('bg-zinc-800', 'font-semibold');
        }
      });
    }

    function renderWorkflows(workflows) {
      const container = document.getElementById('workflow-list');
      container.innerHTML = '';
      if (!workflows || !workflows.length) {
        container.innerHTML = `<div class="px-3 py-4 text-center text-zinc-600 text-xs">No saved workflows yet</div>`;
        return;
      }
      workflows.slice(0, 8).forEach(wf => {
        const row = document.createElement('div');
        row.className = `wf-row group flex items-center justify-between gap-2 px-2 py-1.5 rounded-xl mx-1 cursor-pointer`;
        row.innerHTML = `
          <div class="flex-1 min-w-0" onclick="replayWorkflow('${wf.path}')">
            <div class="font-medium text-zinc-200 truncate">${wf.name}</div>
            <div class="text-[10px] text-zinc-500 mono">${new Date(wf.modified_at * 1000).toLocaleDateString()}</div>
          </div>
          <div class="flex gap-0.5 opacity-70 group-hover:opacity-100">
            <button onclick="event.stopImmediatePropagation(); viewWorkflow('${wf.name}')" class="p-1 hover:bg-zinc-800 rounded" title="View YAML">👁</button>
            <button onclick="event.stopImmediatePropagation(); replayWorkflow('${wf.path}')" class="p-1 hover:bg-zinc-800 rounded text-emerald-400" title="Replay">▶</button>
            <button onclick="event.stopImmediatePropagation(); deleteWorkflow('${wf.name}')" class="p-1 hover:bg-zinc-800 rounded text-rose-400" title="Delete">×</button>
          </div>
        `;
        container.appendChild(row);
      });
    }

    function renderActivity(events) {
      const container = document.getElementById('activity-log');
      container.innerHTML = '';
      filteredEvents = events || [];
      const frag = document.createDocumentFragment();
      filteredEvents.slice(-40).reverse().forEach(ev => {
        const line = document.createElement('div');
        line.className = `log-line px-1.5 py-px flex gap-2 items-baseline rounded`;
        const srcColor = ev.source === 'error' ? 'text-rose-400' : 
                        ev.source === 'human' ? 'text-orange-400' : 
                        ev.source === 'agent' ? 'text-emerald-400' : 'text-blue-400';
        const time = new Date(ev.ts * 1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'});
        line.innerHTML = `
          <span class="w-8 shrink-0 ${srcColor} font-bold">${ev.source}</span>
          <span class="flex-1 truncate text-zinc-300">${ev.event} <span class="text-zinc-500">${ev.message || ''}</span></span>
          <span class="shrink-0 text-zinc-600 tabular-nums">${time}</span>
        `;
        frag.appendChild(line);
      });
      container.appendChild(frag);
    }

    function filterActivity() {
      const q = document.getElementById('activity-filter').value.toLowerCase();
      const container = document.getElementById('activity-log');
      container.innerHTML = '';
      const filtered = (allEvents || []).filter(e => 
        (e.event || '').toLowerCase().includes(q) || 
        (e.message || '').toLowerCase().includes(q) ||
        (e.source || '').toLowerCase().includes(q)
      );
      const frag = document.createDocumentFragment();
      filtered.slice(-35).reverse().forEach(ev => {
        const line = document.createElement('div');
        line.className = `log-line px-1.5 py-px flex gap-2 items-baseline rounded`;
        const srcColor = ev.source === 'error' ? 'text-rose-400' : ev.source === 'human' ? 'text-orange-400' : ev.source === 'agent' ? 'text-emerald-400' : 'text-blue-400';
        const time = new Date(ev.ts * 1000).toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'});
        line.innerHTML = `<span class="w-8 shrink-0 ${srcColor} font-bold">${ev.source}</span><span class="flex-1 truncate text-zinc-300">${ev.event} <span class="text-zinc-500">${ev.message || ''}</span></span><span class="shrink-0 text-zinc-600 tabular-nums">${time}</span>`;
        frag.appendChild(line);
      });
      container.appendChild(frag);
    }

    function clearActivity() {
      allEvents = [];
      document.getElementById('activity-log').innerHTML = '';
    }

    async function exportActivity() {
      try {
        const data = await apiCall('/api/logs/export');
        const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `hermes-activity-${Date.now()}.json`;
        a.click();
      } catch (e) { showToast('Export failed: ' + e.message, 'error'); }
    }

    async function refreshAll() {
      try {
        const [status, evData] = await Promise.all([
          apiCall('/api/status'),
          apiCall('/api/events?limit=80')
        ]);
        currentStatus = status;
        allEvents = evData.events || [];

        updateHeader(status);
        updateLiveView(status);
        updateUptime(status);
        updateIntervention(status);
        updateRecording(status);
        updateModeButtons(status.control_mode);

        // workflows
        const wfData = await apiCall('/api/workflows');
        renderWorkflows(wfData.workflows || []);

        renderActivity(allEvents);

        // placeholder visibility handled in updateLiveView
      } catch (err) {
        console.warn('[Hermes] poll error', err);
        document.getElementById('status-text').innerText = 'DISCONNECTED';
        document.getElementById('status-dot').className = 'w-2 h-2 rounded-full bg-zinc-600';
      }
    }

    function startPolling() {
      if (pollInterval) clearInterval(pollInterval);
      pollInterval = setInterval(refreshAll, 2200);
      refreshAll(); // immediate
    }

    // === ACTIONS ===
    async function postAction(path, payload = {}) {
      try {
        const res = await apiCall(path, 'POST', payload);
        showToast('Action successful');
        await refreshAll();
        return res;
      } catch (e) {
        showToast(e.message || 'Action failed', 'error');
        throw e;
      }
    }

    function navigateToUrl() {
      const val = document.getElementById('nav-url').value.trim();
      if (!val) return;
      postAction('/api/browser/navigate', { url: val });
      document.getElementById('nav-url').value = '';
    }

    function startBrowser() {
      const profile = prompt('Profile name (leave blank for default):', currentStatus.profile || 'default') || 'default';
      postAction('/api/browser/start', { profile, backend: currentStatus.backend || 'playwright-mcp' });
    }
    function restartBrowser() { postAction('/api/browser/restart'); }
    function stopBrowser() { postAction('/api/browser/stop'); }

    async function captureScreenshot() {
      try {
        const res = await postAction('/api/browser/screenshot', { full_page: true });
        showToast('Screenshot captured: ' + (res.filename || res.path || 'ok'));
      } catch(e){}
    }

    async function setControlMode(mode) {
      try {
        await apiCall('/api/control/mode', 'POST', { mode });
        showToast('Mode → ' + mode);
        await refreshAll();
      } catch(e) { showToast(e.message, 'error'); }
    }

    function requestIntervention() {
      document.getElementById('modal-intervention').classList.remove('hidden');
      document.getElementById('modal-intervention').classList.add('flex');
    }
    async function confirmIntervention() {
      const reason = document.getElementById('intervention-reason').value;
      const msg = document.getElementById('intervention-message').value;
      hideModals();
      try {
        await apiCall('/api/intervention/request', 'POST', { reason, message: msg });
        showToast('Intervention requested');
        await refreshAll();
      } catch(e){}
    }
    async function resolveIntervention() {
      const note = prompt('Resolution note (optional):') || '';
      await postAction('/api/intervention/resolve', { note });
    }

    function showRecordModal() {
      document.getElementById('modal-record').classList.remove('hidden');
      document.getElementById('modal-record').classList.add('flex');
      document.getElementById('record-name').focus();
      document.getElementById('record-name').select();
    }
    async function confirmStartRecording() {
      const name = document.getElementById('record-name').value.trim() || 'dashboard-recording';
      const desc = document.getElementById('record-desc').value.trim();
      hideModals();
      try {
        await apiCall('/api/workflows/record/start', 'POST', { name, description: desc });
        showToast('Recording started');
        await refreshAll();
      } catch(e){}
    }
    async function stopRecording() {
      try {
        const saved = await apiCall('/api/workflows/record/save', 'POST');
        showToast('Saved workflow: ' + saved.workflow);
        await refreshAll();
      } catch(e){}
    }

    async function replayWorkflow(path) {
      document.getElementById('modal-replay').classList.remove('hidden');
      document.getElementById('modal-replay').classList.add('flex');
      document.getElementById('replay-workflow-name').innerText = path.split('/').pop();
      window._pendingReplayPath = path;
    }
    async function confirmReplay() {
      const path = window._pendingReplayPath;
      let vars = {};
      try { vars = JSON.parse(document.getElementById('replay-vars').value || '{}'); } catch { vars = {}; }
      hideModals();
      try {
        await apiCall('/api/workflows/replay', 'POST', { path, variables: vars });
        showToast('Replay initiated');
        await refreshAll();
      } catch(e){}
    }

    async function viewWorkflow(name) {
      try {
        const data = await apiCall('/api/workflows/' + encodeURIComponent(name));
        document.getElementById('yaml-name').innerText = data.name;
        document.getElementById('yaml-content').innerText = data.content || '(empty)';
        document.getElementById('modal-yaml').classList.remove('hidden');
        document.getElementById('modal-yaml').classList.add('flex');
      } catch(e) { showToast('Failed to load workflow', 'error'); }
    }

    async function deleteWorkflow(name) {
      if (!confirm('Delete workflow ' + name + '?')) return;
      try {
        await apiCall('/api/workflows/' + encodeURIComponent(name), 'DELETE');
        showToast('Workflow deleted');
        await refreshAll();
      } catch(e){}
    }

    async function quickAction(kind) {
      if (kind === 'click') {
        const sel = prompt('Selector to click:');
        if (sel) await postAction('/api/browser/click', { selector: sel });
      } else if (kind === 'fill' || kind === 'type') {
        const sel = prompt('Selector:');
        const val = prompt('Value:');
        if (sel && val !== null) {
          const ep = kind === 'fill' ? '/api/browser/fill' : '/api/browser/fill'; // type falls back
          await postAction('/api/browser/fill', { selector: sel, value: val });
        }
      }
    }

    function refreshLiveView() {
      const iframe = document.getElementById('live-iframe');
      const src = iframe.src;
      iframe.src = '';
      setTimeout(() => { iframe.src = src; }, 40);
    }

    function copyCurrentUrl() {
      const url = document.getElementById('live-url').innerText;
      if (url) {
        navigator.clipboard.writeText(url).then(() => showToast('URL copied'));
      }
    }

    function showBackendSwitcher() {
      const backends = ['playwright-mcp', 'agentic-stealth-mcp', 'cdp-bridge'];
      const current = currentStatus.backend;
      const choice = prompt('Switch backend to:\n' + backends.join('\n'), current);
      if (choice && backends.includes(choice)) {
        postAction('/api/backend/switch', { backend: choice });
      }
    }

    function showProfileSwitcher() {
      const p = prompt('Switch / create profile:', currentStatus.profile || 'default');
      if (!p) return;
      // For simplicity we just start with that profile (will switch or launch)
      postAction('/api/browser/start', { profile: p, backend: currentStatus.backend });
    }

    async function logout() {
      if (!confirm('Log out of dashboard?')) return;
      await fetch('/logout', { method: 'POST' });
      window.location = '/login';
    }

    function hideModals() {
      document.querySelectorAll('[id^="modal-"]').forEach(m => {
        m.classList.remove('flex');
        m.classList.add('hidden');
      });
    }

    function navigateToUrlOnEnter(e) {
      if (e.key === 'Enter') navigateToUrl();
    }

    function initKeyboard() {
      document.addEventListener('keydown', (e) => {
        if (e.key === '/' && document.activeElement.tagName === 'BODY') {
          e.preventDefault();
          document.getElementById('nav-url').focus();
        }
        if (e.metaKey && e.key.toLowerCase() === 'k') {
          e.preventDefault();
          const url = document.getElementById('nav-url');
          url.focus();
          url.select();
        }
      });
      document.getElementById('nav-url').addEventListener('keypress', navigateToUrlOnEnter);
    }

    function bootstrap() {
      initKeyboard();
      // Seed some initial state from server render if present (future)
      startPolling();
      // Gentle welcome hint
      setTimeout(() => {
        if (!currentStatus.running) {
          // no-op, placeholder already helpful
        }
      }, 800);
      // Keyboard hint in console only
      console.log('%c[Stealth Hermes] Press / to focus URL bar. Cmd/Ctrl+K for quick nav.', 'color:#3f3f46');
    }

    window.addEventListener('load', bootstrap);
    window.addEventListener('beforeunload', () => { if (pollInterval) clearInterval(pollInterval); });
  </script>
</body>
</html>"""


def create_app(
    manager: Optional[BrowserRuntimeManager] = None,
    settings: Optional[DashboardSettings] = None,
):
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

    settings = settings or DashboardSettings()
    manager = manager or BrowserRuntimeManager()
    auth = SessionAuth(settings)
    app = FastAPI(title="Hermes Browser Dashboard", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["content-type", "x-csrf-token"],
    )

    def current_session(request: Request) -> Dict[str, Any]:
        session = auth.get_session(request.cookies.get(settings.cookie_name))
        if not session:
            raise HTTPException(status_code=401, detail="Authentication required")
        return session

    async def require_csrf(request: Request, session: Dict[str, Any]) -> Dict[str, Any]:
        token = request.headers.get("x-csrf-token")
        if not token:
            try:
                body = await request.json()
                token = body.get("csrf")
            except Exception:
                token = None
        if not token or not hmac.compare_digest(token, session["csrf"]):
            raise HTTPException(status_code=403, detail="Invalid CSRF token")
        try:
            return await request.json()
        except Exception:
            return {}

    @app.get("/login", response_class=HTMLResponse)
    async def login_page() -> str:
        from jinja2 import Template as JTemplate

        return JTemplate(LOGIN_TEMPLATE).render()

    @app.post("/login")
    async def login(request: Request):
        raw = (await request.body()).decode("utf-8", errors="replace")
        password = parse_qs(raw).get("password", [""])[0]
        if not auth.verify_password(password):
            raise HTTPException(status_code=401, detail="Invalid password")
        created = auth.create_session()
        response = RedirectResponse("/", status_code=303)
        response.set_cookie(
            settings.cookie_name,
            created["signed"],
            httponly=True,
            secure=settings.cookie_secure,
            samesite="lax",
            max_age=settings.idle_timeout_seconds,
        )
        return response

    @app.post("/logout")
    async def logout(request: Request):
        auth.destroy(request.cookies.get(settings.cookie_name))
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(settings.cookie_name)
        return response

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        try:
            session = current_session(request)
        except HTTPException:
            return RedirectResponse("/login", status_code=303)
        from jinja2 import Template as JTemplate

        # Render the rich self-contained dashboard shell. CSRF is embedded via meta tag.
        # The frontend JS hydrates all state via polling.
        return JTemplate(DASHBOARD_TEMPLATE).render(csrf=session["csrf"])

    @app.get("/api/status")
    async def api_status(request: Request):
        current_session(request)
        return await manager.status()

    @app.get("/api/events")
    async def api_events(request: Request, limit: int = 100):
        current_session(request)
        return {"events": manager.activity.list(limit=limit)}

    @app.get("/api/logs/export")
    async def api_logs(request: Request):
        current_session(request)
        return manager.activity.export()

    @app.post("/api/browser/start")
    async def api_start(request: Request):
        session = current_session(request)
        data = await require_csrf(request, session)
        return await manager.start(
            profile=data.get("profile", "default"),
            backend=data.get("backend", manager.active_backend),
        )

    @app.post("/api/browser/stop")
    async def api_stop(request: Request):
        session = current_session(request)
        await require_csrf(request, session)
        return await manager.stop()

    @app.post("/api/browser/restart")
    async def api_restart(request: Request):
        session = current_session(request)
        await require_csrf(request, session)
        return await manager.restart()

    @app.post("/api/browser/navigate")
    async def api_navigate(request: Request):
        session = current_session(request)
        data = await require_csrf(request, session)
        return await manager.navigate(str(data.get("url") or "about:blank"))

    @app.post("/api/browser/click")
    async def api_click(request: Request):
        session = current_session(request)
        data = await require_csrf(request, session)
        return await manager.click(str(data.get("selector") or ""))

    @app.post("/api/browser/fill")
    async def api_fill(request: Request):
        session = current_session(request)
        data = await require_csrf(request, session)
        return await manager.fill(
            str(data.get("selector") or ""), str(data.get("value") or "")
        )

    @app.post("/api/backend/switch")
    async def api_switch(request: Request):
        session = current_session(request)
        data = await require_csrf(request, session)
        return await manager.switch_backend(str(data.get("backend") or ""))

    @app.post("/api/control/mode")
    async def api_mode(request: Request):
        session = current_session(request)
        data = await require_csrf(request, session)
        return manager.set_control_mode(str(data.get("mode") or "shared"))

    @app.post("/api/control/pause")
    async def api_pause(request: Request):
        session = current_session(request)
        data = await require_csrf(request, session)
        return manager.pause(str(data.get("reason") or "manual"))

    @app.post("/api/control/resume")
    async def api_resume(request: Request):
        session = current_session(request)
        await require_csrf(request, session)
        return manager.resume()

    @app.post("/api/intervention/request")
    async def api_intervention_request(request: Request):
        session = current_session(request)
        data = await require_csrf(request, session)
        return manager.request_intervention(
            str(data.get("reason") or "manual_review"), str(data.get("message") or "")
        )

    @app.post("/api/intervention/resolve")
    async def api_intervention_resolve(request: Request):
        session = current_session(request)
        data = await require_csrf(request, session)
        return manager.resolve_intervention(str(data.get("note") or ""))

    @app.post("/api/workflows/record/start")
    async def api_record_start(request: Request):
        session = current_session(request)
        data = await require_csrf(request, session)
        return manager.start_recording(
            str(data.get("name") or "dashboard-demo"),
            str(data.get("description") or ""),
        )

    @app.post("/api/workflows/record/save")
    async def api_record_save(request: Request):
        session = current_session(request)
        await require_csrf(request, session)
        return manager.save_recording()

    @app.get("/api/workflows")
    async def api_workflows(request: Request):
        current_session(request)
        return {"workflows": manager.list_workflows()}

    @app.post("/api/workflows/replay")
    async def api_replay(request: Request):
        session = current_session(request)
        data = await require_csrf(request, session)
        return await manager.replay_workflow(
            str(data.get("path") or ""), dict(data.get("variables") or {})
        )

    @app.get("/api/profiles")
    async def api_profiles(request: Request):
        current_session(request)
        return {"profiles": manager.list_profiles()}

    @app.post("/api/schedules")
    async def api_schedule(request: Request):
        session = current_session(request)
        data = await require_csrf(request, session)
        return manager.create_schedule(
            workflow_path=str(data.get("workflow_path") or ""),
            profile=str(data.get("profile") or manager.active_profile),
            interval_seconds=int(data.get("interval_seconds") or 3600),
        )

    @app.get("/api/schedules")
    async def api_schedules_list(request: Request):
        current_session(request)
        return {"schedules": manager.list_schedules()}

    @app.delete("/api/schedules/{schedule_id}")
    async def api_schedule_delete(request: Request, schedule_id: str):
        current_session(request)
        return manager.delete_schedule(schedule_id)

    @app.post("/api/browser/screenshot")
    async def api_screenshot(request: Request):
        session = current_session(request)
        await require_csrf(request, session)
        try:
            data = await request.json()
        except Exception:
            data = {}
        full = bool(data.get("full_page", True))
        return await manager.screenshot(full_page=full)

    @app.get("/api/workflows/{name}")
    async def api_workflow_content(request: Request, name: str):
        current_session(request)
        return manager.get_workflow_content(name)

    @app.delete("/api/workflows/{name}")
    async def api_workflow_delete(request: Request, name: str):
        current_session(request)
        return manager.delete_workflow(name)

    @app.exception_handler(Exception)
    async def error_handler(request: Request, exc: Exception):
        _ = request
        manager.activity.append("error", "request_failed", str(exc))
        return JSONResponse({"error": str(exc)}, status_code=500)

    app.state.hermes_manager = manager
    app.state.hermes_auth = auth
    return app


def run_dashboard(
    host: str = "127.0.0.1", port: int = 8443, password: Optional[str] = None
) -> None:
    import os

    import uvicorn

    settings = DashboardSettings(
        host=host,
        port=port,
        password=password or os.getenv("HERMES_DASHBOARD_PASSWORD", "change-me"),
    )
    app = create_app(settings=settings)

    # Run uvicorn in a subprocess to avoid asyncio.Runner conflicts when
    # embedded in a process that already has a running event loop.
    import multiprocessing

    def _start_server():
        uvicorn.run(app, host=host, port=port, loop="asyncio")

    p = multiprocessing.Process(target=_start_server, daemon=True)
    p.start()
    p.join()
