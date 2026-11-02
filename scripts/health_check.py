#!/usr/bin/env python3
"""Health check script for the Stealth Browser + MCP Server + Bridge.

Run: python scripts/health_check.py

Returns structured JSON with status of:
  - MCP server availability
  - Workflow library integrity
  - Remote Browser Bridge (RBB) status
  - Disk space
  - Memory usage
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def _get_project_root() -> Path:
    return Path(__file__).resolve().parent.parent


sys.path.insert(0, str(_get_project_root()))


def check_mcp_server() -> Dict[str, Any]:
    """Verify the MCP server module is importable and functional."""
    result: Dict[str, Any] = {"running": False, "details": ""}
    try:
        from production.mcp_server import StealthMCPServer

        server = StealthMCPServer()
        tools = list(server._tools) if hasattr(server, "_tools") else []
        result["running"] = True
        result["details"] = f"MCP stdio server available ({len(tools)} tools)"
        result["tool_count"] = len(tools)
    except ImportError as e:
        result["details"] = f"Import failed: {e}"
    except Exception as e:
        result["details"] = f"Server init failed: {e}"
    return result


def check_workflow_library() -> Dict[str, Any]:
    """Validate all workflow YAML files in the library."""
    result: Dict[str, Any] = {
        "accessible": False,
        "workflow_count": 0,
        "valid": 0,
        "invalid": 0,
        "errors": [],
    }

    library_root = _get_project_root() / "workflows" / "library"
    if not library_root.exists():
        result["errors"].append(f"Library root missing: {library_root}")
        return result

    try:
        from workflows.schema import load_workflow, validate_workflow
    except ImportError as e:
        result["errors"].append(f"Schema import failed: {e}")
        return result

    result["accessible"] = True
    yaml_files = sorted(library_root.rglob("*.yaml"))
    result["workflow_count"] = len(yaml_files)

    for yf in yaml_files:
        try:
            wf = load_workflow(str(yf))
            vr = validate_workflow(wf)
            if vr.valid:
                result["valid"] += 1
            else:
                result["invalid"] += 1
                rel = yf.relative_to(_get_project_root())
                result["errors"].append(f"{rel}: {vr.errors}")
        except Exception as e:
            result["invalid"] += 1
            rel = yf.relative_to(_get_project_root())
            result["errors"].append(f"{rel}: {e}")

    return result


def check_bridge() -> Dict[str, Any]:
    """Check Remote Browser Bridge configuration."""
    result: Dict[str, Any] = {
        "status": "unknown",
        "port": None,
        "cloudflared_installed": False,
        "service_configured": False,
    }

    port = os.environ.get("STEALTH_RBB_PORT", "9222")
    try:
        result["port"] = int(port)
    except (TypeError, ValueError):
        result["port"] = None
        result["status"] = "invalid_port"
        result["error"] = f"Invalid STEALTH_RBB_PORT: {port!r} is not a number"
        return result

    import shutil

    result["cloudflared_installed"] = shutil.which("cloudflared") is not None

    if sys.platform == "linux":
        import subprocess

        try:
            cp = subprocess.run(
                ["systemctl", "--user", "is-active", "stealth-rbb"],
                capture_output=True,
                timeout=5,
            )
            stdout = cp.stdout
            if isinstance(stdout, bytes):
                stdout = stdout.decode(errors="replace")
            # Configured/active only when systemctl actually says so:
            # an inactive, missing, or failed service does not count.
            if cp.returncode == 0 and (stdout or "").strip() == "active":
                result["service_configured"] = True
                result["status"] = "running"
            else:
                result["status"] = "not_configured"
        except Exception:
            pass

        system_service = Path("/etc/systemd/system/stealth-rbb.service")
        user_service = (
            Path.home() / ".config" / "systemd" / "user" / "stealth-rbb.service"
        )
        if system_service.exists() or user_service.exists():
            result["service_configured"] = True
            if result["status"] != "running":
                result["status"] = "service_found"

        if result["service_configured"] and result["status"] != "running":
            try:
                cp = subprocess.run(
                    ["systemctl", "--no-pager", "--user", "status", "stealth-rbb"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if "active (running)" in cp.stdout or "active (running)" in cp.stderr:
                    result["status"] = "running"
                else:
                    result["status"] = "stopped"
            except Exception:
                result["status"] = "check_failed"

    elif sys.platform == "win32":
        bridge_dir = (
            Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "StealthRBB"
        )
        if bridge_dir.exists():
            result["service_configured"] = True
            result["status"] = (
                "installed" if result["service_configured"] else "not_configured"
            )

    return result


def check_disk() -> Dict[str, Any]:
    """Check disk space on the project root volume."""
    import shutil

    try:
        usage = shutil.disk_usage(_get_project_root())
        total_gb = round(usage.total / (1024**3), 2)
        free_gb = round(usage.free / (1024**3), 2)
        used_percent = round((usage.used / usage.total) * 100, 1)
        return {
            "total_gb": total_gb,
            "free_gb": free_gb,
            "used_percent": used_percent,
            "warning": free_gb < 1.0,
        }
    except Exception as e:
        return {"error": str(e)}


def check_memory() -> Dict[str, Any]:
    """Check available system memory."""
    try:
        import sys

        if sys.platform == "linux":
            with open("/proc/meminfo") as f:
                lines = f.read()

            def _parse_kb(label: str) -> float:
                for line in lines.splitlines():
                    if line.startswith(label + ":"):
                        return float(line.split()[1]) / (1024 * 1024)
                return 0.0

            total = round(_parse_kb("MemTotal"), 2)
            available = round(_parse_kb("MemAvailable"), 2)
            used_percent = (
                round(((total - available) / total) * 100, 1) if total > 0 else 0.0
            )
            return {
                "total_gb": total,
                "available_gb": available,
                "used_percent": used_percent,
                "warning": available < 0.5,
            }
        else:
            import psutil

            vm = psutil.virtual_memory()
            total_gb = round(vm.total / (1024**3), 2)
            available_gb = round(vm.available / (1024**3), 2)
            used_percent = vm.percent
            return {
                "total_gb": total_gb,
                "available_gb": available_gb,
                "used_percent": used_percent,
                "warning": available_gb < 0.5,
            }
    except ImportError:
        return {"error": "psutil not installed; memory check skipped"}
    except Exception as e:
        return {"error": str(e)}


def _run_check(fn: Any) -> Dict[str, Any]:
    """Run one check; an exception becomes an error result, not a crash."""
    try:
        result = fn()
    except Exception as e:
        return {"error": str(e)}
    if isinstance(result, dict):
        return result
    return {"error": f"unexpected result: {result!r}"}


def main() -> None:
    checks: Dict[str, Any] = {
        "mcp_server": _run_check(check_mcp_server),
        "workflow_library": _run_check(check_workflow_library),
        "bridge": _run_check(check_bridge),
        "disk": _run_check(check_disk),
        "memory": _run_check(check_memory),
    }

    issues: List[str] = []
    # A failed check ({"error": ...}) is unhealthy, never silently healthy.
    for name, check in checks.items():
        if isinstance(check, dict) and check.get("error"):
            issues.append(f"{name} check failed: {check['error']}")
    if not checks["mcp_server"].get("running"):
        issues.append("MCP server not available")
    if not checks["workflow_library"].get("accessible"):
        issues.append("Workflow library not accessible")
    if checks["workflow_library"].get("invalid", 0) > 0:
        issues.append(f"{checks['workflow_library']['invalid']} invalid workflow(s)")
    bridge = checks["bridge"]
    if not bridge.get("error"):
        if not bridge.get("service_configured"):
            issues.append("Remote Browser Bridge not configured")
        elif bridge.get("status") in ("stopped", "check_failed"):
            issues.append(f"Remote Browser Bridge not running (status: {bridge.get('status')})")
    if checks["disk"].get("warning"):
        issues.append("Disk space low")
    if checks["memory"].get("warning"):
        issues.append("Memory low")

    overall = "healthy" if not issues else "degraded"

    report = {
        "status": overall,
        "issues": issues,
        "checks": checks,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    print(json.dumps(report, indent=2))
    sys.exit(0 if overall == "healthy" else 1)


if __name__ == "__main__":
    main()
