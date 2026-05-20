| Method                        | Description                              | Parameters |
|-------------------------------|------------------------------------------|----------|
| `launch(headless=True)`       | Launch browser with stealth              | `headless`, `slow_mo` |
| `safe_goto(url, platform)`    | Navigate with recovery                   | `url`, `platform`, `warm_up` |
| `load_cookies_from_file(path)`| Load cookies from real browser           | `cookies_path` |
| `warm_up_before_work(intensity)` | Perform natural warm-up               | `intensity` ("light", "medium", "heavy") |
| `ensure_cookies_fresh(hours)` | Auto-refresh cookies if needed           | `max_age_hours` |

### Human Behavior Methods

| Method                        | Description                              |
|-------------------------------|------------------------------------------|
| `move_mouse_naturally(x, y)`  | Bézier curve mouse movement              |
| `human_click(selector)`       | Natural click with micro-corrections     |
| `type_like_human(selector, text)` | Human-like typing with mistakes      |
| `scroll_naturally(pixels)`    | Variable speed scrolling                 |
| `simulate_reading(seconds)`   | Reading simulation with re-reads         |
| `fake_search_action(query)`   | Simulate search behavior                 |
| `random_idle_behavior(seconds)` | Advanced idle patterns                 |

### Recovery & Proxy

| Method                        | Description                              |
|-------------------------------|------------------------------------------|
| `safe_goto` / `safe_click`    | Actions with automatic recovery          |
| `ensure_cookies_fresh(hours)` | Auto cookie refresh                      |
| `warm_up_session(intensity)`  | Session warm-up before work              |
