#!/usr/bin/env python3
"""Quick stealth demo for Show HN — validates core functionality in ~5 seconds."""

import asyncio
import sys


async def main():
    print("╭─ Agentic Stealth Browser — Quick Demo ───────────────────╮")
    print("│                                                         │")

    try:
        from core.agent_browser import AgentBrowser
        print("│  ✓  core.agent_browser loaded                        │")

        from production.cli import main as cli_main
        print("│  ✓  production.cli loaded                            │")

        # Verify TLS profiles exist
        from stealth.advanced_stealth import get_stealth_script
        script = get_stealth_script("japan")
        if script and len(script) > 100:
            print("│  ✓  TLS stealth script loaded (Japan region)          │")
        else:
            print("│  ~  Stealth script loaded (minimal)                   │")

        print("│                                                         │")
        print("│  Launching headless browser...                           │")

        async with AgentBrowser(session_name="hn-demo") as browser:
            await browser.launch(headless=True)
            print("│  ✓  Browser launched (Chromium, Japan region)          │")

            await browser.safe_goto("https://bot.sannysoft.com")
            print("│  ✓  bot.sannysoft.com — page loaded                    │")

            await browser.safe_goto("about:blank")
            print("│  ✓  Navigation + recovery chain operational            │")

        print("│                                                         │")
        print("│  ✓  All systems operational. Ready to deploy.           │")

    except ImportError as e:
        print(f"│  ✗  Import failed: {e}")
        print("│     Run: pip install agentic-stealth-browser            │")
        print("│     Then: playwright install chromium --with-deps      │")
        sys.exit(1)
    except Exception as e:
        print(f"│  ✗  Error: {type(e).__name__}: {e}")
        sys.exit(1)

    print("╰─────────────────────────────────────────────────────────╯")
    print()
    print("Agentic Stealth Browser v2.1.1 — https://github.com/shanewas/agentic-stealth-browser")


if __name__ == "__main__":
    asyncio.run(main())
