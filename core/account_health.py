"""
Account Health Scoring & Automatic Cooling Off
Addresses #154: Support for "account health" scoring and automatic cooling off.

Tracks risk factors from browser activity and provides:
- Health score (0.0-1.0, higher = healthier)
- Automatic cooling off periods when score drops
- Gradual recovery after cooling off
- Risk event logging for audit
"""

import time
import math
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from enum import Enum


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class RiskEvent:
    """A recorded risk event."""

    event_type: str
    severity: float  # 0.0-1.0
    timestamp: float
    details: Optional[Dict[str, Any]] = None
    decay_hours: float = 24.0  # How long until this event's impact decays


@dataclass
class HealthState:
    """Current health state of an account."""

    score: float = 1.0  # 0.0-1.0
    risk_level: RiskLevel = RiskLevel.LOW
    cooling_off: bool = False
    cooling_off_until: float = 0.0
    events_24h: int = 0
    last_activity: float = 0.0
    total_actions: int = 0


class AccountHealth:
    """Tracks account health and manages cooling off periods.

    Usage:
        health = AccountHealth(account_id="user123")
        health.record_event("rate_limit_hit", severity=0.3)
        if health.should_cool_off():
            wait = health.cooling_off_duration()
            time.sleep(wait)
        health.record_action()
    """

    # Thresholds
    COOLING_OFF_THRESHOLD = 0.4  # Score below this triggers cooling off
    MINIMUM_SCORE = 0.1  # Score never goes below this
    RECOVERY_RATE = 0.02  # Score recovery per minute during cooling off
    BASE_COOLING_DURATION = 300  # 5 minutes base cooling off
    MAX_COOLING_DURATION = 3600  # 1 hour max cooling off

    # Risk event weights
    RISK_EVENTS = {
        "rate_limit_hit": 0.25,
        "captcha_detected": 0.35,
        "block_detected": 0.40,
        "ip_change": 0.15,
        "fingerprint_mismatch": 0.30,
        "session_expired": 0.10,
        "login_failure": 0.20,
        "suspicious_redirect": 0.25,
        "consent_wall": 0.05,
        "slow_response": 0.05,
    }

    def __init__(self, account_id: str = "default", logger: Optional[Any] = None):
        self.account_id = account_id
        self._logger = logger
        self._events: List[RiskEvent] = []
        self._state = HealthState(last_activity=time.time())
        self._cooling_off_count = 0

    @property
    def score(self) -> float:
        """Current health score (0.0-1.0)."""
        self._recalculate()
        return self._state.score

    @property
    def risk_level(self) -> RiskLevel:
        """Current risk level."""
        self._recalculate()
        return self._state.risk_level

    @property
    def is_cooling_off(self) -> bool:
        """Whether account is currently in cooling off period."""
        if not self._state.cooling_off:
            return False
        if time.time() >= self._state.cooling_off_until:
            self._state.cooling_off = False
            return False
        return True

    @property
    def cooling_off_remaining(self) -> float:
        """Seconds remaining in cooling off period (0 if not cooling off)."""
        if not self.is_cooling_off:
            return 0.0
        return max(0.0, self._state.cooling_off_until - time.time())

    def record_event(
        self,
        event_type: str,
        severity: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
        decay_hours: float = 24.0,
    ):
        """Record a risk event."""
        if severity is None:
            severity = self.RISK_EVENTS.get(event_type, 0.1)

        event = RiskEvent(
            event_type=event_type,
            severity=severity,
            timestamp=time.time(),
            details=details,
            decay_hours=decay_hours,
        )
        self._events.append(event)
        self._log(f"Risk event: {event_type} (severity={severity:.2f})")

    def record_action(self):
        """Record a successful action (slightly improves health)."""
        self._state.total_actions += 1
        self._state.last_activity = time.time()

    def record_success(self, count: int = 1):
        """Record successful actions (improves health slightly)."""
        for _ in range(count):
            self.record_action()
        # Small health boost for sustained success
        self._state.score = min(1.0, self._state.score + 0.01 * count)

    def should_cool_off(self) -> bool:
        """Check if account should enter cooling off period."""
        self._recalculate()
        if self.is_cooling_off:
            return True
        return self._state.score < self.COOLING_OFF_THRESHOLD

    def start_cooling_off(self):
        """Start cooling off period."""
        self._state.cooling_off = True
        self._cooling_off_count += 1
        # Duration increases with repeated cooling offs
        duration = min(
            self.MAX_COOLING_DURATION,
            self.BASE_COOLING_DURATION * (1.5 ** (self._cooling_off_count - 1)),
        )
        self._state.cooling_off_until = time.time() + duration
        self._log(
            f"Cooling off started for {duration:.0f}s (count={self._cooling_off_count})"
        )

    def cooling_off_duration(self) -> float:
        """Get recommended cooling off duration in seconds."""
        self._recalculate()
        if self._state.score >= 0.6:
            return self.BASE_COOLING_DURATION * 0.5
        elif self._state.score >= 0.4:
            return self.BASE_COOLING_DURATION
        elif self._state.score >= 0.2:
            return self.BASE_COOLING_DURATION * 2
        else:
            return self.MAX_COOLING_DURATION

    def get_recommended_delay(self) -> float:
        """Get recommended delay between actions based on health."""
        self._recalculate()
        if self._state.score >= 0.8:
            return 0.0  # No extra delay
        elif self._state.score >= 0.6:
            return 1.0  # 1 second extra
        elif self._state.score >= 0.4:
            return 3.0  # 3 seconds extra
        elif self._state.score >= 0.2:
            return 10.0  # 10 seconds extra
        else:
            return 30.0  # 30 seconds extra

    def get_state(self) -> HealthState:
        """Get current health state."""
        self._recalculate()
        return self._state

    def get_events(self, hours: float = 24.0) -> List[RiskEvent]:
        """Get risk events from the last N hours."""
        cutoff = time.time() - (hours * 3600)
        return [e for e in self._events if e.timestamp >= cutoff]

    def reset(self):
        """Reset health state (use with caution)."""
        self._events.clear()
        self._state = HealthState(last_activity=time.time())
        self._cooling_off_count = 0
        self._log("Health state reset")

    def _recalculate(self):
        """Recalculate health score based on recent events."""
        now = time.time()
        cutoff_24h = now - (24 * 3600)

        # Filter recent events
        recent_events = [e for e in self._events if e.timestamp >= cutoff_24h]
        self._state.events_24h = len(recent_events)

        # Calculate score decay from events
        decay = 0.0
        for event in recent_events:
            # Events decay over time
            age_hours = (now - event.timestamp) / 3600
            time_factor = math.exp(-age_hours / event.decay_hours)
            decay += event.severity * time_factor

        # Base score starts at 1.0, reduced by decay
        raw_score = max(self.MINIMUM_SCORE, 1.0 - decay)

        # Recovery during cooling off
        if self._state.cooling_off and not self.is_cooling_off:
            # Just finished cooling off, apply recovery
            recovery = (
                self.RECOVERY_RATE * (self._state.cooling_off_until - (now - 300)) / 60
            )
            raw_score = min(1.0, raw_score + max(0, recovery))

        # Gradual passive recovery (0.001 per minute since last event)
        if recent_events:
            last_event_time = max(e.timestamp for e in recent_events)
            minutes_since = (now - last_event_time) / 60
            passive_recovery = min(0.1, minutes_since * 0.001)
            raw_score = min(1.0, raw_score + passive_recovery)

        self._state.score = raw_score

        # Update risk level
        if raw_score >= 0.8:
            self._state.risk_level = RiskLevel.LOW
        elif raw_score >= 0.6:
            self._state.risk_level = RiskLevel.MEDIUM
        elif raw_score >= 0.3:
            self._state.risk_level = RiskLevel.HIGH
        else:
            self._state.risk_level = RiskLevel.CRITICAL

        # Auto-start cooling off if score drops below threshold
        if raw_score < self.COOLING_OFF_THRESHOLD and not self._state.cooling_off:
            self.start_cooling_off()

    def _log(self, msg: str):
        """Log a message."""
        if self._logger and hasattr(self._logger, "log_action"):
            self._logger.log_action(
                "account_health",
                {
                    "account_id": self.account_id,
                    "message": msg,
                    "score": self._state.score,
                },
                level="info",
            )
        else:
            print(
                f"[AccountHealth:{self.account_id}] {msg} (score={self._state.score:.2f})"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize health state for checkpointing."""
        return {
            "account_id": self.account_id,
            "score": self._state.score,
            "risk_level": self._state.risk_level.value,
            "cooling_off": self._state.cooling_off,
            "cooling_off_until": self._state.cooling_off_until,
            "events_24h": self._state.events_24h,
            "total_actions": self._state.total_actions,
            "cooling_off_count": self._cooling_off_count,
            "events": [
                {
                    "event_type": e.event_type,
                    "severity": e.severity,
                    "timestamp": e.timestamp,
                    "decay_hours": e.decay_hours,
                }
                for e in self._events[-50:]  # Keep last 50 events
            ],
        }

    @classmethod
    def from_dict(
        cls, data: Dict[str, Any], logger: Optional[Any] = None
    ) -> "AccountHealth":
        """Deserialize health state from checkpoint."""
        health = cls(account_id=data["account_id"], logger=logger)
        health._state.score = data.get("score", 1.0)
        health._state.risk_level = RiskLevel(data.get("risk_level", "low"))
        health._state.cooling_off = data.get("cooling_off", False)
        health._state.cooling_off_until = data.get("cooling_off_until", 0.0)
        health._state.events_24h = data.get("events_24h", 0)
        health._state.total_actions = data.get("total_actions", 0)
        health._cooling_off_count = data.get("cooling_off_count", 0)

        for e_data in data.get("events", []):
            health._events.append(
                RiskEvent(
                    event_type=e_data["event_type"],
                    severity=e_data["severity"],
                    timestamp=e_data["timestamp"],
                    decay_hours=e_data.get("decay_hours", 24.0),
                )
            )

        return health
