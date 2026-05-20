"""
AI Integration Hooks for Agentic Browser
Allows connecting to LLMs for decision making and content analysis

Security: All external content (page text, context) is sanitized before being
eligible for LLM consumption to mitigate prompt injection (#188 P3).
"""

from typing import Any, Dict, Optional
import re


class AIHooks:
    """
    Placeholder for AI integration.
    Can be connected to OpenAI, Claude, Grok, or local models.

    IMPORTANT SECURITY NOTE: When wiring a real LLM provider, ALWAYS run
    the output of sanitize_for_llm() (or stronger) on any untrusted content
    (page HTML/text, scraped data) before including in prompts. The hooks
    now apply basic protection by default.
    """
    
    # Common injection / jailbreak patterns observed in web content & attacks
    _INJECTION_PATTERNS = [
        r"\b(ignore|disregard|forget)\s+(all\s+)?(previous|above|prior|earlier|system|instructions?)\b",
        r"\b(you are now|act as|role.?play|pretend you are|from now on you are)\b",
        r"\b(system prompt|override|jailbreak|do anything|no restrictions|unfiltered)\b",
        r"^\s*(system:|assistant:|user:)\s*",
        r"\b(output only the|respond with only|print exactly|your new instructions)\b",
    ]
    _INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)

    def __init__(self, provider: str = "none"):
        self.provider = provider
        self.enabled = provider != "none"
    
    def sanitize_for_llm(self, content: str, max_len: int = 12000) -> str:
        """Strip or neuter likely prompt-injection content from untrusted page/LLM input.
        Returns a safe-ish version with markers for removed sections.
        This is a practical P3 baseline; real deployments should layer more (e.g. LLM guardrails).
        """
        if not content or not isinstance(content, str):
            return ""
        # Truncate first (prevent token exhaustion attacks too)
        safe = content[:max_len]
        # Replace high-confidence injection attempts with neutral markers
        def _replace(m):
            return "[REDACTED: potential instruction override]"
        safe = self._INJECTION_RE.sub(_replace, safe)
        # Also strip common hidden unicode / zero-width tricks used in injection
        safe = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff]", "", safe)
        return safe

    async def analyze_page(self, page_content: str, task: str) -> str:
        """Analyze page content using AI (with injection protection)"""
        if not self.enabled:
            return "AI not enabled. Set provider to use analysis."
        
        safe_content = self.sanitize_for_llm(page_content)
        # Placeholder - will be implemented with actual LLM calls later
        # In real impl: pass safe_content + sanitized task to LLM
        return f"[AI Analysis Placeholder] Task: {task} (content sanitized: {len(safe_content)} chars kept)"
    
    async def decide_next_action(self, context: Dict) -> str:
        """Let AI decide next browsing action (with injection protection on any text fields)"""
        if not self.enabled:
            return "scroll"
        
        # Sanitize any string values in context that might come from page
        safe_ctx = {}
        for k, v in (context or {}).items():
            if isinstance(v, str):
                safe_ctx[k] = self.sanitize_for_llm(v)
            else:
                safe_ctx[k] = v
        # Future: Connect to LLM for autonomous decision making using safe_ctx
        return "scroll"
    
    async def extract_structured_data(self, text: str, schema: Dict) -> Dict:
        """Extract structured data using AI (sanitized input)"""
        if not self.enabled:
            return {}
        
        safe_text = self.sanitize_for_llm(text)
        return {"status": "ai_disabled", "data": {}, "sanitized_len": len(safe_text)}
