# Platform Recipes (P1 #189)

Small, runnable, self-contained Python scripts that exercise the public SDK
against the platforms this project was built to handle. Each one is <50 lines,
runs headless, and exits.

| Script | What it does |
|---|---|
| `01_cloudflare_bypass.py` | Load `nowsecure.nl`, let the recovery orchestrator handle the challenge, save a screenshot, print the final title |
| `02_linkedin_search.py` | Apply the `linkedin_2026` preset, sanity-check `navigator.webdriver` on a public LinkedIn surface, then do a public job search via DuckDuckGo |
| `03_amazon_product.py` | Fetch a product page, extract title + price into a dict |

Markdown recipes (longer-form, human-curated) live alongside:

- `linkedin.md` — preset selection, region, warm-up, real cookies

See the main [README](../../README.md) for the recommended production flow
and the [documentation index](../../docs/README.md) for the full docs tree.
