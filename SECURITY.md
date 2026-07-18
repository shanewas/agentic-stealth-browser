# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 3.0.x   | :white_check_mark: |
| < 3.0   | :x:                |

This table is updated as part of every release; a release is not complete until the current minor version appears here.

## Reporting a Vulnerability

We take the security of Agentic Stealth Browser seriously. If you believe you have found a security vulnerability, please report it to us as described below.

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please report them via [GitHub Security Advisory](https://github.com/shanewas/agentic-stealth-browser/security/advisories/new).

You should receive a response within 48 hours. If for some reason you do not, please follow up via email to ensure we received your original message.

## Security Best Practices

When using this framework in production:

1. **Never commit cookies or session data** — Use encrypted cookie storage (`save_cookies_to_file(encrypt=True)`)
2. **Rotate proxy credentials** — Use environment variables, never hardcode in source
3. **Enable audit logging** — All actions should be logged for forensic analysis
4. **Use region-aligned TLS profiles** — Mismatched fingerprints are a primary detection vector
5. **Always warm up sessions** — Cold sessions are flagged by anti-bot systems
6. **Isolate accounts** — Never share proxies or browser contexts across accounts
7. **Keep dependencies updated** — Regularly update Playwright and Python dependencies

## MCP Approval Mode

The MCP server ships fail-closed: sensitive actions (`execute_js`, `stealth_launch`, navigate to unknown domains, `run_workflow`, `stealth_replay`) return `MCP_APPROVAL_REQUIRED` until approved. Set `STEALTH_APPROVAL_MODE=permissive` to auto-approve all sensitive actions (previous default; not recommended for shared/production deployments).

## Known Limitations

- TLS fingerprint spoofing is limited to browser launch arguments; true ClientHello manipulation requires lower-level network stack access
- This framework is designed for legitimate automation use cases; misuse may violate terms of service of target websites

## Responsible Disclosure

We follow a 90-day disclosure timeline. We will work with you to understand and resolve the issue before any public disclosure.
