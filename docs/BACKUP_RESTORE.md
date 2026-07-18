# Backup & Restore

## What to back up

- `sessions/` — logged-in session cookies. Each one requires a fresh human
  login/CAPTCHA solve to rebuild, so losing this directory is expensive, not
  just inconvenient.
- `checkpoints/` — scraping/workflow checkpoint state.
- Audit logs — `audit/*.jsonl` and the dashboard's `audit.jsonl`.

## Why it's expensive to rebuild

Session cookies represent an authenticated browser state obtained by a human
solving a login flow (often including CAPTCHA). There is no automated way to
regenerate them — losing `sessions/` means someone has to log back in by hand
for every account.

## Backup

```
python scripts/backup_sessions.py [output_dir]
```

Produces `backup-sessions-<YYYYmmdd-HHMMSS>.tar.gz` containing `sessions/`
(and `checkpoints/` if present). Copy `audit/*.jsonl` separately if you need
audit history preserved too.

## Restore procedure

1. Stop the service (stop any running scraping/workflow process).
2. Extract the archive into the repo root, restoring `sessions/` and
   `checkpoints/`:
   ```
   tar -xzf backup-sessions-<timestamp>.tar.gz
   ```
3. Restart the service.

## Encrypt at rest

Session cookies are credentials. Encrypt backup archives at rest (e.g. GPG,
age, or an encrypted storage bucket) — never store `backup-sessions-*.tar.gz`
unencrypted in shared or cloud storage.
