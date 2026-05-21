# Cost & Resource Estimation Guide (#177)

This guide helps you estimate the computational, network, and financial costs of running the Agentic Stealth Browser at scale.

---

## Resource Baseline (Per Browser Instance)

| Resource | Light Mode | Normal Mode | Heavy Mode |
|---|---|---|---|
| **RAM** | ~300-400 MB | ~400-600 MB | ~600-900 MB |
| **CPU** | 5-10% (idle), 20-40% (active) | 10-20% (idle), 30-60% (active) | 15-30% (idle), 40-80% (active) |
| **Disk (per session)** | ~50-100 MB | ~100-200 MB | ~200-500 MB |
| **Network (per navigation)** | ~1-5 MB | ~2-10 MB | ~5-20 MB |
| **Launch time** | ~2-4 seconds | ~4-8 seconds | ~8-15 seconds |
| **Warm-up time** | ~1-2 seconds | ~3-6 seconds | ~8-15 seconds |

---

## Scaling Estimates

### Concurrent Instances

| Concurrent Browsers | RAM Required | CPU Cores (min) | Recommended Setup |
|---|---|---|---|
| 1-5 | 2-4 GB | 2-4 | Single machine, normal mode |
| 5-10 | 4-8 GB | 4-8 | Single machine, light mode for some |
| 10-25 | 8-20 GB | 8-16 | Multiple machines or Docker containers |
| 25-50 | 20-40 GB | 16-32 | Kubernetes cluster, pooled contexts |
| 50-100 | 40-80 GB | 32-64 | Distributed architecture, one process per account |

### Cost Per 1,000 Navigations (Cloud VM Estimates)

| Provider | Instance Type | Cost/hr | Navigations/hr | Cost per 1K navs |
|---|---|---|---|---|
| AWS | t3.medium | ~$0.04 | ~200-400 | ~$0.10-0.20 |
| AWS | t3.large | ~$0.08 | ~400-800 | ~$0.10-0.20 |
| GCP | e2-medium | ~$0.03 | ~200-400 | ~$0.08-0.15 |
| Hetzner | CPX21 | ~$0.01 | ~200-400 | ~$0.03-0.05 |

---

## Proxy Costs

| Proxy Type | Cost per GB | Recommended Use |
|---|---|---|
| Datacenter | $1-5/GB | Low-sensitivity sites (Wikipedia, GitHub) |
| Residential | $10-20/GB | Medium/high-sensitivity (LinkedIn, Amazon) |
| Mobile | $20-40/GB | Critical-sensitivity (Cloudflare-protected) |

**Estimated bandwidth per 1,000 navigations:** 2-10 GB depending on page complexity.

---

## LLM API Costs (If Using AI Hooks)

| Model | Cost per 1K tokens | Tokens per navigation (est.) | Cost per 1K navs |
|---|---|---|---|
| GPT-4o mini | $0.15 | 500-2,000 | $0.08-0.30 |
| GPT-4o | $2.50 | 500-2,000 | $1.25-5.00 |
| Claude Sonnet | $3.00 | 500-2,000 | $1.50-6.00 |
| Local (Ollama) | $0 (hardware) | 500-2,000 | $0 (GPU cost amortized) |

---

## Optimization Tips

### Reduce Costs
1. **Use `light_mode=True`** — Skips expensive warm-up steps, reduces launch time by 50%+
2. **Use pooled contexts** (`use_pooled_context=True`) — Shares a single Chromium process across multiple sessions, saving 200-400 MB per additional instance
3. **Set `AGENTIC_STEALTH_REALISM=light`** — Reduces CDP chatter and micro-movements in CI/headless environments
4. **Reuse sessions** — Load cookies from file instead of re-authenticating
5. **Use datacenter proxies for low-sensitivity sites** — 5-10x cheaper than residential

### Improve Performance
1. **Use `warm_up_before_work_background()`** — Non-blocking warm-up allows concurrent work
2. **Pre-warm browser pool** — Launch browsers in advance for instant availability
3. **Use `safe_goto` with appropriate `platform`** — Platform-specific recovery strategies reduce wasted retries
4. **Set reasonable rate limits** — Prevents blocks that trigger expensive recovery flows

### Memory Management
1. **Close browsers promptly** — Use `async with AgentBrowser()` for guaranteed cleanup
2. **Prune ephemeral sessions** — Call `session_manager.prune_ephemeral()` regularly
3. **Monitor disk usage** — Session data accumulates; clean up old sessions periodically
4. **Use separate processes for multi-account** — Prevents memory leaks from shared state

---

## Monitoring & Alerting

Use the built-in metrics and health endpoints:

```python
# Get metrics summary
summary = browser.metrics.get_summary()
print(f"Correlation ID: {summary['correlation_id']}")
print(f"Uptime: {summary['uptime_seconds']}s")
print(f"Success rate: {summary['success_rate']}%")

# Prometheus export
prom_metrics = browser.metrics.get_prometheus_metrics()
```

Set up alerts for:
- Success rate dropping below 90%
- Block rate exceeding 10%
- Memory usage exceeding 80% of available RAM
- Proxy consecutive failures exceeding 3
