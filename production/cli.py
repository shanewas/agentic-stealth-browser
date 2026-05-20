#!/usr/bin/env python3
"""
Production CLI entrypoint for Agentic Stealth Browser (addresses #233, #281).

High-value DX: `stealth-browser health` and `status` commands expose:
  - proxy usage / current config
  - account state (healthy/degraded)
  - block rate (from recovery + metrics)
  - TLS/preset/region, cookies, recovery stats, current URL after launch

Usage examples:
  python -m production.cli health --preset linkedin_2026 --region us --headless
  stealth-browser status
  stealth-browser health --no-launch   # future: inspect persisted state

Also supports smoke, metrics, debug-report for operators.
"""
import argparse
import asyncio
import json
import sys
from typing import Any, Dict

from core.agent_browser import AgentBrowser
from stealth.presets import list_presets


def _print_json(obj: Dict[str, Any], pretty: bool = True) -> None:
    if pretty:
        print(json.dumps(obj, indent=2, default=str))
    else:
        print(json.dumps(obj, default=str))


async def _cmd_health(args: argparse.Namespace) -> int:
    """Launch (optionally) and print rich health/status snapshot. Core of #281."""
    print("[stealth-browser] Health/Status command (P2/P3 DX observability)")
    print(f"  preset={args.preset} region={args.region} headless={args.headless} debug={args.debug}")

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
        _print_json(health)

        # Also surface proxy/account/block highlights for quick human reading
        print("\n=== QUICK OBSERVABILITY SUMMARY ===")
        print(f"  Launched: {health.get('launched')}")
        print(f"  Preset: {health.get('preset')}")
        print(f"  Region / TLS: {health.get('region')} / {health.get('tls_profile', {}).get('name')}")
        print(f"  Proxy: {health.get('proxy')}")
        print(f"  Account State: {health.get('account_state')}")
        print(f"  Block Rate: {health.get('block_rate_pct')}%")
        print(f"  Cookies: {health.get('cookies', {}).get('status')}")
        print(f"  Recovery: {health.get('recovery', {}).get('last_block', 'none')}")
        print("====================================\n")

        if args.debug:
            dbg = await browser.debug_report(print_report=True)
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
    from audit.logger import AuditLogger
    log = AuditLogger(args.session or "default")
    seq = log.replay_sequence(getattr(args, "limit", 15))
    _print_json({"session": log.session_name, "replay_sequence": seq, "count": len(seq)})
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="stealth-browser",
        description="Agentic Stealth Browser Production CLI - DX & Observability (#281)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # health (primary high-value DX command)
    h = subparsers.add_parser("health", help="Rich health snapshot: proxy usage, block rate, account state, TLS/preset")
    h.add_argument("--preset", default=None, choices=[None] + list_presets(), help="Apply 2026 platform preset")
    h.add_argument("--region", default="global", help="TLS region (us/eu/japan/korea/global)")
    h.add_argument("--session", default=None, help="Named session (persistent cookies)")
    h.add_argument("--headless", action="store_true", default=True, help="Run headless (default)")
    h.add_argument("--no-headless", dest="headless", action="store_false", help="Run headed for visual debug")
    h.add_argument("--debug", action="store_true", help="Enable debug mode + fingerprint dump")
    h.add_argument("--json", action="store_true", help="Raw JSON only output")
    h.set_defaults(func=_cmd_health)

    # status (alias)
    s = subparsers.add_parser("status", help="Current browser status (alias to health)")
    s.add_argument("--preset", default=None, choices=[None] + list_presets())
    s.add_argument("--region", default="global")
    s.add_argument("--debug", action="store_true")
    s.set_defaults(func=_cmd_status)

    # list-presets
    lp = subparsers.add_parser("list-presets", help="List available platform presets (#288)")
    lp.set_defaults(func=_cmd_list_presets)

    rp = subparsers.add_parser("replay", help="Replay/inspect actions from audit logs (#253 light)")
    rp.add_argument("--session", default="default")
    rp.add_argument("--limit", type=int, default=15)
    rp.set_defaults(func=_cmd_replay)

    # future: metrics, smoke, debug-report, explain etc. (scaffolded)
    m = subparsers.add_parser("metrics", help="Show aggregated metrics (stub)")
    m.set_defaults(func=lambda a: (print("Metrics: use AgentOrchestrator.get_stats() in code"), 0))

    args = parser.parse_args()
    if hasattr(args, "func"):
        rc = asyncio.run(args.func(args))
        sys.exit(rc)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
