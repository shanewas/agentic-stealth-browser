# Data Handling & Retention

## What the tool persists

- Scraped results (wherever the operator's workflow writes them)
- Cookies under `sessions/`
- Screenshots under `checkpoints/`

## Data controller

The operator running this tool is the data controller for any data it collects or persists. The maintainers are not.

## Retention recommendation

By default, retain persisted files no longer than necessary for the operator's task — 30 days is a reasonable starting point unless the operator's own policy or applicable law requires otherwise.

## Deletion

Deletion is the operator's responsibility. Documented deletion means removing the relevant files under `sessions/` and `checkpoints/`.
