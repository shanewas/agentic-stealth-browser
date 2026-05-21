"""
"Explain why blocked" Analyzer + Actionable Recommendations (DX #273 P1)

Standalone + integrated helper that turns cryptic block signals into clear English
plus prioritized things an operator can do RIGHT NOW to get unblocked.

Designed to be called from:
- AntiBlockOrchestrator.recover()
- MCP tools
- Notebooks / debug sessions after a failure
- Standalone: from recovery.explain_blocked import explain_why_blocked

Integrates with AuditLogger automatically when an orchestrator is passed.
"""

from typing import Dict, Any, Optional, List
from recovery.anti_block_orchestrator import BlockType, RecoveryContext, AntiBlockOrchestrator
from audit.logger import AuditLogger


async def explain_why_blocked(
    block_type: Optional[BlockType] = None,
    platform: str = "unknown",
    http_status: Optional[int] = None,
    response_time: float = 0.0,
    recent_error: str = "",
    orchestrator: Optional[AntiBlockOrchestrator] = None,
    context: Optional[RecoveryContext] = None,
) -> Dict[str, Any]:
    """
    Core DX function for #273.

    Returns a rich, human-readable diagnosis and a list of concrete next actions.
    """
    if context is None:
        context = RecoveryContext(
            platform=platform,
            url="",
            last_error=recent_error or "",
            http_status=http_status,
            response_time=response_time,
        )

    detected_type = block_type
    if detected_type is None and orchestrator:
        detected_type = await orchestrator.detect_block(context)
    if detected_type is None:
        detected_type = BlockType.UNKNOWN

    platform_l = platform.lower()

    base_explanations = {
        BlockType.CAPTCHA: "The page returned a CAPTCHA / JS challenge / 'verify you are human' experience. Your browser fingerprint or behavior tripped the site's bot detector.",
        BlockType.HARD_RATE_LIMIT: "Explicit rate limiting (429 or 'too many requests'). The platform has flagged this session/IP/account for aggressive usage.",
        BlockType.SOFT_RATE_LIMIT: "Soft block (403, unusually slow responses, or generic denial). The site is suspicious but has not fully cut you off yet.",
        BlockType.ACCOUNT_RESTRICTION: "Account-level restriction detected (LinkedIn 'unusual activity', 'security verification', 'temporarily restricted').",
        BlockType.PROXY_BLOCK: "Proxy or IP reputation problem (often 503/ proxy errors or datacenter flags).",
        BlockType.NONE: "No strong block signals — you may simply be seeing normal variation or a transient issue.",
        BlockType.UNKNOWN: "Unknown block type — the system detected something unusual but could not classify it precisely.",
    }

    explanation = base_explanations.get(detected_type, base_explanations[BlockType.UNKNOWN])

    recs: List[str] = [
        "1. Rotate to a fresh high-quality residential proxy (sticky session < 30min old) and/or new anonymous browser profile.",
        "2. Immediately slow down: use heavier think() delays (8-25s) and warm_up_before_work('heavy') before continuing work.",
        "3. Load cookies that were exported from a REAL browser while logged into the exact same account (this is the #1 success factor for LinkedIn/Upwork).",
        "4. Switch to a platform-specific preset: launch(..., preset='linkedin_2026' or 'amazon_2026') — this gives correct TLS + behavior + locale.",
        "5. Reduce parallelization and request rate. Call browser.set_rate_limit(domain, requests_per_minute=4).",
    ]

    if "linkedin" in platform_l or detected_type == BlockType.ACCOUNT_RESTRICTION:
        recs.insert(0, "LINKEDIN-SPECIFIC: Always warm up on https://www.linkedin.com/feed/ with heavy behavior before viewing any profile. Use the linkedin_2026 preset.")
        recs.append("After a restriction hit, wait 30-90+ minutes + new proxy before retrying. Consider a different persona entirely.")
    if detected_type == BlockType.CAPTCHA:
        recs.append("For persistent CAPTCHAs: run with headed=True for manual solving during development, or integrate a solver service for prod.")
    if "amazon" in platform_l:
        recs.append("Amazon loves consistent US residential + realistic first-page timing. Avoid datacenter proxies.")

    result = {
        "block_type": detected_type.value if hasattr(detected_type, "value") else str(detected_type),
        "platform": platform,
        "explanation": explanation,
        "likely_root_cause": "Combination of TLS fingerprint / canvas/WebGL / header / behavioral timing / IP reputation signals failed to look human enough for the target.",
        "actionable_recommendations": recs,
        "quick_win_command": "await browser.launch(debug=True, preset='linkedin_2026' if 'linkedin' in platform else 'general'); await browser.debug_report(print_report=True)",
        "confidence": "high" if detected_type != BlockType.NONE else "low",
    }

    # Auto-log when possible
    logger = getattr(orchestrator, "logger", None) or AuditLogger("explain_blocked")
    logger.log_action("explain_why_blocked", result, level="warning")

    return result


# Convenience re-export
__all__ = ["explain_why_blocked", "BlockType"]
