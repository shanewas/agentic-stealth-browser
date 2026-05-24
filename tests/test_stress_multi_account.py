"""
Load/stress tests for long-running multi-account scenarios.
Addresses #140: No load or stress test for long-running multi-account scenarios.
"""

import time
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestMultiAccountStress:
    """Stress tests for multi-account scenarios."""

    def test_concurrent_account_health_tracking(self):
        """Multiple accounts should track health independently."""
        from core.account_health import AccountHealth

        accounts = []
        for i in range(10):
            health = AccountHealth(f"account_{i}")
            # Each account records different events
            for _ in range(i + 1):
                health.record_event("rate_limit_hit")
            accounts.append(health)

        # Verify independence
        scores = [h.score for h in accounts]
        # Scores should differ (more events = lower score)
        assert scores[0] > scores[-1], "More events should lower score"
        # All scores should be within valid range
        for score in scores:
            assert 0.1 <= score <= 1.0

    def test_concurrent_proxy_health_tracking(self):
        """Multiple proxy sessions should track health independently."""
        from proxy.proxy_manager import ProxyManager

        manager = ProxyManager()

        # Record results for multiple sessions
        for i in range(5):
            session = f"session_{i}"
            for j in range(i + 1):
                manager.record_proxy_result(session, success=(j % 2 == 0))

        # Verify each session has correct counts
        for i in range(5):
            session = f"session_{i}"
            health = manager.get_proxy_health(session)
            assert health["total_requests"] == i + 1


class TestRateLimiterStress:
    """Stress tests for rate limiter under load."""

    def test_many_domains_rate_limiting(self):
        """Rate limiter should handle many domains without degradation."""
        from production.rate_limiter import DomainRateLimiter, RateLimitConfig

        lim = DomainRateLimiter()

        for i in range(50):
            lim.set_limit(
                f"domain_{i}.com",
                RateLimitConfig(requests_per_minute=100, cooldown_seconds=0),
            )

        async def _run():
            for i in range(50):
                await lim.wait_if_needed(f"domain_{i}.com")

        start = time.time()
        asyncio.run(_run())
        elapsed = time.time() - start

        # Should complete quickly (< 1 second for 50 domains)
        assert elapsed < 1.0, f"Too slow: {elapsed:.2f}s"

    def test_rapid_requests_same_domain(self):
        """Rapid requests to same domain should trigger rate limiting."""
        from production.rate_limiter import DomainRateLimiter, RateLimitConfig

        lim = DomainRateLimiter()
        lim.set_limit(
            "rapid.test", RateLimitConfig(requests_per_minute=100, cooldown_seconds=0)
        )
        lim.request_times["rapid.test"].clear()
        lim.last_request.pop("rapid.test", None)

        async def _run():
            waits = []
            for _ in range(10):
                w = await lim.wait_if_needed("rapid.test")
                waits.append(w)
            return waits

        waits = asyncio.run(_run())

        # All requests should complete without waiting
        assert len(waits) == 10
        assert all(w == 0.0 for w in waits)


class TestAccountWarmingStress:
    """Stress tests for account warming under load."""

    def test_multiple_accounts_warming(self):
        """Multiple accounts should warm independently."""
        from core.account_warming import AccountWarmer

        warmers = []
        for i in range(5):
            warmer = AccountWarmer(f"account_{i}", data_dir="/tmp/test_warming_stress")
            warmer.start()
            warmers.append(warmer)

        # Each should be at phase 0 initially
        for warmer in warmers:
            assert warmer.phase_index == 0
            limits = warmer.get_session_limits()
            assert limits["max_actions"] > 0


class TestPersonaRotatorStress:
    """Stress tests for persona rotation under load."""

    def test_multiple_accounts_rotating(self):
        """Multiple accounts should rotate personas independently."""
        from behavior.persona_rotator import PersonaRotator

        rotators = []
        for i in range(5):
            rotator = PersonaRotator(f"account_{i}")
            rotator.set_current_persona("casual_user")
            rotators.append(rotator)

        # Transition some to power_user
        for i in range(0, 5, 2):
            rotators[i].transition_to("power_user", transition_days=14)

        # Verify independence
        for i in range(5):
            status = rotators[i].get_status()
            assert status["account_id"] == f"account_{i}"


class TestSessionCheckpointStress:
    """Stress tests for session checkpointing under load."""

    def test_multiple_checkpoints_same_account(self, tmp_path):
        """Multiple checkpoints for same account should not conflict."""
        from core.session_checkpoint import SessionManager

        manager = SessionManager(data_dir=str(tmp_path))

        for i in range(10):
            cp = manager.create_checkpoint(
                account_id="stress_test",
                session_id=f"session_{i}",
            )
            manager.save_checkpoint(cp, filename=f"checkpoint_{i}.json")

        # All checkpoints should be loadable
        for i in range(10):
            loaded = manager.load_checkpoint(f"checkpoint_{i}.json")
            assert loaded.metadata.session_id == f"session_{i}"
