import json
from pathlib import Path

import pytest

from production.mcp_server import StealthMCPServer, main


class _FakePage:
    def __init__(self):
        self.url = "about:blank"
        self._title = "Fake Page"

    async def title(self):
        return self._title

    async def screenshot(self, path: str, full_page: bool = False):
        _ = full_page
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(b"fake-png-bytes")
        return b"fake-png-bytes"


class _FakeScraper:
    async def scrape_page(self, url: str, extract_images: bool = False, platform: str = "unknown"):
        return {
            "url": url,
            "extract_images": extract_images,
            "platform": platform,
            "content": {"title": "fake"},
        }


class _FakeBrowser:
    def __init__(
        self,
        session_name=None,
        anonymous=False,
        ephemeral=False,
        light_mode=False,
        use_pooled_context=False,
    ):
        self.session_name = session_name
        self.anonymous = anonymous
        self.ephemeral = ephemeral
        self.light_mode = light_mode
        self.use_pooled_context = use_pooled_context
        self.current_preset = None
        self.current_region = "global"
        self.scraper = _FakeScraper()
        self._page = _FakePage()
        self._pages = [self._page]
        self._closed = False

    async def launch(self, headless=True, debug=False, debug_cdp=False, preset=None, region=None):
        self.current_preset = preset
        self.current_region = region or "global"
        self.debug = debug
        self.debug_cdp = debug_cdp
        self.headless = headless

    def page_getter(self):
        return self._page

    async def safe_goto(self, url: str, warm_up=True, platform="unknown", rate_limit=True, domain=None, account=None):
        _ = (warm_up, platform, rate_limit, domain, account)
        self._page.url = url
        self._page._title = f"Visited {url}"
        return True

    async def load_cookies_from_file(self, cookies_path: str, encryption_key=None):
        _ = encryption_key
        return {"status": "success", "loaded": 1, "path": cookies_path}

    async def switch_region(self, new_region: str, relaunch: bool = False):
        self.current_region = new_region
        _ = relaunch
        return {"status": "success", "old_region": "global", "new_region": new_region}

    async def get_health_status(self):
        return {"status": "ok", "launched": True, "region": self.current_region}

    async def debug_report(self, print_report: bool = False):
        _ = print_report
        return {"status": "success", "report": {"ok": True}}

    async def get_cdp_endpoint(self):
        if not getattr(self, "debug_cdp", False):
            return {
                "status": "disabled",
                "message": "CDP attach is disabled for this session. Relaunch with debug_cdp=True to enable (binds to localhost only; see security notes).",
            }
        return {
            "status": "enabled",
            "ws_endpoint": "ws://127.0.0.1:9222/devtools/browser/fake-uuid-for-test",
            "port": 9222,
            "warning": "SECURITY: localhost only.",
        }

    def get_replay_sequence(self, limit: int = 30):
        return {
            "status": "ok",
            "sequence": [{"event": "navigate", "ts": 1}, {"event": "click", "ts": 2}][:limit],
        }

    def get_pages(self):
        return list(self._pages)

    async def close(self):
        self._closed = True


class _TrackingReplayBrowser(_FakeBrowser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.last_limit = None

    def get_replay_sequence(self, limit: int = 30):
        self.last_limit = limit
        return {
            "status": "ok",
            "sequence": [{"event": f"event-{i}", "ts": i} for i in range(limit)],
        }


class _LargeDebugBrowser(_FakeBrowser):
    async def debug_report(self, print_report: bool = False):
        _ = print_report
        return {
            "status": "success",
            "report": {
                "ok": True,
                "blob": "x" * 12000,
            },
        }


def _tool_structured_content(resp: dict) -> dict:
    return resp["result"]["structuredContent"]


@pytest.mark.asyncio
async def test_tools_manifest_contains_required_runtime_tools():
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)
    names = {t["name"] for t in server.list_tools()["tools"]}
    required = {
        "stealth_launch",
        "stealth_navigate",
        "stealth_load_cookies",
        "stealth_set_region",
        "stealth_scrape",
        "stealth_status",
        "stealth_tabs_list",
        "stealth_tab_snapshot",
        "stealth_session_timeline",
        "stealth_debug_report",
        "stealth_get_cdp_endpoint",
        "stealth_close",
        "stealth_capabilities",
    }
    assert required.issubset(names)


@pytest.mark.asyncio
async def test_initialize_and_tools_list_jsonrpc_shape():
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)
    init_resp = await server.handle_jsonrpc(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}}
    )
    assert init_resp["result"]["protocolVersion"] == "2025-03-26"
    assert "tools" in init_resp["result"]["capabilities"]

    list_resp = await server.handle_jsonrpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert "tools" in list_resp["result"]
    assert len(list_resp["result"]["tools"]) >= 8


@pytest.mark.asyncio
async def test_launch_then_navigate_tool_flow():
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)

    launch_resp = await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {"name": "stealth_launch", "arguments": {"session_name": "demo", "headless": True, "region": "us"}},
        }
    )
    launch_payload = _tool_structured_content(launch_resp)
    assert launch_payload["status"] == "success"
    assert launch_payload["session_name"] == "demo"

    nav_resp = await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {"name": "stealth_navigate", "arguments": {"session_name": "demo", "url": "https://example.com"}},
        }
    )
    nav_payload = _tool_structured_content(nav_resp)
    assert nav_payload["status"] == "success"
    assert nav_payload["navigated"] is True
    assert nav_payload["current_url"] == "https://example.com"


@pytest.mark.asyncio
async def test_cookie_load_blocks_path_traversal_by_security_policy():
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)
    await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 21,
            "method": "tools/call",
            "params": {"name": "stealth_launch", "arguments": {"session_name": "demo"}},
        }
    )

    cookies_resp = await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 22,
            "method": "tools/call",
            "params": {"name": "stealth_load_cookies", "arguments": {"session_name": "demo", "cookies_path": "../secret.json"}},
        }
    )
    payload = _tool_structured_content(cookies_resp)
    assert payload["status"] == "error"
    assert payload["error_code"] == "MCP_SECURITY_PATH_DENIED"
    assert cookies_resp["result"].get("isError") is True


def test_list_tools_cli_flag(capsys):
    rc = main(["--list-tools"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    names = {t["name"] for t in data["tools"]}
    assert "stealth_launch" in names
    assert "stealth_status" in names
    assert "stealth_tabs_list" in names


@pytest.mark.asyncio
async def test_observability_tabs_snapshot_timeline_and_debug_tools():
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)
    await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 31,
            "method": "tools/call",
            "params": {"name": "stealth_launch", "arguments": {"session_name": "obs"}},
        }
    )
    await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 32,
            "method": "tools/call",
            "params": {"name": "stealth_navigate", "arguments": {"session_name": "obs", "url": "https://example.com"}},
        }
    )

    tabs_resp = await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 33,
            "method": "tools/call",
            "params": {"name": "stealth_tabs_list", "arguments": {"session_name": "obs"}},
        }
    )
    tabs_payload = _tool_structured_content(tabs_resp)
    assert tabs_payload["status"] == "success"
    assert tabs_payload["tab_count"] >= 1
    tab_id = tabs_payload["tabs"][0]["tab_id"]

    snap_resp = await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 34,
            "method": "tools/call",
            "params": {"name": "stealth_tab_snapshot", "arguments": {"session_name": "obs", "tab_id": tab_id}},
        }
    )
    snap_payload = _tool_structured_content(snap_resp)
    assert snap_payload["status"] == "success"
    assert Path(snap_payload["screenshot_path"]).exists()
    assert "dom_summary" in snap_payload

    timeline_resp = await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 35,
            "method": "tools/call",
            "params": {"name": "stealth_session_timeline", "arguments": {"session_name": "obs", "limit": 2}},
        }
    )
    timeline_payload = _tool_structured_content(timeline_resp)
    assert timeline_payload["status"] == "success"
    assert timeline_payload["count"] == 2

    debug_resp = await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 36,
            "method": "tools/call",
            "params": {"name": "stealth_debug_report", "arguments": {"session_name": "obs"}},
        }
    )
    debug_payload = _tool_structured_content(debug_resp)
    assert debug_payload["status"] == "success"
    assert debug_payload["debug"]["status"] == "success"


@pytest.mark.asyncio
async def test_timeline_limit_uses_env_default_and_max(monkeypatch):
    monkeypatch.setenv("STEALTH_MCP_TIMELINE_DEFAULT_LIMIT", "2")
    monkeypatch.setenv("STEALTH_MCP_TIMELINE_MAX_LIMIT", "3")
    server = StealthMCPServer(agent_browser_cls=_TrackingReplayBrowser)
    await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 41,
            "method": "tools/call",
            "params": {"name": "stealth_launch", "arguments": {"session_name": "obs"}},
        }
    )

    default_resp = await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 42,
            "method": "tools/call",
            "params": {"name": "stealth_session_timeline", "arguments": {"session_name": "obs"}},
        }
    )
    default_payload = _tool_structured_content(default_resp)
    assert default_payload["status"] == "success"
    assert default_payload["count"] == 2
    assert server._sessions["obs"].last_limit == 2

    clamped_resp = await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 43,
            "method": "tools/call",
            "params": {"name": "stealth_session_timeline", "arguments": {"session_name": "obs", "limit": 999}},
        }
    )
    clamped_payload = _tool_structured_content(clamped_resp)
    assert clamped_payload["status"] == "success"
    assert clamped_payload["count"] == 3
    assert server._sessions["obs"].last_limit == 3


@pytest.mark.asyncio
async def test_observability_payload_is_truncated_when_debug_report_is_large(monkeypatch):
    monkeypatch.setenv("STEALTH_MCP_OBSERVABILITY_MAX_CHARS", "2000")
    server = StealthMCPServer(agent_browser_cls=_LargeDebugBrowser)
    await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 51,
            "method": "tools/call",
            "params": {"name": "stealth_launch", "arguments": {"session_name": "obs"}},
        }
    )

    debug_resp = await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 52,
            "method": "tools/call",
            "params": {"name": "stealth_debug_report", "arguments": {"session_name": "obs"}},
        }
    )
    payload = _tool_structured_content(debug_resp)
    assert payload["status"] == "success"
    assert payload["truncated"] is True
    assert payload["details"]["endpoint"] == "stealth_debug_report"
    assert payload["details"]["max_chars"] == 2000
    assert payload["details"]["original_chars"] > payload["details"]["max_chars"]
    assert len(payload["preview"]) == 2000
    assert "debug" not in payload


@pytest.mark.asyncio
async def test_observability_payload_is_truncated_for_large_timeline(monkeypatch):
    monkeypatch.setenv("STEALTH_MCP_OBSERVABILITY_MAX_CHARS", "2000")
    monkeypatch.setenv("STEALTH_MCP_TIMELINE_MAX_LIMIT", "1000")
    server = StealthMCPServer(agent_browser_cls=_TrackingReplayBrowser)
    await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 53,
            "method": "tools/call",
            "params": {"name": "stealth_launch", "arguments": {"session_name": "obs"}},
        }
    )

    timeline_resp = await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 54,
            "method": "tools/call",
            "params": {"name": "stealth_session_timeline", "arguments": {"session_name": "obs", "limit": 400}},
        }
    )
    payload = _tool_structured_content(timeline_resp)
    assert payload["status"] == "success"
    assert payload["truncated"] is True
    assert payload["details"]["endpoint"] == "stealth_session_timeline"
    assert payload["details"]["original_chars"] > payload["details"]["max_chars"]
    assert len(payload["preview"]) == 2000
    assert "events" not in payload


@pytest.mark.asyncio
async def test_snapshot_retention_prunes_old_files(monkeypatch, tmp_path):
    monkeypatch.setenv("STEALTH_MCP_SNAPSHOT_DIR", str(tmp_path / "snapshots"))
    monkeypatch.setenv("STEALTH_MCP_SNAPSHOT_MAX_PER_SESSION", "3")

    tick = {"value": 1710000000.0}

    def _fake_time():
        tick["value"] += 0.01
        return tick["value"]

    monkeypatch.setattr("production.mcp_server.time.time", _fake_time)

    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)
    await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 61,
            "method": "tools/call",
            "params": {"name": "stealth_launch", "arguments": {"session_name": "obs"}},
        }
    )

    tabs_resp = await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 62,
            "method": "tools/call",
            "params": {"name": "stealth_tabs_list", "arguments": {"session_name": "obs"}},
        }
    )
    tab_id = _tool_structured_content(tabs_resp)["tabs"][0]["tab_id"]

    for idx in range(6):
        snap_resp = await server.handle_jsonrpc(
            {
                "jsonrpc": "2.0",
                "id": 63 + idx,
                "method": "tools/call",
                "params": {"name": "stealth_tab_snapshot", "arguments": {"session_name": "obs", "tab_id": tab_id}},
            }
        )
        snap_payload = _tool_structured_content(snap_resp)
        assert snap_payload["status"] == "success"

    snapshot_dir = (tmp_path / "snapshots") / "obs"
    pngs = sorted(snapshot_dir.glob("*.png"))
    assert len(pngs) == 3


@pytest.mark.asyncio
async def test_stealth_get_cdp_endpoint_disabled_by_default_and_enabled_when_flagged():
    """#377: opt-in CDP endpoint tool. Disabled returns clear status; enabled returns ws + warnings."""
    # Default (disabled)
    server = StealthMCPServer(agent_browser_cls=_FakeBrowser)
    await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 71,
            "method": "tools/call",
            "params": {"name": "stealth_launch", "arguments": {"session_name": "cdp-test"}},
        }
    )
    resp_disabled = await server.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 72,
            "method": "tools/call",
            "params": {"name": "stealth_get_cdp_endpoint", "arguments": {"session_name": "cdp-test"}},
        }
    )
    payload_d = _tool_structured_content(resp_disabled)
    assert payload_d["status"] == "success"
    cdp_d = payload_d["cdp"]
    assert cdp_d["status"] == "disabled"
    assert "disabled" in cdp_d.get("message", "").lower()
    assert "localhost" in cdp_d.get("message", "").lower() or "127.0.0.1" in str(cdp_d)

    # Now launch with flag
    server2 = StealthMCPServer(agent_browser_cls=_FakeBrowser)
    await server2.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 73,
            "method": "tools/call",
            "params": {"name": "stealth_launch", "arguments": {"session_name": "cdp-enabled", "debug_cdp": True}},
        }
    )
    resp_enabled = await server2.handle_jsonrpc(
        {
            "jsonrpc": "2.0",
            "id": 74,
            "method": "tools/call",
            "params": {"name": "stealth_get_cdp_endpoint", "arguments": {"session_name": "cdp-enabled"}},
        }
    )
    payload_e = _tool_structured_content(resp_enabled)
    assert payload_e["status"] == "success"
    cdp_e = payload_e["cdp"]
    assert cdp_e["status"] == "enabled"
    assert "ws_endpoint" in cdp_e
    assert cdp_e["ws_endpoint"].startswith("ws://127.0.0.1")
    assert "warning" in cdp_e and "localhost" in cdp_e["warning"].lower()
