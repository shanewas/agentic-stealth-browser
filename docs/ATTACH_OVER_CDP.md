# Attach to an existing browser (WSL → Windows, container → host, remote)

`AgentBrowser` can now *attach* to a browser you've already launched yourself,
instead of spawning its own Chromium. This is the right tool when you want to
drive the **real Chrome window** the user is using — for example, controlling
a Chrome on the Windows host from inside WSL.

## When to use this vs. `launch()`

| Scenario | Use |
|----------|-----|
| Headless automation on a server | `launch(headless=True)` (full stealth) |
| Run from your own desktop, want a visible browser | `launch(headless=False)` |
| **Control a browser running on a different host or OS** | **`attach_over_cdp()`** |
| Drive an already-open user session (cookies, logged-in tabs) | `attach_over_cdp(new_context=False)` |
| Reuse the user's Chrome process but with a clean profile | `attach_over_cdp(new_context=True)` |

## Stealth degradation in attach mode

Attach mode keeps the **runtime** stealth layer (init scripts: navigator
patches, `webdriver` flag removal, canvas/WebGL/audio noise) but cannot apply
**launch-time** stealth because the browser process already exists:

- ❌ TLS / JA3 / JA4 fingerprint (process-level TLS stack)
- ❌ Launch args, sandbox flags, `--user-agent`
- ❌ User-data-dir profile selection
- ❌ Regional preset (the TLS profile part)
- ✅ Init-script stealth (all `navigator.*` + canvas/WebGL/audio patches)
- ✅ Human behavior, recovery, workflow runner
- ✅ Per-context cookies, viewport, locale, proxy (when `new_context=True`)

These degradations are returned in the response payload's `degradation` field
so callers can log them.

## WSL → Windows host walkthrough

### 1. Launch Chrome on Windows with remote debugging

In a **Windows PowerShell** (not WSL):

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
    --remote-debugging-port=9222 `
    --user-data-dir="$env:TEMP\chrome-cdp-profile"
```

Using a dedicated `--user-data-dir` avoids clashing with your normal Chrome.
Drop it to attach to your **real** profile (with all its cookies/logins).

### 2. Allow WSL to reach the port

By default Chrome binds `--remote-debugging-port` to `127.0.0.1` on Windows,
which WSL2 cannot reach directly. Two options:

**Option A — Bind to all interfaces (simplest, less safe):**
```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
    --remote-debugging-port=9222 `
    --remote-allow-origins=* `
    --user-data-dir="$env:TEMP\chrome-cdp-profile"
```
Then open the port through Windows Firewall to the WSL subnet only.

**Option B — Port forward inside WSL (preferred):**

WSL2 can reach the Windows host via the gateway IP in `/etc/resolv.conf`:

```bash
# inside WSL
WIN_HOST=$(ip route | awk '/^default/ {print $3}')
echo "Windows host: $WIN_HOST"
```

If Chrome bound to 127.0.0.1 on Windows, set up an `ssh -L` or use
[`wsl-vpnkit`](https://github.com/sakai135/wsl-vpnkit), or just bind to all
interfaces as in Option A — Windows Firewall is your real boundary.

### 3. Attach from WSL

```python
import asyncio
from core.agent_browser import AgentBrowser

async def main():
    win_host = "<paste WIN_HOST from step 2>"
    async with AgentBrowser(session_name="wsl-windows-demo") as browser:
        info = await browser.attach_over_cdp(
            f"http://{win_host}:9222",
            new_context=True,        # don't touch the user's tabs
            apply_stealth=True,
        )
        print("attached:", info["browser_version"], info["degradation"])

        await browser.safe_goto("https://bot.sannysoft.com")
        # init-script stealth still hides navigator.webdriver, etc.

asyncio.run(main())
```

### 4. MCP variant

For MCP clients, the same flow is exposed as the `stealth_attach_over_cdp`
tool:

```json
{
  "name": "stealth_attach_over_cdp",
  "arguments": {
    "session_name": "wsl-windows-demo",
    "cdp_url": "http://172.20.16.1:9222",
    "new_context": true,
    "allow_remote": true
  }
}
```

`allow_remote: true` is **required** for any non-loopback host. Loopback URLs
(`127.0.0.1`, `localhost`, `::1`) work without it.

## Teardown semantics

`close()` (and `async with` exit) only:

1. Closes the page we opened
2. Closes the context we created — but **only if** `new_context=True` was
   passed; adopted user contexts are left intact
3. Disconnects the Playwright CDP session — the **external browser process
   stays alive**

This is the inverse of `launch()`, which always terminates the browser it
spawned.

## Security

Attaching to a CDP endpoint grants **full control** of that browser, including
any authenticated sessions the user is logged into. Two rules:

1. Never expose `--remote-debugging-port` to the public internet. Bind to
   loopback or your local trust boundary.
2. The MCP tool refuses non-loopback hosts unless `allow_remote=true` is
   explicit, so a stray LLM call can't silently attach across the network.
