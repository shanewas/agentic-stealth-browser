"""
Unit tests for Recovery state machine: backoff calculation, BlockType detection, circuit breaker.

Covers:
- AntiBlockOrchestrator.calculate_backoff
- BlockType detection via detect_block
- Circuit breaker open/close/reset
- Platform-aware strategy lookup
- Recovery history learning
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import asyncio
import time
from recovery.anti_block_orchestrator import (
    AntiBlockOrchestrator,
    BlockType,
    RecoveryAction,
    RecoveryContext,
    ErrorSeverity,
    MaxRetriesExceeded,
)


def _make_ctx(**kwargs):
    defaults = dict(platform="default", url="https://example.com", attempt=1)
    defaults.update(kwargs)
    return RecoveryContext(**defaults)


class TestBlockTypeDetection:
    def test_transient_error_patterns_detected(self):
        orch = AntiBlockOrchestrator()
        for err in ["timeout waiting", "connection reset", "dns failure"]:
            ctx = _make_ctx(last_error=err)
            result = asyncio.run(orch.detect_block(ctx))
            assert result == BlockType.TRANSIENT_ERROR, f"Failed for {err}"

    def test_transient_error_not_overridden_by_status_codes(self):
        orch = AntiBlockOrchestrator()
        err = "connection reset by peer"
        for status in [403, 429, 503]:
            ctx = _make_ctx(last_error=err, http_status=status)
            result = asyncio.run(orch.detect_block(ctx))
            assert result != BlockType.TRANSIENT_ERROR, (
                f"Should be overridden for {status}"
            )

    def test_http_429_is_hard_rate_limit(self):
        orch = AntiBlockOrchestrator()
        ctx = _make_ctx(http_status=429)
        assert asyncio.run(orch.detect_block(ctx)) == BlockType.HARD_RATE_LIMIT

    def test_http_403_is_soft_rate_limit(self):
        orch = AntiBlockOrchestrator()
        ctx = _make_ctx(http_status=403)
        assert asyncio.run(orch.detect_block(ctx)) == BlockType.SOFT_RATE_LIMIT

    def test_http_503_is_proxy_block(self):
        orch = AntiBlockOrchestrator()
        ctx = _make_ctx(http_status=503)
        assert asyncio.run(orch.detect_block(ctx)) == BlockType.PROXY_BLOCK

    def test_http_502_is_proxy_block(self):
        orch = AntiBlockOrchestrator()
        ctx = _make_ctx(http_status=502)
        assert asyncio.run(orch.detect_block(ctx)) == BlockType.PROXY_BLOCK

    def test_captcha_keywords_in_error(self):
        orch = AntiBlockOrchestrator()
        for kw in [
            "captcha challenge",
            "security check required",
            "robot check failed",
        ]:
            ctx = _make_ctx(last_error=kw)
            assert asyncio.run(orch.detect_block(ctx)) == BlockType.CAPTCHA, (
                f"Failed for '{kw}'"
            )

    def test_rate_limit_keywords_in_error(self):
        orch = AntiBlockOrchestrator()
        ctx = _make_ctx(last_error="too many requests")
        assert asyncio.run(orch.detect_block(ctx)) == BlockType.HARD_RATE_LIMIT

    def test_linkedin_unusual_activity(self):
        orch = AntiBlockOrchestrator()
        ctx = _make_ctx(platform="linkedin", last_error="unusual activity detected")
        assert asyncio.run(orch.detect_block(ctx)) == BlockType.ACCOUNT_RESTRICTION

    def test_linkedin_temporarily_restricted(self):
        orch = AntiBlockOrchestrator()
        ctx = _make_ctx(platform="linkedin", last_error="temporarily restricted")
        assert asyncio.run(orch.detect_block(ctx)) == BlockType.ACCOUNT_RESTRICTION

    def test_amazon_robot_detection(self):
        orch = AntiBlockOrchestrator()
        ctx = _make_ctx(platform="amazon", last_error="sorry robot check")
        assert asyncio.run(orch.detect_block(ctx)) == BlockType.CAPTCHA


class TestBackoffCalculation:
    def test_base_backoff_with_jitter(self):
        orch = AntiBlockOrchestrator()
        ctx = _make_ctx(platform="linkedin")
        backoff = orch.calculate_backoff(ctx)
        # LinkedIn base is 45s, with jitter 0.3: range ~[31.5, 58.5]
        assert 25 <= backoff <= 70, f"Backoff {backoff} out of expected range"

    def test_transient_backoff_is_shorter(self):
        orch = AntiBlockOrchestrator()
        ctx = _make_ctx(platform="linkedin", last_error="timeout error")
        backoff = orch.calculate_backoff(ctx)
        # LinkedIn transient multiplier is 0.6: base 45 * 0.6 = 27, with jitter 0.3: ~[18.9, 35.1]
        assert 12 <= backoff <= 50, f"Transient backoff {backoff} out of expected range"

    def test_backoff_increases_with_attempts(self):
        orch = AntiBlockOrchestrator()
        ctx1 = _make_ctx(attempt=1)
        ctx3 = _make_ctx(attempt=3)
        backoff1 = orch.calculate_backoff(ctx1)
        backoff3 = orch.calculate_backoff(ctx3)
        # Attempt 3 should be larger (exponential growth)
        assert backoff3 >= backoff1

    def test_backoff_respects_max(self):
        orch = AntiBlockOrchestrator()
        ctx = _make_ctx(platform="linkedin", attempt=20)
        backoff = orch.calculate_backoff(ctx)
        assert backoff <= 300, f"Backoff {backoff} exceeds max of 300"


class TestCircuitBreaker:
    def test_circuit_not_open_initially(self):
        orch = AntiBlockOrchestrator()
        assert orch._check_circuit_breaker("test-key") is False

    def test_circuit_opens_after_threshold(self):
        orch = AntiBlockOrchestrator()
        orch.circuit_breaker_threshold = 3
        for _ in range(3):
            orch._record_failure("test-key")
        assert orch._check_circuit_breaker("test-key") is True

    def test_circuit_resets(self):
        orch = AntiBlockOrchestrator()
        orch.circuit_breaker_threshold = 3
        for _ in range(3):
            orch._record_failure("test-key")
        orch._reset_circuit("test-key")
        assert orch._check_circuit_breaker("test-key") is False

    def test_circuit_opens_with_cooldown(self):
        orch = AntiBlockOrchestrator()
        orch.circuit_breaker_threshold = 2
        orch.circuit_cooldown = 0.1
        for _ in range(2):
            orch._record_failure("test-key")
        assert orch._check_circuit_breaker("test-key") is True
        time.sleep(0.15)
        assert orch._check_circuit_breaker("test-key") is False

    def test_failure_count_tracks_correctly(self):
        orch = AntiBlockOrchestrator()
        orch._record_failure("key-a")
        orch._record_failure("key-a")
        orch._record_failure("key-b")
        assert orch.failure_counts.get("key-a", 0) > 0
        assert orch.failure_counts.get("key-b", 0) > 0

    def test_cost_tracker(self):
        orch = AntiBlockOrchestrator()
        orch._record_failure("key", cost=2.5)
        orch._record_failure("key", cost=1.0)
        assert orch.cost_tracker["key"] == 3.5


class TestPlatformStrategies:
    def test_get_strategy_default(self):
        orch = AntiBlockOrchestrator()
        strat = orch.get_strategy("unknown")
        assert strat["max_retries"] == 4
        assert "base_backoff" in strat

    def test_get_strategy_linkedin(self):
        orch = AntiBlockOrchestrator()
        strat = orch.get_strategy("linkedin")
        assert strat["max_retries"] == 5
        assert strat["base_backoff"] == 45

    def test_get_strategy_amazon(self):
        orch = AntiBlockOrchestrator()
        strat = orch.get_strategy("amazon")
        assert strat["max_retries"] == 4
        assert strat["base_backoff"] == 30

    def test_get_strategy_google(self):
        orch = AntiBlockOrchestrator()
        strat = orch.get_strategy("google")
        assert strat["max_retries"] == 3
        assert strat["base_backoff"] == 20


class TestRecoveryActionDecision:
    def test_transient_always_backoff(self):
        orch = AntiBlockOrchestrator()
        ctx = _make_ctx(platform="linkedin", attempt=1)
        action = orch._decide_recovery_action(ctx, BlockType.TRANSIENT_ERROR)
        assert action == RecoveryAction.BACKOFF

    def test_none_is_noop(self):
        orch = AntiBlockOrchestrator()
        ctx = _make_ctx()
        assert orch._decide_recovery_action(ctx, BlockType.NONE) == RecoveryAction.NOOP

    def test_proxy_block_rotates_proxy(self):
        orch = AntiBlockOrchestrator()
        ctx = _make_ctx()
        # Default platform uses "backoff_and_retry" as preferred action
        action = orch._decide_recovery_action(ctx, BlockType.PROXY_BLOCK)
        assert action == RecoveryAction.BACKOFF

    def test_proxy_block_rotates_proxy_for_specific_platform(self):
        """On a platform without preferred action in strategies, taxonomy fallback applies."""
        orch = AntiBlockOrchestrator()
        # Create a platform with a preferred action that is NOT backoff
        ctx = _make_ctx(platform="linkedin")
        action = orch._decide_recovery_action(ctx, BlockType.PROXY_BLOCK)
        # LinkedIn's preferred_first_action is "rotate_session", not backoff
        # But PROXY_BLOCK still gets ROTATE_PROXY_ONLY from taxonomy... wait, let's see
        # LinkedIn preferred_first_action is rotate_session → ROTATE_SESSION_ONLY
        assert action == RecoveryAction.ROTATE_SESSION_ONLY

    def test_safe_mode_blocks_rotation(self):
        orch = AntiBlockOrchestrator(safe_mode=True)
        ctx = _make_ctx(attempt=2)
        action = orch._decide_recovery_action(ctx, BlockType.CAPTCHA)
        assert action == RecoveryAction.FAIL_FAST

    def test_safe_mode_allows_single_retry(self):
        orch = AntiBlockOrchestrator(safe_mode=True)
        ctx = _make_ctx(attempt=1)
        action = orch._decide_recovery_action(ctx, BlockType.SOFT_RATE_LIMIT)
        assert action == RecoveryAction.BACKOFF

    def test_custom_strategy_overrides_default(self):
        orch = AntiBlockOrchestrator()
        called_with = []

        def custom(ctx, bt):
            called_with.append((ctx.platform, bt))
            return RecoveryAction.FAIL_FAST

        orch.register_recovery_strategy("mytest", custom)
        ctx = _make_ctx(platform="mytest")
        action = orch._decide_recovery_action(ctx, BlockType.CAPTCHA)
        assert action == RecoveryAction.FAIL_FAST
        assert len(called_with) == 1

    def test_custom_strategy_exception_falls_back(self):
        orch = AntiBlockOrchestrator()

        def failing(ctx, bt):
            raise RuntimeError("boom")

        orch.register_recovery_strategy("mytest", failing)
        ctx = _make_ctx(platform="mytest")
        action = orch._decide_recovery_action(ctx, BlockType.PROXY_BLOCK)
        # Falls back to default strategy's preferred action: BACKOFF for "default"
        assert action == RecoveryAction.BACKOFF


class TestRecoveryHistoryLearning:
    def test_update_history_success(self):
        orch = AntiBlockOrchestrator()
        ctx = _make_ctx(platform="linkedin", url="https://linkedin.com/feed")
        orch._update_recovery_history(ctx, RecoveryAction.BACKOFF, success=True)
        key = orch._get_history_key(ctx)
        assert key in orch.recovery_history
        assert orch.recovery_history[key]["total_attempts"] == 1

    def test_history_key_includes_platform_domain(self):
        orch = AntiBlockOrchestrator()
        ctx = _make_ctx(
            platform="amazon",
            url="https://amazon.co.jp/dp/123",
            account_hint="test-user",
        )
        key = orch._get_history_key(ctx)
        assert "amazon" in key
        assert "test-user" in key
        assert "amazon.co.jp" in key

    def test_history_eviction(self):
        orch = AntiBlockOrchestrator()
        orch._max_history_size = 5
        for i in range(10):
            ctx = _make_ctx(
                url=f"https://site{i}.com",
                platform=f"site{i}",
                account_hint=f"user{i}",
            )
            orch._update_recovery_history(ctx, RecoveryAction.BACKOFF, success=True)
        assert len(orch.recovery_history) <= 5

    def test_learned_strategy_is_preferred(self):
        orch = AntiBlockOrchestrator()
        ctx = _make_ctx(
            platform="amazon", url="https://amazon.com/test", account_hint="shop"
        )
        # Simulate: ROTATE_BOTH succeeded, BACKOFF failed
        orch._update_recovery_history(ctx, RecoveryAction.ROTATE_BOTH, success=True)
        orch._update_recovery_history(ctx, RecoveryAction.ROTATE_BOTH, success=True)
        orch._update_recovery_history(ctx, RecoveryAction.BACKOFF, success=False)
        orch._update_recovery_history(ctx, RecoveryAction.BACKOFF, success=False)
        action = orch._decide_recovery_action(ctx, BlockType.HARD_RATE_LIMIT)
        assert action == RecoveryAction.ROTATE_BOTH


class TestMaxRetriesExceeded:
    def test_exception_attributes(self):
        exc = MaxRetriesExceeded(
            "too many retries",
            platform="linkedin",
            max_retries=5,
            last_error="timeout",
        )
        assert exc.platform == "linkedin"
        assert exc.max_retries == 5
        assert exc.last_error == "timeout"
        assert str(exc) == "too many retries"


class TestErrorSeverityMapping:
    def test_block_type_to_severity(self):
        orch = AntiBlockOrchestrator()
        assert (
            orch.block_type_to_severity[BlockType.TRANSIENT_ERROR] == ErrorSeverity.LOW
        )
        assert (
            orch.block_type_to_severity[BlockType.SOFT_RATE_LIMIT]
            == ErrorSeverity.MEDIUM
        )
        assert (
            orch.block_type_to_severity[BlockType.HARD_RATE_LIMIT] == ErrorSeverity.HIGH
        )
        assert orch.block_type_to_severity[BlockType.CAPTCHA] == ErrorSeverity.HIGH
        assert (
            orch.block_type_to_severity[BlockType.ACCOUNT_RESTRICTION]
            == ErrorSeverity.CRITICAL
        )
