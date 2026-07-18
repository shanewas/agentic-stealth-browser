# Security Incident Response

## Reporting

See [SECURITY.md](../SECURITY.md) for how to report a vulnerability.

## Credential / Key Compromise

1. Rotate the leaked secret.
2. Invalidate live dashboard sessions by rotating `DashboardSettings.secret_key`.
3. Delete affected session cookie files under `sessions/`.
4. Force re-login for all operators.

## Triage Severity

- **SEV1** — key/credential leak
- **SEV2** — data exposure
- **SEV3** — availability

## Post-Incident

Record the incident in the CHANGELOG Security section.
