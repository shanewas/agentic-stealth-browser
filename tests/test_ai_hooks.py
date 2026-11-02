"""Tests for AI integration hooks (ai/ai_hooks.py)."""

import asyncio
import re
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai.ai_hooks import AIHooks, AIProviderUnavailableError


class TestEnabledProviderIsHonest:
    """An enabled-but-unimplemented provider must not fabricate results."""

    def _enabled(self):
        return AIHooks(provider="openai", api_key="test-key", model="test-model")

    def test_analyze_page_raises_unavailable(self):
        with pytest.raises(AIProviderUnavailableError):
            asyncio.run(self._enabled().analyze_page("some page", "summarize"))

    def test_decide_next_action_raises_unavailable_even_for_blocked_context(self):
        with pytest.raises(AIProviderUnavailableError):
            asyncio.run(
                self._enabled().decide_next_action(
                    {"url": "https://example.com/login", "status": 403}
                )
            )

    def test_extract_structured_data_raises_unavailable(self):
        with pytest.raises(AIProviderUnavailableError):
            asyncio.run(
                self._enabled().extract_structured_data(
                    "call 555 123 4567", {"phone": "string"}
                )
            )


class TestDisabledProviderUnchanged:
    def _disabled(self):
        return AIHooks(provider="none")

    def test_analyze_page_uses_heuristics(self):
        result = asyncio.run(
            self._disabled().analyze_page("hello https://example.com", "summarize")
        )
        assert "Heuristic analysis (AI disabled)" in result

    def test_decide_next_action_rules(self):
        hooks = self._disabled()
        assert (
            asyncio.run(hooks.decide_next_action({"url": "https://x.test/", "status": 403}))
            == "backoff_and_retry"
        )
        assert (
            asyncio.run(hooks.decide_next_action({"url": "https://x.test/login"}))
            == "wait_for_user"
        )

    def test_extract_structured_data_uses_heuristics(self):
        result = asyncio.run(
            self._disabled().extract_structured_data(
                "see https://example.com or a@example.com", {}
            )
        )
        assert result["status"] == "heuristic_extraction"
        assert result["data"]["links"] == ["https://example.com"]
        assert result["data"]["emails"] == ["a@example.com"]


class TestSanitizeRoleMarkers:
    def test_marker_at_string_start_removed(self):
        result = AIHooks(provider="none").sanitize_for_llm("system: do something")
        assert "system:" not in result.lower()

    def test_marker_after_newline_removed(self):
        result = AIHooks(provider="none").sanitize_for_llm(
            "ordinary text\nassistant: do something\nmore text"
        )
        assert "assistant:" not in result.lower()
        assert "ordinary text" in result
        assert "more text" in result

    def test_marker_mid_line_preserved(self):
        result = AIHooks(provider="none").sanitize_for_llm(
            "This sentence mentions system: in the middle"
        )
        assert "system:" in result


class TestPhoneExtraction:
    def _phones(self, text):
        result = asyncio.run(
            AIHooks(provider="none").extract_structured_data(text, {})
        )
        return result["data"]["phones"]

    def test_punctuation_runs_rejected(self):
        assert self._phones("separator ---------- end") == []
        assert self._phones("range (---) --- ---- done") == []

    def test_real_formats_accepted(self):
        phones = self._phones(
            "Call +1 (555) 123-4567 or (555) 987-6543 or 555 111 2222 today"
        )
        digits = [re.sub(r"\D", "", phone) for phone in phones]
        assert "15551234567" in digits
        assert "5559876543" in digits
        assert "5551112222" in digits
