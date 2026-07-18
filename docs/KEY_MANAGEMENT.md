# Key Management

| Secret | Source | Rotation procedure |
|---|---|---|
| Cookie encryption key | env var | Generate a new key, re-encrypt or discard existing session cookie files under `sessions/`, force re-login. |
| Dashboard `secret_key` (`DashboardSettings.secret_key`) | env var | Set a new value, restart the dashboard process — this invalidates all live dashboard sessions. |
| HMAC / audit keys | env var | Generate a new key, redeploy, allow a short overlap window if signed artifacts must remain verifiable during rotation. |

Keys must come from environment variables and must never be committed to the repository. Rotation should be performed immediately on suspected compromise (see [docs/INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md)) and periodically as routine hygiene.
