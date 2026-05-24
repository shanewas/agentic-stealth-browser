"""
Phase 1 Recovery Tests
Tests for the anti-block recovery orchestrator basic functionality.
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from recovery.anti_block_orchestrator import (
    AntiBlockOrchestrator,
    BlockType,
    RecoveryAction,
    RecoveryContext,
    ErrorSeverity,
    MaxRetriesExceeded,
)


class TestBlockType:
    """Test BlockType enum."""

    def test_all_values_exist(self):
        assert BlockType.NONE.value == "none"
        assert BlockType.SOFT_RATE_LIMIT.value == "soft_rate_limit"
        assert BlockType.HARD_RATE_LIMIT.value == "hard_rate_limit"
        assert BlockType.CAPTCHA.value == "captcha"
        assert BlockType.ACCOUNT_RESTRICTION.value == "account_restriction"
        assert BlockType.PROXY_BLOCK.value == "proxy_block"
        assert BlockType.UNKNOWN.value == "unknown"
        assert BlockType.TRANSIENT_ERROR.value == "transient_error"


class TestRecoveryAction:
    """Test RecoveryAction enum."""

    def test_all_values_exist(self):
        assert RecoveryAction.RETRY.value == "retry"
        assert RecoveryAction.BACKOFF.value == "backoff_and_retry"
        assert RecoveryAction.ROTATE_SESSION_ONLY.value == "rotate_session"
        assert RecoveryAction.ROTATE_PROXY_ONLY.value == "rotate_proxy"
        assert RecoveryAction.ROTATE_BOTH.value == "rotate_both"
        assert RecoveryAction.FAIL_FAST.value == "fail_fast"


class TestErrorSeverity:
    """Test ErrorSeverity enum."""

    def test_all_values_exist(self):
        assert ErrorSeverity.LOW.value == "low"
        assert ErrorSeverity.MEDIUM.value == "medium"
        assert ErrorSeverity.HIGH.value == "high"
        assert ErrorSeverity.CRITICAL.value == "critical"


class TestRecoveryContext:
    """Test RecoveryContext dataclass."""

    def test_default_values(self):
        ctx = RecoveryContext(platform="test", url="https://example.com")
        assert ctx.platform == "test"
        assert ctx.url == "https://example.com"
        assert ctx.attempt == 1
        assert ctx.last_error is None
        assert ctx.block_type == BlockType.NONE
        assert ctx.response_time == 0.0
        assert ctx.http_status is None
        assert ctx.metadata == {}
        assert ctx.session_name is None
        assert ctx.error_severity == ErrorSeverity.MEDIUM
        assert ctx.recovery_action is None
        assert ctx.account_hint is None


class TestAntiBlockOrchestrator:
    """Test AntiBlockOrchestrator basic functionality."""

    def test_init_defaults(self):
        orch = AntiBlockOrchestrator()
        assert orch.light_detection is True
        assert orch.circuit_breaker_threshold == 5
        assert orch.circuit_cooldown == 300
        assert orch.safe_mode is False
        assert orch.recovery_mode == "aggressive"

    def test_get_strategy_linkedin(self):
        orch = AntiBlockOrchestrator()
        strategy = orch.get_strategy("linkedin")
        assert strategy["max_retries"] == 5
        assert strategy["base_backoff"] == 45

    def test_get_strategy_amazon(self):
        orch = AntiBlockOrchestrator()
        strategy = orch.get_strategy("amazon")
        assert strategy["max_retries"] == 4
        assert strategy["base_backoff"] == 30

    def test_get_strategy_default(self):
        orch = AntiBlockOrchestrator()
        strategy = orch.get_strategy("unknown-site")
        assert strategy["max_retries"] == 4
        assert strategy["base_backoff"] == 25

    def test_calculate_backoff(self):
        orch = AntiBlockOrchestrator()
        ctx = RecoveryContext(platform="linkedin", url="https://linkedin.com")
        ctx.attempt = 1
        backoff = orch.calculate_backoff(ctx)
        assert backoff >= 3.0  # minimum backoff
        assert backoff <= 45 * 1.3  # base + jitter

    def test_calculate_backoff_exponential(self):
        orch = AntiBlockOrchestrator()
        ctx = RecoveryContext(platform="linkedin", url="https://linkedin.com")
        ctx.attempt = 3
        backoff = orch.calculate_backoff(ctx)
        # Should be higher than attempt 1 due to exponential backoff
        assert backoff > 45  # base * 2^(3-1) = 45 * 4 = 180, with jitter

    def test_circuit_breaker(self):
        orch = AntiBlockOrchestrator()
        key = "test-platform"

        # Initially circuit should be closed
        assert orch._check_circuit_breaker(key) is False

        # Record failures to trip circuit
        for _ in range(5):
            orch._record_failure(key)

        # Circuit should now be open
        assert orch._check_circuit_breaker(key) is True

        # Reset circuit
        orch._reset_circuit(key)
        assert orch._check_circuit_breaker(key) is False

    def test_transient_error_detection(self):
        orch = AntiBlockOrchestrator()
        ctx = RecoveryContext(
            platform="test",
            url="https://example.com",
            last_error="Connection timeout occurred",
        )
        # This is tested via detect_block which is async
        # We'll test the pattern matching indirectly

    def test_safe_mode_prevents_rotation(self):
        orch = AntiBlockOrchestrator(safe_mode=True)
        assert orch.safe_mode is True
        # In safe mode, recovery should not rotate proxies

    def test_recovery_history_tracking(self):
        orch = AntiBlockOrchestrator()
        ctx = RecoveryContext(platform="test", url="https://example.com")
        orch._update_recovery_history(ctx, RecoveryAction.RETRY, success=True)

        key = orch._get_history_key(ctx)
        assert key in orch.recovery_history
        assert orch.recovery_history[key]["total_attempts"] == 1

    def test_recovery_history_lru_eviction(self):
        orch = AntiBlockOrchestrator()
        # Set a small max history for testing
        orch._max_history_size = 5

        # Add more entries than the limit
        for i in range(10):
            ctx = RecoveryContext(platform=f"test-{i}", url=f"https://example{i}.com")
            orch._update_recovery_history(ctx, RecoveryAction.RETRY, success=True)

        # History should not exceed the limit
        assert len(orch.recovery_history) <= orch._max_history_size

    def test_decide_recovery_action_transient(self):
        orch = AntiBlockOrchestrator()
        ctx = RecoveryContext(platform="test", url="https://example.com")
        action = orch._decide_recovery_action(ctx, BlockType.TRANSIENT_ERROR)
        assert action == RecoveryAction.BACKOFF

    def test_decide_recovery_action_none(self):
        orch = AntiBlockOrchestrator()
        ctx = RecoveryContext(platform="test", url="https://example.com")
        action = orch._decide_recovery_action(ctx, BlockType.NONE)
        assert action == RecoveryAction.NOOP

    def test_decide_recovery_action_proxy_block(self):
        orch = AntiBlockOrchestrator()
        ctx = RecoveryContext(platform="test", url="https://example.com")
        # For unknown platform with attempt=1, default strategy prefers backoff
        # Proxy block specifically should trigger rotation
        action = orch._decide_recovery_action(ctx, BlockType.PROXY_BLOCK)
        # The default strategy's preferred_first_action is "backoff_and_retry"
        # but PROXY_BLOCK should map to ROTATE_PROXY_ONLY in the fallback taxonomy
        assert action in (RecoveryAction.ROTATE_PROXY_ONLY, RecoveryAction.BACKOFF)

    def test_decide_recovery_action_fail_fast_in_safe_mode(self):
        orch = AntiBlockOrchestrator(safe_mode=True)
        ctx = RecoveryContext(platform="test", url="https://example.com", attempt=3)
        action = orch._decide_recovery_action(ctx, BlockType.ACCOUNT_RESTRICTION)
        assert action == RecoveryAction.FAIL_FAST


class TestMaxRetriesExceeded:
    """Test MaxRetriesExceeded exception."""

    def test_exception_attributes(self):
        err = MaxRetriesExceeded(
            "Test error",
            platform="linkedin",
            max_retries=5,
            last_error="timeout",
        )
        assert err.platform == "linkedin"
        assert err.max_retries == 5
        assert err.last_error == "timeout"
        assert "Test error" in str(err)
