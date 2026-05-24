"""
Adaptive/ML-driven behavior tuning based on block detection feedback.
Addresses #71: Add adaptive / ML-driven behavior tuning based on block detection feedback.

Uses historical block data to adjust behavior parameters automatically.
v1.8.0 adds:
  - FeedbackStore for persistent telemetry
  - Domain-specific tuning profiles
  - Enhanced replay/recovery event ingestion
"""

import json
import os
import time
import random
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field


@dataclass
class BehaviorFeedback:
    """A single feedback event from a browsing session."""
    timestamp: float
    blocked: bool
    block_type: str = "none"
    platform: str = "unknown"
    domain: str = ""
    behavior_params: Optional[Dict[str, float]] = None
    response_time: float = 0.0
    recovery_attempts: int = 0
    selector_success: Dict[str, float] = field(default_factory=dict)
    stealth_events: List[Dict[str, Any]] = field(default_factory=list)


class FeedbackStore:
    """Persistent telemetry store for replay/recovery events.

    Tracks selector success rates per domain and stealth detection events
    to accumulate learning across sessions.
    """

    def __init__(self, store_path: Optional[str] = None):
        self._store_path = Path(store_path or os.getenv(
            "STEALTH_FEEDBACK_STORE",
            str(Path.home() / ".agentic-browser" / "feedback_store.json"),
        ))
        self._events: List[Dict[str, Any]] = []
        self._selector_stats: Dict[str, Dict[str, Dict[str, float]]] = {}
        self._stealth_detections: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if self._store_path.exists():
            try:
                data = json.loads(self._store_path.read_text())
                self._events = data.get("events", [])
                self._selector_stats = data.get("selector_stats", {})
                self._stealth_detections = data.get("stealth_detections", [])
            except Exception:
                pass

    def _save(self) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        self._store_path.write_text(json.dumps({
            "events": self._events[-1000:],
            "selector_stats": self._selector_stats,
            "stealth_detections": self._stealth_detections[-500:],
        }, default=str, indent=2))

    def record_event(self, event_type: str, domain: str, details: Dict[str, Any]) -> None:
        self._events.append({
            "timestamp": time.time(),
            "type": event_type,
            "domain": domain,
            "details": details,
        })
        if len(self._events) > 2000:
            self._events = self._events[-1000:]
        self._save()

    def record_selector_result(self, domain: str, selector: str, success: bool) -> None:
        if domain not in self._selector_stats:
            self._selector_stats[domain] = {}
        if selector not in self._selector_stats[domain]:
            self._selector_stats[domain][selector] = {"hits": 0, "misses": 0}
        key = "hits" if success else "misses"
        self._selector_stats[domain][selector][key] += 1
        self._save()

    def record_stealth_detection(self, domain: str, detection_type: str, bypassed_by: str = "") -> None:
        self._stealth_detections.append({
            "timestamp": time.time(),
            "domain": domain,
            "detection_type": detection_type,
            "bypassed_by": bypassed_by,
        })
        if len(self._stealth_detections) > 500:
            self._stealth_detections = self._stealth_detections[-250:]
        self._save()

    def get_selector_stats(self, domain: str = "") -> Dict[str, Dict[str, Dict[str, float]]]:
        if domain:
            return {domain: self._selector_stats.get(domain, {})}
        return dict(self._selector_stats)

    def get_detection_summary(self) -> Dict[str, Any]:
        detection_counts: Dict[str, int] = {}
        bypassed_counts: Dict[str, int] = {}
        for d in self._stealth_detections:
            detection_counts[d["detection_type"]] = detection_counts.get(d["detection_type"], 0) + 1
            if d.get("bypassed_by"):
                bypassed_counts[d["bypassed_by"]] = bypassed_counts.get(d["bypassed_by"], 0) + 1
        return {
            "total_detections": len(self._stealth_detections),
            "by_type": detection_counts,
            "bypasses": bypassed_counts,
        }


@dataclass
class DomainTuningProfile:
    """Per-domain behavior tuning profile with bounded adaptation."""
    domain: str
    typing_speed: float = 0.5
    scroll_depth: float = 0.5
    mouse_precision: float = 0.5
    pause_frequency: float = 0.5
    distraction_rate: float = 0.3
    min_typing_speed: float = 0.3
    min_scroll_depth: float = 0.3
    min_mouse_precision: float = 0.3
    success_count: int = 0
    fail_count: int = 0

    @staticmethod
    def default_bounds() -> Dict[str, tuple]:
        return {
            "typing_speed": (0.3, 1.0),
            "scroll_depth": (0.3, 1.0),
            "mouse_precision": (0.3, 1.0),
            "pause_frequency": (0.2, 0.8),
            "distraction_rate": (0.1, 0.5),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "typing_speed": self.typing_speed,
            "scroll_depth": self.scroll_depth,
            "mouse_precision": self.mouse_precision,
            "pause_frequency": self.pause_frequency,
            "distraction_rate": self.distraction_rate,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
        }

    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        if total == 0:
            return 1.0
        return self.success_count / total


class BehaviorTuner:
    """Adaptive behavior tuning using historical feedback.

    Uses a simple weighted scoring system to adjust behavior parameters
    based on what has worked (not blocked) vs what hasn't (blocked).

    v1.8.0 adds:
      - FeedbackStore integration for persistent telemetry
      - Domain-specific tuning profiles
      - Bounded adaptation (never drops below minimum stealth thresholds)

    Usage:
        tuner = BehaviorTuner()
        # After each session:
        tuner.record_feedback(blocked=False, behavior_params={...})
        # Get optimized params:
        params = tuner.get_optimized_params()
        # Get domain-specific profile:
        profile = tuner.get_domain_profile("linkedin.com")
    """

    def __init__(self, rng: Optional[random.Random] = None, feedback_store: Optional[FeedbackStore] = None):
        self.rng = rng or random.Random()
        self._feedback_history: List[BehaviorFeedback] = []
        self._current_params: Dict[str, float] = {
            "typing_speed": 0.5,
            "scroll_depth": 0.5,
            "mouse_precision": 0.5,
            "pause_frequency": 0.5,
            "distraction_rate": 0.3,
        }
        self._successful_params: List[Dict[str, float]] = []
        self._failed_params: List[Dict[str, float]] = []
        self._domain_profiles: Dict[str, DomainTuningProfile] = {}
        self._feedback_store = feedback_store or FeedbackStore()

    def record_feedback(self, blocked: bool, block_type: str = "none",
                        platform: str = "unknown",
                        behavior_params: Optional[Dict[str, float]] = None,
                        response_time: float = 0.0,
                        domain: str = "",
                        recovery_attempts: int = 0,
                        selector_results: Optional[Dict[str, bool]] = None,
                        stealth_events: Optional[List[Dict[str, Any]]] = None):
        """Record feedback from a browsing session."""
        feedback = BehaviorFeedback(
            timestamp=time.time(),
            blocked=blocked,
            block_type=block_type,
            platform=platform,
            domain=domain,
            behavior_params=behavior_params or self._current_params.copy(),
            response_time=response_time,
            recovery_attempts=recovery_attempts,
            selector_success={sel: (1.0 if ok else 0.0) for sel, ok in (selector_results or {}).items()},
            stealth_events=stealth_events or [],
        )
        self._feedback_history.append(feedback)

        params = feedback.behavior_params
        if blocked:
            self._failed_params.append(params)
        else:
            self._successful_params.append(params)

        if domain:
            self._update_domain_profile(feedback)

        self._feed_telemetry_store(feedback)

        if len(self._feedback_history) >= 5:
            self._auto_tune()

    def _update_domain_profile(self, feedback: BehaviorFeedback) -> None:
        domain = feedback.domain
        if domain not in self._domain_profiles:
            self._domain_profiles[domain] = DomainTuningProfile(
                domain=domain,
                typing_speed=self._current_params.get("typing_speed", 0.5),
                scroll_depth=self._current_params.get("scroll_depth", 0.5),
                mouse_precision=self._current_params.get("mouse_precision", 0.5),
                pause_frequency=self._current_params.get("pause_frequency", 0.5),
                distraction_rate=self._current_params.get("distraction_rate", 0.3),
            )
        profile = self._domain_profiles[domain]
        if feedback.blocked:
            profile.fail_count += 1
        else:
            profile.success_count += 1

        params = feedback.behavior_params or {}
        bounds = DomainTuningProfile.default_bounds()
        for key in ["typing_speed", "scroll_depth", "mouse_precision", "pause_frequency", "distraction_rate"]:
            if key in params:
                current = getattr(profile, key, 0.5)
                low, high = bounds.get(key, (0.0, 1.0))
                lerp = 0.1
                new_val = current + lerp * (params[key] - current)
                clamped = max(low, min(high, new_val))
                setattr(profile, key, clamped)

    def _feed_telemetry_store(self, feedback: BehaviorFeedback) -> None:
        self._feedback_store.record_event(
            event_type="block" if feedback.blocked else "navigate",
            domain=feedback.domain or feedback.platform,
            details={
                "blocked": feedback.blocked,
                "block_type": feedback.block_type,
                "platform": feedback.platform,
                "params": feedback.behavior_params,
                "response_time": feedback.response_time,
                "recovery_attempts": feedback.recovery_attempts,
            },
        )
        for sel, rate in feedback.selector_success.items():
            self._feedback_store.record_selector_result(
                feedback.domain, sel, rate >= 0.5,
            )
        for event in feedback.stealth_events:
            self._feedback_store.record_stealth_detection(
                domain=feedback.domain or feedback.platform,
                detection_type=event.get("type", "unknown"),
                bypassed_by=event.get("bypassed_by", ""),
            )

    def get_domain_profile(self, domain: str) -> Optional[DomainTuningProfile]:
        return self._domain_profiles.get(domain)

    def get_all_domain_profiles(self) -> Dict[str, DomainTuningProfile]:
        return dict(self._domain_profiles)

    def get_optimized_params(self, domain: str = "") -> Dict[str, float]:
        """Get behavior parameters optimized from historical data, optionally per-domain."""
        if domain and domain in self._domain_profiles:
            prof = self._domain_profiles[domain]
            return {
                "typing_speed": prof.typing_speed,
                "scroll_depth": prof.scroll_depth,
                "mouse_precision": prof.mouse_precision,
                "pause_frequency": prof.pause_frequency,
                "distraction_rate": prof.distraction_rate,
            }
        if not self._successful_params:
            return self._current_params.copy()
        optimized = {}
        for key in self._current_params:
            values = [p.get(key, 0.5) for p in self._successful_params if key in p]
            if values:
                optimized[key] = sum(values) / len(values)
            else:
                optimized[key] = self._current_params[key]
        return optimized

    def get_success_rate(self) -> float:
        """Get overall success rate."""
        if not self._feedback_history:
            return 1.0
        successes = sum(1 for f in self._feedback_history if not f.blocked)
        return successes / len(self._feedback_history)

    def get_platform_success_rates(self) -> Dict[str, float]:
        """Get success rates per platform."""
        platform_stats: Dict[str, Dict[str, int]] = {}
        for f in self._feedback_history:
            if f.platform not in platform_stats:
                platform_stats[f.platform] = {"total": 0, "success": 0}
            platform_stats[f.platform]["total"] += 1
            if not f.blocked:
                platform_stats[f.platform]["success"] += 1
        return {
            platform: stats["success"] / max(1, stats["total"])
            for platform, stats in platform_stats.items()
        }

    def get_block_type_distribution(self) -> Dict[str, int]:
        """Get distribution of block types."""
        dist: Dict[str, int] = {}
        for f in self._feedback_history:
            if f.blocked:
                dist[f.block_type] = dist.get(f.block_type, 0) + 1
        return dist

    def get_stealth_detection_summary(self) -> Dict[str, Any]:
        return self._feedback_store.get_detection_summary()

    def _auto_tune(self):
        """Automatically adjust parameters based on feedback.

        v1.8.0: Bounded adaptation — never reduces below minimum stealth thresholds.
        """
        if not self._successful_params or not self._failed_params:
            return
        min_bounds = {
            "typing_speed": 0.3,
            "scroll_depth": 0.3,
            "mouse_precision": 0.3,
            "pause_frequency": 0.2,
            "distraction_rate": 0.1,
        }
        for key in self._current_params:
            success_vals = [p.get(key, 0.5) for p in self._successful_params if key in p]
            fail_vals = [p.get(key, 0.5) for p in self._failed_params if key in p]
            if not success_vals or not fail_vals:
                continue
            success_avg = sum(success_vals) / len(success_vals)
            fail_avg = sum(fail_vals) / len(fail_vals)
            diff = abs(success_avg - fail_avg)
            weight = min(0.1, diff * 0.5)
            current = self._current_params[key]
            self._current_params[key] = current + weight * (success_avg - current)
            lo = min_bounds.get(key, 0.0)
            self._current_params[key] = max(lo, min(1.0, self._current_params[key]))

    def get_telemetry_report(self) -> Dict[str, Any]:
        return {
            "total_feedback_events": len(self._feedback_history),
            "store_events": len(self._feedback_store._events),
            "detection_summary": self.get_stealth_detection_summary(),
            "domain_profiles": {
                domain: prof.to_dict() for domain, prof in self._domain_profiles.items()
            },
            "selector_stats": self._feedback_store.get_selector_stats(),
        }

    def get_status(self) -> Dict[str, Any]:
        """Get tuner status including domain profiles and telemetry."""
        return {
            "total_sessions": len(self._feedback_history),
            "success_rate": self.get_success_rate(),
            "successful_sessions": len(self._successful_params),
            "failed_sessions": len(self._failed_params),
            "current_params": self._current_params.copy(),
            "optimized_params": self.get_optimized_params(),
            "platform_rates": self.get_platform_success_rates(),
            "block_distribution": self.get_block_type_distribution(),
            "domain_profile_count": len(self._domain_profiles),
            "domain_profiles": {
                domain: prof.to_dict() for domain, prof in self._domain_profiles.items()
            },
            "telemetry": self.get_telemetry_report(),
        }

    def reset(self):
        """Reset all feedback data."""
        self._feedback_history.clear()
        self._successful_params.clear()
        self._failed_params.clear()
        self._domain_profiles.clear()
        self._current_params = {
            "typing_speed": 0.5,
            "scroll_depth": 0.5,
            "mouse_precision": 0.5,
            "pause_frequency": 0.5,
            "distraction_rate": 0.3,
        }
