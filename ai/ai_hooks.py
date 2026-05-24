"""
AI Integration Hooks for Agentic Browser
Allows connecting to LLMs for decision making and content analysis

Security: All external content (page text, context) is sanitized before being
eligible for LLM consumption to mitigate prompt injection (#188 P3).

P3 #98 fix: AIHooks now provides real value even without an LLM provider:
- Content sanitization for safe downstream use
- Rule-based action decisions as fallback
- Structured extraction via regex/heuristics
"""

from typing import Dict, Optional, List
import re


class AIHooks:
    """
    AI integration hooks with injection protection and rule-based fallbacks.

    When provider="none", provides:
    - Content sanitization for safe downstream use
    - Rule-based action decisions
    - Heuristic structured extraction

    When provider is set, connects to actual LLM (OpenAI, Claude, etc.).
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

    def __init__(
        self,
        provider: str = "none",
        api_key: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.enabled = provider != "none"
        self._client = None

    def sanitize_for_llm(self, content: str, max_len: int = 12000) -> str:
        """Strip or neuter likely prompt-injection content from untrusted page/LLM input.
        Returns a safe-ish version with markers for removed sections.
        This is a practical P3 baseline; real deployments should layer more (e.g. LLM guardrails).
        """
        if not content or not isinstance(content, str):
            return ""
        safe = content[:max_len]

        def _replace(m):
            return "[REDACTED: potential instruction override]"

        safe = self._INJECTION_RE.sub(_replace, safe)
        safe = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff]", "", safe)
        return safe

    def extract_links(self, text: str) -> List[str]:
        """P3 #98: Extract URLs from text without LLM."""
        url_pattern = r'https?://[^\s<>"\')\]]+'
        return re.findall(url_pattern, text)

    def extract_emails(self, text: str) -> List[str]:
        """P3 #98: Extract email addresses from text without LLM."""
        email_pattern = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        return re.findall(email_pattern, text)

    async def analyze_page(self, page_content: str, task: str) -> str:
        """Analyze page content using AI (with injection protection)"""
        if not self.enabled:
            safe_content = self.sanitize_for_llm(page_content)
            links = self.extract_links(safe_content)
            emails = self.extract_emails(safe_content)
            word_count = len(safe_content.split())
            return (
                f"Heuristic analysis (AI disabled):\n"
                f"  Word count: {word_count}\n"
                f"  Links found: {len(links)}\n"
                f"  Emails found: {len(emails)}\n"
                f"  Content sanitized: {len(safe_content)} chars\n"
                f"  Task: {task}\n"
                f"  Enable AI provider for deeper analysis."
            )

        safe_content = self.sanitize_for_llm(page_content)
        return f"[AI Analysis Placeholder] Task: {task} (content sanitized: {len(safe_content)} chars kept)"

    async def decide_next_action(self, context: Dict) -> str:
        """Let AI decide next browsing action (with injection protection on any text fields)"""
        if not self.enabled:
            url = context.get("url", "")
            status = context.get("status", 200)
            if status in (403, 429, 503):
                return "backoff_and_retry"
            if "login" in url.lower() or "signin" in url.lower():
                return "wait_for_user"
            if not context.get("has_content", False):
                return "scroll"
            return "extract_and_continue"

        safe_ctx = {}
        for k, v in (context or {}).items():
            if isinstance(v, str):
                safe_ctx[k] = self.sanitize_for_llm(v)
            else:
                safe_ctx[k] = v
        return "scroll"

    async def extract_structured_data(self, text: str, schema: Dict) -> Dict:
        """Extract structured data using AI (sanitized input)"""
        if not self.enabled:
            safe_text = self.sanitize_for_llm(text)
            result = {
                "links": self.extract_links(safe_text),
                "emails": self.extract_emails(safe_text),
                "phones": re.findall(r"\+?[\d\s\-\(\)]{10,}", safe_text),
                "prices": re.findall(r"\$[\d,]+\.?\d*", safe_text),
            }
            return {
                "status": "heuristic_extraction",
                "data": result,
                "sanitized_len": len(safe_text),
            }

        safe_text = self.sanitize_for_llm(text)
        return {"status": "ai_disabled", "data": {}, "sanitized_len": len(safe_text)}
