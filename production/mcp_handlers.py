from __future__ import annotations

import asyncio
import ipaddress
import logging
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict

import fnmatch

from production.approval_gate import ApprovalDecision

# ponytail: the extracted handler block only actually references the names
# above (plus ToolError/SERVER_*/is_url_safe/is_loopback_host, imported at
# the bottom of this file — see comment there). Names from the original
# mcp_server.py import block that aren't used by these 18 methods
# (argparse, json, os, socket, sys, dataclass, Awaitable, Callable, Optional,
# AuditLogger, FileAccessPolicy, LLMAuthorizationPolicy, MCPSecurityContext,
# sanitize_tool_description, ApprovalGate, InputValidationError,
# validate_tool_input, PolicyEngine) are intentionally dropped to keep
# `ruff check` (F401) green; re-add if a future handler needs one.


class _MCPToolHandlers:
    async def _tool_stealth_launch(self, args: Dict[str, Any]) -> Dict[str, Any]:
        session_name = str(args.get("session_name") or "default")
        headless = bool(args.get("headless", True))
        debug = bool(args.get("debug", False))
        debug_cdp = bool(args.get("debug_cdp", False))
        preset = args.get("preset")
        region = args.get("region")
        anonymous = bool(args.get("anonymous", True))
        ephemeral = bool(args.get("ephemeral", False))
        light_mode = bool(args.get("light_mode", False))
        use_pooled_context = bool(args.get("use_pooled_context", False))

        if session_name in self._sessions:
            try:
                await self._sessions[session_name].close()
            except Exception:
                logging.getLogger(__name__).debug("suppressed exception", exc_info=True)
            finally:
                self._sessions.pop(session_name, None)

        AgentBrowser = self._get_agent_browser_cls()
        browser = AgentBrowser(
            session_name=session_name,
            anonymous=anonymous,
            ephemeral=ephemeral,
            light_mode=light_mode,
            use_pooled_context=use_pooled_context,
        )
        await browser.launch(
            headless=headless,
            debug=debug,
            debug_cdp=debug_cdp,
            preset=preset,
            region=region,
        )

        self._sessions[session_name] = browser
        self._active_session = session_name

        health = await browser.get_health_status()
        return self._tool_ok_payload(
            {
                "session_name": session_name,
                "launched": True,
                "preset": browser.current_preset,
                "region": browser.current_region,
                "health": health,
            }
        )

    async def _tool_stealth_navigate(self, args: Dict[str, Any]) -> Dict[str, Any]:
        url = args.get("url")
        if not url:
            raise ToolError("MCP_VALIDATION_ERROR", "url is required")
        if not is_url_safe(str(url)):
            raise ToolError(
                "MCP_SSRF_BLOCKED",
                "URL resolves to a private or blocked address",
            )
        session_name, browser = await self._resolve_browser(args.get("session_name"))
        platform = str(args.get("platform") or "unknown")
        warm_up = bool(args.get("warm_up", True))
        rate_limit = bool(args.get("rate_limit", True))
        respect_robots = bool(args.get("respect_robots", False))
        domain = args.get("domain")
        account = args.get("account")

        ok = await browser.safe_goto(
            str(url),
            warm_up=warm_up,
            platform=platform,
            rate_limit=rate_limit,
            respect_robots=respect_robots,
            domain=domain,
            account=account,
        )
        if not ok:
            raise ToolError(
                "MCP_NAVIGATION_FAILED",
                "Navigation failed or blocked.",
                {"url": url, "platform": platform},
            )

        current_url = None
        try:
            p = browser.page_getter()
            current_url = getattr(p, "url", None) if p else None
        except Exception:
            current_url = None

        return self._tool_ok_payload(
            {
                "session_name": session_name,
                "url": str(url),
                "current_url": current_url,
                "platform": platform,
                "navigated": True,
            }
        )

    async def _tool_stealth_load_cookies(self, args: Dict[str, Any]) -> Dict[str, Any]:
        cookies_path = args.get("cookies_path")
        if not cookies_path:
            raise ToolError("MCP_VALIDATION_ERROR", "cookies_path is required")

        allowed, reason = self.security.check_file_access(str(cookies_path))
        if not allowed:
            raise ToolError(
                "MCP_SECURITY_PATH_DENIED",
                "cookies_path is not allowed by MCP security policy",
                {"path": str(cookies_path), "reason": reason},
            )

        session_name, browser = await self._resolve_browser(args.get("session_name"))
        result = await browser.load_cookies_from_file(
            str(cookies_path),
            encryption_key=args.get("encryption_key"),
        )

        if result.get("status") != "success":
            raise ToolError(
                "MCP_COOKIE_LOAD_FAILED",
                result.get("message", "Failed to load cookies"),
                result,
            )

        return self._tool_ok_payload({"session_name": session_name, "result": result})

    async def _tool_stealth_set_region(self, args: Dict[str, Any]) -> Dict[str, Any]:
        region = args.get("region")
        if not region:
            raise ToolError("MCP_VALIDATION_ERROR", "region is required")
        session_name, browser = await self._resolve_browser(args.get("session_name"))
        relaunch = bool(args.get("relaunch", False))
        result = await browser.switch_region(str(region), relaunch=relaunch)
        if result.get("status") != "success":
            raise ToolError(
                "MCP_REGION_SWITCH_FAILED",
                result.get("message", "Failed to switch region"),
                result,
            )
        return self._tool_ok_payload({"session_name": session_name, "result": result})

    async def _tool_stealth_scrape(self, args: Dict[str, Any]) -> Dict[str, Any]:
        url = args.get("url")
        if not url:
            raise ToolError("MCP_VALIDATION_ERROR", "url is required")
        if not is_url_safe(str(url)):
            raise ToolError(
                "MCP_SSRF_BLOCKED",
                "URL resolves to a private or blocked address",
            )
        session_name, browser = await self._resolve_browser(args.get("session_name"))
        extract_images = bool(args.get("extract_images", False))
        platform = str(args.get("platform") or "unknown")

        if not getattr(browser, "scraper", None):
            raise ToolError(
                "MCP_SCRAPER_UNAVAILABLE",
                "Scraper is not initialized. Relaunch the session.",
            )

        result = await browser.scraper.scrape_page(
            str(url), extract_images=extract_images, platform=platform
        )
        if getattr(browser, "logger", None):
            browser.logger.log_action(
                "scrape_succeeded", {"url": str(url), "platform": platform}
            )
        return self._tool_ok_payload({"session_name": session_name, "scrape": result})

    async def _tool_stealth_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        session_name, browser = await self._resolve_browser(args.get("session_name"))
        include_debug = bool(args.get("include_debug", False))
        health = await browser.get_health_status()
        payload: Dict[str, Any] = {"session_name": session_name, "health": health}
        if include_debug:
            payload["debug"] = await browser.debug_report(print_report=False)
        return self._tool_ok_payload(payload)

    async def _tool_stealth_tabs_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        session_name, browser = await self._resolve_browser(args.get("session_name"))
        pages = self._get_pages(browser)
        current_page = self._get_current_page(browser)

        tabs = []
        for idx, page in enumerate(pages, start=1):
            tab_id = self._get_tab_id(session_name, page)
            tabs.append(
                {
                    "tab_id": tab_id,
                    "index": idx,
                    "title": await self._page_title(page),
                    "url": self._page_url(page),
                    "is_current": page is current_page,
                }
            )

        payload = self._tool_ok_payload(
            {
                "session_name": session_name,
                "active_tab_id": self._get_tab_id(session_name, current_page)
                if current_page
                else None,
                "tab_count": len(tabs),
                "tabs": tabs,
            }
        )
        return self._guard_observability_payload(payload, "stealth_tabs_list")

    async def _tool_stealth_tab_snapshot(self, args: Dict[str, Any]) -> Dict[str, Any]:
        session_name, browser = await self._resolve_browser(args.get("session_name"))
        full_page = bool(args.get("full_page", False))
        tab_id, page = await self._resolve_page(
            session_name, browser, args.get("tab_id")
        )

        snapshot_path = self._resolve_snapshot_path(session_name, tab_id)
        screenshot_call = page.screenshot(path=str(snapshot_path), full_page=full_page)
        if asyncio.iscoroutine(screenshot_call):
            await screenshot_call

        title = await self._page_title(page)
        url = self._page_url(page)
        payload = self._tool_ok_payload(
            {
                "session_name": session_name,
                "tab_id": tab_id,
                "title": title,
                "url": url,
                "screenshot_path": str(snapshot_path.resolve()),
                "full_page": full_page,
                "dom_summary": self._dom_summary_from_signals(title, url),
            }
        )
        return self._guard_observability_payload(payload, "stealth_tab_snapshot")

    async def _tool_stealth_session_timeline(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        session_name, browser = await self._resolve_browser(args.get("session_name"))
        limit_raw = args.get("limit", self._timeline_default_limit)
        try:
            limit = int(limit_raw)
        except Exception:
            raise ToolError("MCP_VALIDATION_ERROR", "limit must be an integer")
        limit = max(1, min(limit, self._timeline_max_limit))

        cursor = args.get("cursor")
        since_ts = args.get("since_ts")
        replay = (
            browser.get_replay_sequence(limit, cursor=cursor, since_ts=since_ts)
            if hasattr(browser, "get_replay_sequence")
            else {"status": "unsupported", "sequence": []}
        )
        sequence = replay.get("sequence", []) if isinstance(replay, dict) else []
        if not isinstance(sequence, list):
            sequence = []

        # Minimal pagination contract (#381): compute next_cursor/has_more using heuristic (full page => more likely exists)
        next_cursor = None
        has_more = False
        if sequence and len(sequence) == limit:
            has_more = True
            first_evt = sequence[0] if sequence else None
            if isinstance(first_evt, dict):
                next_cursor = first_evt.get("timestamp") or first_evt.get("ts")
        payload = self._tool_ok_payload(
            {
                "session_name": session_name,
                "timeline_status": replay.get("status", "unknown")
                if isinstance(replay, dict)
                else "unknown",
                "count": len(sequence),
                "events": sequence,
                "next_cursor": next_cursor,
                "has_more": has_more,
                "truncated": False,
            }
        )
        return self._guard_observability_payload(payload, "stealth_session_timeline")

    async def _tool_stealth_debug_report(self, args: Dict[str, Any]) -> Dict[str, Any]:
        session_name, browser = await self._resolve_browser(args.get("session_name"))
        print_report = bool(args.get("print_report", False))
        # #381 pagination params (applied to recent_audit inside the debug report)
        limit_raw = args.get("limit")
        limit = None
        if limit_raw is not None:
            try:
                limit = int(limit_raw)
                limit = max(1, min(limit, 100))
            except Exception:
                limit = 15
        cursor = args.get("cursor")
        since_ts = args.get("since_ts")
        debug = await browser.debug_report(
            print_report=print_report, limit=limit, cursor=cursor, since_ts=since_ts
        )
        if debug.get("status") != "success":
            raise ToolError(
                "MCP_DEBUG_REPORT_FAILED",
                debug.get("message", "debug_report failed"),
                debug,
            )
        # Compute consistent pagination fields based on the recent_audit included in report (heuristic)
        report = debug.get("report", {}) if isinstance(debug, dict) else {}
        recent = report.get("recent_audit", []) if isinstance(report, dict) else []
        count = len(recent) if isinstance(recent, list) else 0
        page_limit = limit if limit is not None else 15
        has_more = count == page_limit
        next_cursor = None
        if has_more and recent:
            first = recent[0]
            if isinstance(first, dict):
                next_cursor = first.get("timestamp")
        payload = self._tool_ok_payload(
            {
                "session_name": session_name,
                "debug": debug,
                "count": count,
                "next_cursor": next_cursor,
                "has_more": has_more,
                "truncated": False,
            }
        )
        return self._guard_observability_payload(payload, "stealth_debug_report")

    async def _tool_stealth_get_cdp_endpoint(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        session_name, browser = await self._resolve_browser(args.get("session_name"))
        cdp = await browser.get_cdp_endpoint()
        # small payload; no truncation guard needed, but redact just in case
        payload = self._tool_ok_payload({"session_name": session_name, "cdp": cdp})
        # use guard for uniformity (though typically tiny)
        return self._guard_observability_payload(payload, "stealth_get_cdp_endpoint")

    async def _tool_stealth_attach_over_cdp(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        cdp_url = args.get("cdp_url")
        if not cdp_url or not isinstance(cdp_url, str):
            raise ToolError("MCP_VALIDATION_ERROR", "cdp_url is required")

        # Host safety gate: by default only loopback hosts are allowed.
        # Operator must explicitly set allow_remote=True to attach to a
        # non-loopback endpoint (e.g. Windows host from WSL).
        allow_remote = bool(args.get("allow_remote", False))
        host_to_check = cdp_url.strip()
        if not host_to_check.startswith(("http://", "https://", "ws://", "wss://")):
            host_to_check = f"http://{host_to_check}"
        try:
            parsed = urllib.parse.urlparse(host_to_check)
            host = (parsed.hostname or "").lower()
        except Exception:
            raise ToolError("MCP_VALIDATION_ERROR", "cdp_url is not a valid URL")
        if not host:
            raise ToolError("MCP_VALIDATION_ERROR", "cdp_url has no host component")

        # Two-layer host safety gate (#438, #441):
        #   Layer 1 — is the host loopback? If yes, no allow_remote needed.
        #   Layer 2 — if not loopback, allow_remote=true is required AND
        #             the host must pass is_url_safe (rejects RFC-1918,
        #             link-local IPv4/IPv6, cloud-metadata).
        is_loopback = is_loopback_host(host_to_check)
        if not is_loopback:
            if not allow_remote:
                raise ToolError(
                    "MCP_REMOTE_CDP_BLOCKED",
                    f"cdp_url host '{host}' is not loopback. "
                    "Set allow_remote=true to attach to a remote browser. "
                    "Only attach to endpoints you own and trust.",
                )
            # #448: do not apply full is_url_safe (RFC1918 block) here — WSL/container
            # host IPs are intentionally RFC1918 private ranges; the operator who sets
            # allow_remote is explicitly trusting that endpoint (see warning in payload).
            # Nav/scrape still use strict is_url_safe. Reconciles documented WSL workflow.

            # Even with allow_remote=true, still reject link-local and cloud-metadata
            # (untrusted auto-config / instance metadata ranges). This keeps the spirit
            # of the original hardening while permitting the RFC1918 WSL use-case.
            try:
                norm = host_to_check
                if not any(
                    norm.startswith(p)
                    for p in ("http://", "https://", "ws://", "wss://")
                ):
                    norm = "http://" + norm
                ph = urllib.parse.urlparse(norm).hostname or ""
                if ph:
                    ip = ipaddress.ip_address(ph)
                    if ip in ipaddress.ip_network(
                        "169.254.0.0/16"
                    ) or ip in ipaddress.ip_network("fe80::/10"):
                        raise ToolError(
                            "MCP_REMOTE_CDP_BLOCKED",
                            f"cdp_url host '{host}' is in a blocked auto-config range "
                            "(link-local or cloud-metadata). Even with allow_remote=true, "
                            "these are rejected.",
                        )
            except (ValueError, TypeError, ipaddress.AddressValueError):
                logging.getLogger(__name__).debug(
                    "suppressed exception", exc_info=True
                )  # hostname or parse issue; will surface later or was already validated

        session_name = str(args.get("session_name") or "default")
        if session_name in self._sessions:
            try:
                await self._sessions[session_name].close()
            except Exception:
                logging.getLogger(__name__).debug("suppressed exception", exc_info=True)
            finally:
                self._sessions.pop(session_name, None)

        AgentBrowser = self._get_agent_browser_cls()
        browser = AgentBrowser(
            session_name=session_name,
            anonymous=bool(args.get("anonymous", True)),
            ephemeral=bool(args.get("ephemeral", False)),
        )
        attach_info = await browser.attach_over_cdp(
            cdp_url=cdp_url,
            new_context=bool(args.get("new_context", False)),
            context_index=int(args.get("context_index", 0)),
            apply_stealth=bool(args.get("apply_stealth", True)),
        )

        self._sessions[session_name] = browser
        self._active_session = session_name

        payload = self._tool_ok_payload(
            {
                "session_name": session_name,
                "attached": True,
                "attach": attach_info,
                "loopback": is_loopback,
            }
        )
        return self._guard_observability_payload(payload, "stealth_attach_over_cdp")

    async def _tool_stealth_close(self, args: Dict[str, Any]) -> Dict[str, Any]:
        close_all = bool(args.get("close_all", False))
        if close_all:
            count = len(self._sessions)
            await self._close_all_sessions()
            return self._tool_ok_payload({"closed_all": True, "closed_sessions": count})

        session_name, browser = await self._resolve_browser(args.get("session_name"))
        await browser.close()
        self._sessions.pop(session_name, None)
        self._tab_ids.pop(session_name, None)
        if self._active_session == session_name:
            self._active_session = next(iter(self._sessions.keys()), None)
        return self._tool_ok_payload({"session_name": session_name, "closed": True})

    async def _tool_stealth_capabilities(self, args: Dict[str, Any]) -> Dict[str, Any]:
        _ = args
        return self._tool_ok_payload(
            {
                "server_name": SERVER_NAME,
                "server_title": SERVER_TITLE,
                "server_version": SERVER_VERSION,
                "protocol_version": PROTOCOL_VERSION,
                "tool_count": len(self._tools),
                "tools": [t.name for t in self._tools.values()],
                "active_session": self._active_session,
                "sessions": list(self._sessions.keys()),
            }
        )

    async def _tool_stealth_teach(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from workflows.recorder import WorkflowRecorder

        session_name = str(args.get("session_name") or "")
        workflow_name = str(args.get("workflow_name") or "")
        description = args.get("description")
        capture_seconds_raw = args.get("capture_seconds", 60)
        try:
            capture_seconds = int(capture_seconds_raw)
        except Exception:
            raise ToolError(
                "MCP_VALIDATION_ERROR", "capture_seconds must be an integer"
            )
        capture_seconds = max(1, min(capture_seconds, 600))

        if not session_name:
            raise ToolError("MCP_VALIDATION_ERROR", "session_name is required")
        if not workflow_name:
            raise ToolError("MCP_VALIDATION_ERROR", "workflow_name is required")

        resolved_name, browser = await self._resolve_browser(session_name)

        current_url = ""
        try:
            p = browser.page_getter()
            if p:
                current_url = getattr(p, "url", "") or ""
                try:
                    title_attr = getattr(p, "title")
                    if callable(title_attr):
                        val = title_attr()
                        if asyncio.iscoroutine(val):
                            val = await val
                except Exception:
                    logging.getLogger(__name__).debug(
                        "suppressed exception", exc_info=True
                    )
        except Exception:
            logging.getLogger(__name__).debug("suppressed exception", exc_info=True)

        recorder = WorkflowRecorder()

        if current_url:
            from workflows.schema import Workflow, WorkflowStep, workflow_to_yaml_str

            steps = []
            steps.append(WorkflowStep(type="navigate", params={"url": current_url}))
            steps.append(WorkflowStep(type="wait", params={"ms": 1000}))

            workflow = Workflow(
                name=workflow_name,
                steps=steps,
                description=description
                or f"Recorded workflow for session '{resolved_name}' — URL: {current_url}",
            )

            output_dir = self._workflow_library_root / resolved_name
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{workflow_name}.yaml"
            output_path.write_text(workflow_to_yaml_str(workflow))

            return self._tool_ok_payload(
                {
                    "session_name": resolved_name,
                    "workflow_name": workflow_name,
                    "workflow_path": str(output_path),
                    "step_count": len(steps),
                    "note": "Full passive recording requires M4 bridge integration.",
                }
            )
        else:
            workflow = None
            steps = []

        workflow = recorder.to_workflow(name=workflow_name, description=description)
        steps = workflow.steps

        output_dir = self._workflow_library_root / resolved_name
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{workflow_name}.yaml"
        workflow_yaml = recorder.to_workflow_yaml(
            name=workflow_name, description=description
        )
        output_path.write_text(workflow_yaml)

        return self._tool_ok_payload(
            {
                "session_name": resolved_name,
                "workflow_name": workflow_name,
                "workflow_path": str(output_path),
                "step_count": len(steps),
                "note": "Full passive recording requires M4 bridge integration.",
            }
        )

    async def _tool_stealth_replay(self, args: Dict[str, Any]) -> Dict[str, Any]:
        from workflows.player import WorkflowPlayer
        from workflows.schema import load_workflow

        filename = str(args.get("filename") or "")
        if not filename:
            raise ToolError("MCP_VALIDATION_ERROR", "filename is required")

        if ".." in filename:
            raise ToolError(
                "MCP_SECURITY_PATH_DENIED",
                "Path traversal not allowed in filename.",
                {"filename": filename},
            )

        workflow_path = self._workflow_library_root / filename
        resolved_workflow_path = workflow_path.resolve()
        resolved_root = self._workflow_library_root.resolve()
        if (
            resolved_root not in resolved_workflow_path.parents
            and resolved_workflow_path != resolved_root
        ):
            raise ToolError(
                "MCP_SECURITY_PATH_DENIED",
                "Workflow path resolved outside allowed library root.",
                {"filename": filename},
            )

        if not resolved_workflow_path.exists():
            raise ToolError(
                "MCP_WORKFLOW_NOT_FOUND",
                f"Workflow file not found: {filename}",
                {"filename": filename},
            )

        variables = dict(args.get("variables") or {})
        session_name = args.get("session_name")

        workflow = load_workflow(str(resolved_workflow_path))

        # Security gate: enforce policy (step-type / domain allow-lists) on every step
        # before executing any of them. Default policy is fail-open; operator policy
        # YAML makes this deny blocked step types / domains and require approval.
        for idx, step in enumerate(workflow.steps):
            decision = self._policy_engine.check_step(
                step.type, str(step.params.get("url", ""))
            )
            if not decision["allowed"]:
                raise ToolError(
                    "MCP_POLICY_DENIED",
                    f"Workflow step {idx} ('{step.type}') denied by policy: {decision['reason']}",
                    {
                        "step_index": idx,
                        "step_type": step.type,
                        "reason": decision["reason"],
                    },
                )
            if decision.get("approval_required"):
                appr = self._approval_gate.check_sensitive(
                    step.type, step.params, str(session_name or "")
                )
                if appr.decision != ApprovalDecision.ALLOWED:
                    raise ToolError(
                        "MCP_APPROVAL_REQUIRED",
                        f"Workflow step {idx} ('{step.type}') requires approval: {appr.reason}"
                        " — approve via resolve_pending(request_id) or set STEALTH_APPROVAL_MODE=permissive",
                        {
                            "step_index": idx,
                            "step_type": step.type,
                            "request_id": appr.request_id,
                        },
                    )

        if session_name:
            resolved_name, browser = await self._resolve_browser(session_name)
        else:
            resolved_name, browser = await self._resolve_browser(None)

        player = WorkflowPlayer(browser)
        result = await player.execute(
            workflow, runtime_vars=variables if variables else None
        )

        return self._tool_ok_payload(
            {
                "session_name": resolved_name,
                "filename": filename,
                "success": result.success,
                "steps_executed": result.steps_executed,
                "total_steps": result.total_steps,
                "failed_step": result.failed_step,
                "failed_step_type": result.failed_step_type,
                "error_message": result.error_message,
                "execution_time": result.execution_time,
                "summary": result.summary,
            }
        )

    async def _tool_stealth_workflow_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        platform = args.get("platform")
        pattern = args.get("pattern")

        search_root = self._workflow_library_root
        if platform:
            platform = str(platform)
            search_root = self._workflow_library_root / platform
            if not search_root.exists():
                # fall back to bundled in wheel
                if self._bundled_workflow_root:
                    bundled_p = (
                        self._bundled_workflow_root / platform
                        if hasattr(self._bundled_workflow_root, "__truediv__")
                        else None
                    )
                    if bundled_p and bundled_p.exists():
                        search_root = bundled_p  # type: ignore
                if (
                    not getattr(search_root, "exists", lambda: False)()
                    or not search_root.exists()
                ):
                    return self._tool_ok_payload({"workflows": []})

        workflows = []
        roots_for_rel = [self._workflow_library_root]
        if self._bundled_workflow_root:
            roots_for_rel.append(self._bundled_workflow_root)
        for yaml_file in sorted(search_root.rglob("*.yaml")):
            # best effort relative for display (prefer user root)
            rel_root = self._workflow_library_root
            try:
                relative_path = yaml_file.relative_to(rel_root)
            except Exception:
                relative_path = Path(yaml_file.name)
            filename_str = relative_path.as_posix()

            if pattern and not fnmatch.fnmatch(filename_str, pattern):
                continue

            parts = relative_path.parts
            platform_name = parts[0] if len(parts) > 1 else "root"

            try:
                stat = yaml_file.stat()
                size = stat.st_size
                modified_at = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)
                )
            except Exception:
                size = 0
                modified_at = ""

            workflows.append(
                {
                    "name": yaml_file.stem,
                    "path": filename_str,
                    "platform": platform_name,
                    "size": size,
                    "modified_at": modified_at,
                }
            )

        return self._tool_ok_payload({"workflows": workflows})

    async def _tool_stealth_workflow_delete(
        self, args: Dict[str, Any]
    ) -> Dict[str, Any]:
        filename = str(args.get("filename") or "")
        confirm = args.get("confirm", False)

        if not filename:
            raise ToolError("MCP_VALIDATION_ERROR", "filename is required")

        if not confirm:
            raise ToolError(
                "MCP_VALIDATION_ERROR",
                "Confirmation required. Set confirm=True to delete.",
                {"filename": filename},
            )

        if ".." in filename:
            raise ToolError(
                "MCP_SECURITY_PATH_DENIED",
                "Path traversal not allowed in filename.",
                {"filename": filename},
            )

        workflow_path = self._workflow_library_root / filename
        resolved_workflow_path = workflow_path.resolve()
        resolved_root = self._workflow_library_root.resolve()
        if (
            resolved_root not in resolved_workflow_path.parents
            and resolved_workflow_path != resolved_root
        ):
            raise ToolError(
                "MCP_SECURITY_PATH_DENIED",
                "Resolved workflow path is outside the allowed library root.",
                {"filename": filename},
            )

        if not resolved_workflow_path.exists():
            raise ToolError(
                "MCP_WORKFLOW_NOT_FOUND",
                f"Workflow file not found: {filename}",
                {"filename": filename},
            )

        resolved_workflow_path.unlink()
        return self._tool_ok_payload(
            {
                "deleted": True,
                "filename": filename,
            }
        )


# Placed after the class body (not with the imports above) so this module can be
# imported before or after production.mcp_server without a circular-import
# NameError: by the time this line runs, _MCPToolHandlers already exists in this
# module's namespace, so production.mcp_server (which imports _MCPToolHandlers
# from here) can always complete first if it's the one triggering this load.
from production.mcp_server import (  # noqa: E402
    ToolError,
    SERVER_NAME,
    SERVER_TITLE,
    SERVER_VERSION,
    PROTOCOL_VERSION,
    is_url_safe,
    is_loopback_host,
)
