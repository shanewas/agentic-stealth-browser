#!/usr/bin/env python3
"""
Production CLI entrypoint for Agentic Stealth Browser (addresses #233, #281, #173).

High-value DX: `stealth-browser health` and `status` commands expose:
  - proxy usage / current config
  - account state (healthy/degraded)
  - block rate (from recovery + metrics)
  - TLS/preset/region, cookies, recovery stats, current URL after launch

#173: Added `stealth-browser scrape <url>` for one-liner stealth scraping from terminal.

Usage examples:
  python -m production.cli health --preset linkedin_2026 --region us --headless
  stealth-browser status
  stealth-browser scrape https://example.com --extract text
  stealth-browser scrape https://example.com --extract html --platform amazon
  stealth-browser health --no-launch   # future: inspect persisted state

Also supports smoke, metrics, debug-report for operators.
"""

import argparse
import asyncio
import json
import sys
from typing import Any, Dict
from urllib.parse import urlparse

from audit.logger import AuditLogger
from core.agent_browser import AgentBrowser
from stealth.presets import list_presets


def _redact_for_output(obj: Any) -> Any:
    """Redact sensitive data before printing to stdout/stderr."""
    if isinstance(obj, dict):
        return AuditLogger._redact_sensitive(obj)
    if isinstance(obj, str):
        try:
            parsed = json.loads(obj)
            if isinstance(parsed, dict):
                redacted = AuditLogger._redact_sensitive(parsed)
                return json.dumps(redacted)
        except (json.JSONDecodeError, TypeError):
            pass
    return obj


def _print_json(obj: Dict[str, Any], pretty: bool = True) -> None:
    safe = _redact_for_output(obj)
    if pretty:
        print(json.dumps(safe, indent=2, default=str))
    else:
        print(json.dumps(safe, default=str))


async def _cmd_health(args: argparse.Namespace) -> int:
    """Launch (optionally) and print rich health/status snapshot. Core of #281."""
    print("[stealth-browser] Health/Status command (P2/P3 DX observability)")
    print(
        f"  preset={args.preset} region={args.region} headless={args.headless} debug={args.debug}"
    )

    try:
        browser = AgentBrowser(
            session_name=args.session,
            anonymous=not bool(args.session),
            ephemeral=True,  # P2 throwaway for CLI health probe
        )
        await browser.launch(
            headless=args.headless,
            debug=args.debug,
            preset=args.preset,
            region=args.region,
        )

        health = await browser.get_health_status()
        safe_health = (
            AuditLogger._redact_sensitive(health)
            if isinstance(health, dict)
            else health
        )
        _print_json(safe_health)

        # Also surface proxy/account/block highlights for quick human reading
        print("\n=== QUICK OBSERVABILITY SUMMARY ===")
        print(f"  Launched: {safe_health.get('launched')}")
        print(f"  Preset: {safe_health.get('preset')}")
        print(
            f"  Region / TLS: {safe_health.get('region')} / {safe_health.get('tls_profile', {}).get('name')}"
        )
        print(f"  Proxy: {safe_health.get('proxy')}")
        print(f"  Account State: {safe_health.get('account_state')}")
        print(f"  Block Rate: {safe_health.get('block_rate_pct')}%")
        print(f"  Cookies: {safe_health.get('cookies', {}).get('status')}")
        print(
            f"  Recovery: {safe_health.get('recovery', {}).get('last_block', 'none')}"
        )
        print("====================================\n")

        if args.debug:
            await browser.debug_report(print_report=True)
            print("Debug report included above.")

        await browser.close()
        return 0 if health.get("status") == "ok" else 1

    except Exception as exc:
        print(f"HEALTH ERROR: {exc}", file=sys.stderr)
        return 2


async def _cmd_status(args: argparse.Namespace) -> int:
    """Alias / lighter status (enhanced stealth_status behavior)."""
    # Re-use health but with less noise
    rc = await _cmd_health(args)
    return rc


async def _cmd_list_presets(args: argparse.Namespace) -> int:
    presets = list_presets()
    print("Available 2026 presets:")
    for p in presets:
        print(f"  - {p}")
    print("Use with: stealth-browser health --preset linkedin_2026")
    return 0


async def _cmd_replay(args: argparse.Namespace) -> int:
    """#253 replay from audit logs (lightweight)."""
    log = AuditLogger(args.session or "default")
    seq = log.replay_sequence(getattr(args, "limit", 15))
    safe_seq = AuditLogger._redact_sensitive(
        {"session": log.session_name, "replay_sequence": seq, "count": len(seq)}
    )
    _print_json(safe_seq)
    return 0


async def _cmd_scrape(args: argparse.Namespace) -> int:
    """#173: One-liner stealth scrape from the terminal."""
    url = args.url
    extract = args.extract
    platform = args.platform or "unknown"
    preset = args.preset
    region = args.region or "global"

    print(f"[stealth-browser] Scraping: {url} (extract={extract}, platform={platform})")

    try:
        async with AgentBrowser(
            session_name=f"cli-scrape-{urlparse(url).netloc}",
            anonymous=True,
            ephemeral=True,
        ) as browser:
            await browser.launch(
                headless=True,
                preset=preset,
                region=region,
            )

            success = await browser.safe_goto(url, platform=platform)
            if not success:
                print(f"ERROR: Failed to navigate to {url}", file=sys.stderr)
                return 2

            page = browser.page
            if extract == "text":
                content = await page.inner_text("body")
            elif extract == "html":
                content = await page.content()
            elif extract == "title":
                content = await page.title()
            else:
                content = await page.inner_text("body")

            # Output content
            if args.max_length and len(content) > args.max_length:
                content = content[: args.max_length] + "\n... [truncated]"

            print(content)

            # Print summary to stderr so it doesn't mix with content
            health = await browser.get_health_status()
            print(
                f"\n[stealth-browser] Scrape complete. Block rate: {health.get('block_rate_pct', 0)}%",
                file=sys.stderr,
            )

        return 0

    except Exception as exc:
        print(f"SCRAPE ERROR: {exc}", file=sys.stderr)
        return 2


async def _cmd_dashboard(args: argparse.Namespace) -> int:
    """Start the Hermes single-user browser dashboard."""
    from production.hermes_dashboard import run_dashboard

    run_dashboard(host=args.host, port=args.port, password=args.password)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="stealth-browser",
        description="Agentic Stealth Browser Production CLI - DX & Observability (#281)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # health (primary high-value DX command)
    h = subparsers.add_parser(
        "health",
        help="Rich health snapshot: proxy usage, block rate, account state, TLS/preset",
    )
    h.add_argument(
        "--preset",
        default=None,
        choices=[None] + list_presets(),
        help="Apply 2026 platform preset",
    )
    h.add_argument(
        "--region", default="global", help="TLS region (us/eu/japan/korea/global)"
    )
    h.add_argument("--session", default=None, help="Named session (persistent cookies)")
    h.add_argument(
        "--headless", action="store_true", default=True, help="Run headless (default)"
    )
    h.add_argument(
        "--no-headless",
        dest="headless",
        action="store_false",
        help="Run headed for visual debug",
    )
    h.add_argument(
        "--debug", action="store_true", help="Enable debug mode + fingerprint dump"
    )
    h.add_argument("--json", action="store_true", help="Raw JSON only output")
    h.set_defaults(func=_cmd_health)

    # status (alias)
    s = subparsers.add_parser("status", help="Current browser status (alias to health)")
    s.add_argument("--preset", default=None, choices=[None] + list_presets())
    s.add_argument("--region", default="global")
    s.add_argument("--debug", action="store_true")
    s.set_defaults(func=_cmd_status)

    # list-presets
    lp = subparsers.add_parser(
        "list-presets", help="List available platform presets (#288)"
    )
    lp.set_defaults(func=_cmd_list_presets)

    rp = subparsers.add_parser(
        "replay", help="Replay/inspect actions from audit logs (#253 light)"
    )
    rp.add_argument("--session", default="default")
    rp.add_argument("--limit", type=int, default=15)
    rp.set_defaults(func=_cmd_replay)

    # future: metrics, smoke, debug-report, explain etc. (scaffolded)
    m = subparsers.add_parser("metrics", help="Show aggregated metrics (stub)")
    m.set_defaults(
        func=lambda a: (print("Metrics: use AgentOrchestrator.get_stats() in code"), 0)
    )

    # #173: One-liner stealth scrape
    sc = subparsers.add_parser(
        "scrape", help="One-liner stealth scrape from terminal (#173)"
    )
    sc.add_argument("url", help="URL to scrape")
    sc.add_argument(
        "--extract",
        choices=["text", "html", "title"],
        default="text",
        help="Content extraction type",
    )
    sc.add_argument(
        "--platform",
        default=None,
        help="Platform for recovery tuning (e.g. linkedin, amazon)",
    )
    sc.add_argument(
        "--preset",
        default=None,
        choices=[None] + list_presets(),
        help="Apply platform preset",
    )
    sc.add_argument(
        "--region", default="global", help="TLS region (us/eu/japan/korea/global)"
    )
    sc.add_argument(
        "--max-length", type=int, default=None, help="Truncate output to N characters"
    )
    sc.set_defaults(func=_cmd_scrape)

    dash = subparsers.add_parser(
        "dashboard", help="Start the Hermes Browser Dashboard"
    )
    dash.add_argument("--host", default="127.0.0.1")
    dash.add_argument("--port", type=int, default=8443)
    dash.add_argument(
        "--password",
        default=None,
        help="Dashboard password (defaults to HERMES_DASHBOARD_PASSWORD or change-me)",
    )
    dash.set_defaults(func=_cmd_dashboard)

    args = parser.parse_args()
    if hasattr(args, "func"):
        rc = asyncio.run(args.func(args))
        sys.exit(rc)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
