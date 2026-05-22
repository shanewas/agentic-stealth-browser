"""
Adaptive/ML-driven behavior tuning based on block detection feedback.
Addresses #71: Add adaptive / ML-driven behavior tuning based on block detection feedback.

Uses historical block data to adjust behavior parameters automatically.
"""

import time
import random
from typing import Optional, Dict, Any, List
from dataclasses import dataclass


@dataclass
class BehaviorFeedback:
    """A single feedback event from a browsing session."""
    timestamp: float
    blocked: bool
    block_type: str = "none"
    platform: str = "unknown"
    behavior_params: Optional[Dict[str, float]] = None
    response_time: float = 0.0


class BehaviorTuner:
    """Adaptive behavior tuning using historical feedback.

    Uses a simple weighted scoring system to adjust behavior parameters
    based on what has worked (not blocked) vs what hasn't (blocked).

    Usage:
        tuner = BehaviorTuner()
        # After each session:
        tuner.record_feedback(blocked=False, behavior_params={...})
        # Get optimized params:
        params = tuner.get_optimized_params()
    """

    def __init__(self, rng: Optional[random.Random] = None):
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

    def record_feedback(self, blocked: bool, block_type: str = "none",
                        platform: str = "unknown",
                        behavior_params: Optional[Dict[str, float]] = None,
                        response_time: float = 0.0):
        """Record feedback from a browsing session."""
        feedback = BehaviorFeedback(
            timestamp=time.time(),
            blocked=blocked,
            block_type=block_type,
            platform=platform,
            behavior_params=behavior_params or self._current_params.copy(),
            response_time=response_time,
        )
        self._feedback_history.append(feedback)

        params = feedback.behavior_params
        if blocked:
            self._failed_params.append(params)
        else:
            self._successful_params.append(params)

        # Auto-tune if we have enough data
        if len(self._feedback_history) >= 5:
            self._auto_tune()

    def get_optimized_params(self) -> Dict[str, float]:
        """Get behavior parameters optimized from historical data."""
        if not self._successful_params:
            return self._current_params.copy()

        # Average of successful parameters
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

    def _auto_tune(self):
        """Automatically adjust parameters based on feedback."""
        if not self._successful_params or not self._failed_params:
            return

        # For each parameter, compare successful vs failed averages
        for key in self._current_params:
            success_vals = [p.get(key, 0.5) for p in self._successful_params if key in p]
            fail_vals = [p.get(key, 0.5) for p in self._failed_params if key in p]

            if not success_vals or not fail_vals:
                continue

            success_avg = sum(success_vals) / len(success_vals)
            fail_avg = sum(fail_vals) / len(fail_vals)

            # Move current params toward successful average
            # Weight by how different failed params were
            diff = abs(success_avg - fail_avg)
            weight = min(0.1, diff * 0.5)  # Small adjustment

            current = self._current_params[key]
            self._current_params[key] = current + weight * (success_avg - current)

            # Clamp to valid range
            self._current_params[key] = max(0.0, min(1.0, self._current_params[key]))

    def get_status(self) -> Dict[str, Any]:
        """Get tuner status."""
        return {
            "total_sessions": len(self._feedback_history),
            "success_rate": self.get_success_rate(),
            "successful_sessions": len(self._successful_params),
            "failed_sessions": len(self._failed_params),
            "current_params": self._current_params.copy(),
            "optimized_params": self.get_optimized_params(),
            "platform_rates": self.get_platform_success_rates(),
            "block_distribution": self.get_block_type_distribution(),
        }

    def reset(self):
        """Reset all feedback data."""
        self._feedback_history.clear()
        self._successful_params.clear()
        self._failed_params.clear()
        self._current_params = {
            "typing_speed": 0.5,
            "scroll_depth": 0.5,
            "mouse_precision": 0.5,
            "pause_frequency": 0.5,
            "distraction_rate": 0.3,
        }
