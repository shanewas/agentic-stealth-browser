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
from workflows.schema import Workflow, WorkflowStep, load_workflow, validate_workflow, workflow_to_yaml_str


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
    allowed_origins: List[str] = field(default_factory=lambda: ["http://127.0.0.1:8443", "http://localhost:8443"])


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

    def append(self, source: str, event: str, message: str, **details: Any) -> ActivityEvent:
        item = ActivityEvent(source=source, event=event, message=message, details=details)
        self._events.append(item)
        if len(self._events) > self.max_events:
            self._events = self._events[-self.max_events :]
        return item

    def list(self, limit: int = 100, source: Optional[str] = None) -> List[Dict[str, Any]]:
        events = self._events
        if source:
            events = [e for e in events if e.source == source]
        return [e.to_dict() for e in events[-limit:]]

    def export(self) -> Dict[str, Any]:
        return {"events": [e.to_dict() for e in self._events], "count": len(self._events)}


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
        await self.manager._launch_browser(profile=profile, backend=self.name, headless=headless)

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
            await page.evaluate(f"document.querySelector({json.dumps(selector)}).click()")
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
            await page.evaluate(f"document.querySelector({json.dumps(selector)}).value = {json.dumps(value)}")
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
        await self.manager._launch_browser(profile=profile, backend=self.name, headless=headless, debug_cdp=True)

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

    def start(self, name: str, description: str = "", metadata: Optional[Dict[str, Any]] = None) -> None:
        self.active = True
        self.name = name
        self.description = description
        self.steps = []
        self.metadata = dict(metadata or {})

    def stop(self) -> Workflow:
        self.active = False
        return Workflow(name=self.name, description=self.description, steps=list(self.steps), metadata=dict(self.metadata))

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

    async def _launch_browser(self, profile: str, backend: str, headless: bool = True, debug_cdp: bool = False) -> None:
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
        self.activity.append("system", "browser_started", f"Started {backend}", profile=profile, debug_cdp=debug_cdp)

    async def _close_browser(self) -> None:
        if self.browser and hasattr(self.browser, "close"):
            await self.browser.close()
        self.browser = None

    def require_browser(self) -> Any:
        if not self.browser:
            raise RuntimeError("Browser is not running")
        return self.browser

    def current_page(self) -> Any:
        browser = self.require_browser()
        if hasattr(browser, "page_getter"):
            return browser.page_getter()
        return getattr(browser, "page", None)

    async def start(self, profile: str = "default", backend: str = "playwright-mcp", headless: bool = True) -> Dict[str, Any]:
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
        self.activity.append("system", "browser_restarted", "Browser restarted", profile=profile, backend=backend)
        return await self.status()

    async def switch_backend(self, backend: str) -> Dict[str, Any]:
        self._ensure_backend(backend)
        warning = "Switch relaunches the managed browser while preserving the active profile name."
        await self.start(profile=self.active_profile, backend=backend)
        self.activity.append("system", "backend_switched", f"Switched to {backend}", warning=warning)
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
            "capabilities": {name: adapter.capabilities for name, adapter in self.adapters.items()},
            "intervention": self.intervention,
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
        self.activity.append("system", "control_mode", f"Control mode set to {mode}", mode=mode)
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
        self.intervention = {"reason": reason, "message": message, "requested_at": time.time()}
        self.activity.append("system", "intervention_requested", message or reason, reason=reason)
        return {"execution_state": self.execution_state, "intervention": self.intervention}

    def resolve_intervention(self, note: str = "") -> Dict[str, Any]:
        previous = self.intervention
        self.intervention = None
        self.execution_state = "resuming"
        self.activity.append("human", "intervention_resolved", note or "Intervention resolved", previous=previous or {})
        return {"execution_state": self.execution_state, "resolved": True}

    def start_recording(self, name: str, description: str = "") -> Dict[str, Any]:
        self.recorder.start(name=name, description=description, metadata={"profile": self.active_profile, "backend": self.active_backend})
        self.activity.append("system", "recording_started", f"Recording {name}", workflow=name)
        return {"recording": True, "workflow": name}

    def save_recording(self) -> Dict[str, Any]:
        workflow = self.recorder.stop()
        validation = validate_workflow(workflow)
        if not validation.valid:
            raise ValueError("; ".join(validation.errors))
        path = self.workflow_root / f"{safe_name(workflow.name)}.yaml"
        path.write_text(workflow_to_yaml_str(workflow), encoding="utf-8")
        self.activity.append("system", "workflow_saved", f"Saved workflow {workflow.name}", path=str(path), steps=len(workflow.steps))
        return {"workflow": workflow.name, "path": str(path), "steps": len(workflow.steps)}

    async def replay_workflow(self, workflow_path: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
        self.activity.append("agent", "workflow_replayed", f"Replayed {workflow.name}", **payload)
        return payload

    def list_workflows(self) -> List[Dict[str, Any]]:
        items = []
        for path in sorted(self.workflow_root.glob("*.yaml")):
            items.append({"name": path.stem, "path": str(path), "modified_at": path.stat().st_mtime})
        return items

    def list_profiles(self) -> List[Dict[str, Any]]:
        self.profile_root.mkdir(parents=True, exist_ok=True)
        profiles = sorted(p.name for p in self.profile_root.iterdir() if p.is_dir())
        if "default" not in profiles:
            profiles.insert(0, "default")
        return [{"name": name, "active": name == self.active_profile} for name in profiles]

    def create_schedule(self, workflow_path: str, profile: str, interval_seconds: int) -> Dict[str, Any]:
        schedule = {
            "id": secrets.token_hex(6),
            "workflow_path": workflow_path,
            "profile": profile,
            "interval_seconds": max(1, int(interval_seconds)),
            "next_run_at": time.time() + max(1, int(interval_seconds)),
            "last_result": None,
        }
        self.schedules.append(schedule)
        self.activity.append("system", "schedule_created", "Scheduled workflow", schedule_id=schedule["id"])
        return schedule

    async def run_due_schedules_once(self, now: Optional[float] = None) -> List[Dict[str, Any]]:
        now = now or time.time()
        results = []
        for schedule in self.schedules:
            if schedule["next_run_at"] <= now:
                if self.active_profile != schedule["profile"] or not self.browser:
                    await self.start(profile=schedule["profile"], backend=self.active_backend)
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
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in value.strip())
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
        sig = hmac.new(self.settings.secret_key.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{value}.{sig}"

    def unsign(self, signed: str) -> Optional[str]:
        if "." not in signed:
            return None
        value, sig = signed.rsplit(".", 1)
        expected = hmac.new(self.settings.secret_key.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()
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


INDEX_TEMPLATE = """
<!doctype html>
<html><head><meta charset="utf-8"><title>Hermes Browser Dashboard</title>
<style>
body{margin:0;font-family:Segoe UI,Arial,sans-serif;background:#111;color:#eee}
header{height:44px;display:flex;align-items:center;gap:12px;padding:0 14px;background:#1e1f22;border-bottom:1px solid #333}
main{display:grid;grid-template-columns:1fr 360px;height:calc(100vh - 44px)}
iframe,.empty{width:100%;height:100%;border:0;background:#202124}
aside{border-left:1px solid #333;background:#17181a;padding:12px;overflow:auto}
button,select,input{background:#2d2f34;color:#fff;border:1px solid #444;padding:7px;border-radius:4px}
.row{display:flex;gap:8px;margin-bottom:10px}.muted{color:#aaa;font-size:12px}.event{font-size:12px;border-bottom:1px solid #2a2a2a;padding:6px 0}
</style></head>
<body>
<header><strong>Hermes Browser</strong><span>{{ status.backend }}</span><span class="muted">{{ status.profile }}</span></header>
<main>
{% if status.live_view_url %}<iframe src="{{ status.live_view_url }}"></iframe>{% else %}<div class="empty"></div>{% endif %}
<aside>
<div class="row"><button data-action="/api/browser/start">Start</button><button data-action="/api/browser/restart">Restart</button><button data-action="/api/browser/stop">Stop</button></div>
<div class="row"><select id="backend">{% for b in backends %}<option value="{{ b }}" {% if b == status.backend %}selected{% endif %}>{{ b }}</option>{% endfor %}</select><button id="switch">Switch</button></div>
<input id="url" placeholder="https://example.com" style="width:100%;box-sizing:border-box"><div class="row"><button id="go">Navigate</button><button data-action="/api/control/pause">Pause</button><button data-action="/api/control/resume">Resume</button></div>
<h3>Timeline</h3>{% for e in events %}<div class="event"><b>{{ e.source }}</b> {{ e.event }}<br><span class="muted">{{ e.message }}</span></div>{% endfor %}
</aside></main>
<script>
const csrf="{{ csrf }}";
async function post(url,data={}){await fetch(url,{method:"POST",headers:{"content-type":"application/json","x-csrf-token":csrf},body:JSON.stringify(data)});location.reload();}
document.querySelectorAll("[data-action]").forEach(b=>b.onclick=()=>post(b.dataset.action));
document.getElementById("switch").onclick=()=>post("/api/backend/switch",{backend:document.getElementById("backend").value});
document.getElementById("go").onclick=()=>post("/api/browser/navigate",{url:document.getElementById("url").value});
</script></body></html>
"""


def create_app(
    manager: Optional[BrowserRuntimeManager] = None,
    settings: Optional[DashboardSettings] = None,
):
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
    from jinja2 import Template

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
        return "<form method='post'><input type='password' name='password' autofocus><button>Login</button></form>"

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
        status = await manager.status()
        return Template(INDEX_TEMPLATE).render(
            status=status,
            events=manager.activity.list(limit=40),
            csrf=session["csrf"],
            backends=SUPPORTED_BACKENDS,
        )

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
        return await manager.start(profile=data.get("profile", "default"), backend=data.get("backend", manager.active_backend))

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
        return await manager.fill(str(data.get("selector") or ""), str(data.get("value") or ""))

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
        return manager.request_intervention(str(data.get("reason") or "manual_review"), str(data.get("message") or ""))

    @app.post("/api/intervention/resolve")
    async def api_intervention_resolve(request: Request):
        session = current_session(request)
        data = await require_csrf(request, session)
        return manager.resolve_intervention(str(data.get("note") or ""))

    @app.post("/api/workflows/record/start")
    async def api_record_start(request: Request):
        session = current_session(request)
        data = await require_csrf(request, session)
        return manager.start_recording(str(data.get("name") or "dashboard-demo"), str(data.get("description") or ""))

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
        return await manager.replay_workflow(str(data.get("path") or ""), dict(data.get("variables") or {}))

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

    @app.exception_handler(Exception)
    async def error_handler(request: Request, exc: Exception):
        _ = request
        manager.activity.append("error", "request_failed", str(exc))
        return JSONResponse({"error": str(exc)}, status_code=500)

    app.state.hermes_manager = manager
    app.state.hermes_auth = auth
    return app


def run_dashboard(host: str = "127.0.0.1", port: int = 8443, password: Optional[str] = None) -> None:
    import os

    import uvicorn

    settings = DashboardSettings(host=host, port=port, password=password or os.getenv("HERMES_DASHBOARD_PASSWORD", "change-me"))
    app = create_app(settings=settings)
    uvicorn.run(app, host=host, port=port)
