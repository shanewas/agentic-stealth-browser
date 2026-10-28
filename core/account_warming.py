"""
Account Warming & Gradual Activity Ramp-Up
Addresses #137: Add first-class support for account warming and gradual activity ramp-up.

Provides a high-level AccountWarmer that slowly increases:
- Action volume (pages visited, actions per session)
- Scroll depth
- Site variety
- Session duration

over multiple sessions to build account trust.
"""

import time
import json
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass


@dataclass
class WarmingPhase:
    """A single phase in the warming schedule."""

    phase: int
    days: int  # How many days this phase lasts
    max_actions: int  # Max actions per session
    max_pages: int  # Max pages per session
    max_scroll_depth: int  # Max scroll depth (pixels)
    max_session_minutes: int  # Max session duration
    site_variety: int  # Max unique domains per session
    action_delay_min: float  # Min delay between actions (seconds)
    action_delay_max: float  # Max delay between actions (seconds)


# Default warming schedule: gradual ramp-up over 14 days
DEFAULT_WARMING_SCHEDULE = [
    WarmingPhase(0, 2, 5, 3, 200, 5, 1, 8.0, 20.0),  # Day 1-2: Very light
    WarmingPhase(1, 2, 10, 5, 500, 10, 2, 5.0, 15.0),  # Day 3-4: Light
    WarmingPhase(2, 3, 20, 8, 1000, 15, 3, 3.0, 10.0),  # Day 5-7: Moderate
    WarmingPhase(3, 3, 35, 12, 2000, 20, 4, 2.0, 8.0),  # Day 8-10: Normal-ish
    WarmingPhase(4, 4, 50, 15, 5000, 30, 5, 1.0, 5.0),  # Day 11-14: Near full
]


class AccountWarmer:
    """Manages account warming schedule and tracks progress.

    Usage:
        warmer = AccountWarmer(account_id="user123", data_dir="./warming")
        warmer.start()  # Begins warming schedule

        # Before each session:
        limits = warmer.get_session_limits()
        print(f"Max pages: {limits['max_pages']}")
        print(f"Action delay: {limits['action_delay_min']}-{limits['action_delay_max']}s")

        # During session:
        warmer.record_action()
        warmer.record_page_visit("https://example.com")

        # After session:
        warmer.end_session()

        # After warming period:
        if warmer.is_warmed():
            print("Account is fully warmed!")
    """

    def __init__(
        self,
        account_id: str = "default",
        data_dir: str = "./warming_data",
        schedule: Optional[List[WarmingPhase]] = None,
        logger: Optional[Any] = None,
    ):
        self.account_id = account_id
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.schedule = schedule or DEFAULT_WARMING_SCHEDULE
        self._logger = logger

        # State
        self._started_at: Optional[float] = None
        self._current_phase: int = 0
        self._total_sessions: int = 0
        self._total_actions: int = 0
        self._session_actions: int = 0
        self._session_pages: int = 0
        self._session_domains: set = set()
        self._session_start: Optional[float] = None
        self._session_active: bool = False
        self._max_scroll_this_session: int = 0

    @property
    def session_active(self) -> bool:
        """Whether a warming session is currently active."""
        return self._session_active

    @property
    def days_elapsed(self) -> float:
        """Days since warming started."""
        if not self._started_at:
            return 0.0
        return (time.time() - self._started_at) / 86400.0

    @property
    def current_phase(self) -> WarmingPhase:
        """Get current warming phase."""
        if not self._started_at:
            return self.schedule[0]

        days = self.days_elapsed
        cumulative_days = 0
        for phase in self.schedule:
            cumulative_days += phase.days
            if days < cumulative_days:
                return phase

        # Past all phases - return last phase (fully warmed)
        return self.schedule[-1]

    @property
    def phase_index(self) -> int:
        """Current phase index."""
        return self.current_phase.phase

    @property
    def progress(self) -> float:
        """Overall warming progress (0.0-1.0)."""
        if not self._started_at:
            return 0.0

        total_days = sum(p.days for p in self.schedule)
        return min(1.0, self.days_elapsed / total_days)

    def is_warmed(self) -> bool:
        """Check if account is fully warmed."""
        return self.progress >= 1.0

    def start(self):
        """Start the warming schedule."""
        if self._started_at:
            self._log("Warming already in progress")
            return

        self._started_at = time.time()
        self._current_phase = 0
        self._total_sessions = 0
        self._total_actions = 0
        self._save_state()
        self._log(f"Warming started with {len(self.schedule)} phases")

    def start_session(self):
        """Begin a new session."""
        if not self._started_at:
            self.start()

        self._session_start = time.time()
        self._session_active = True
        self._session_actions = 0
        self._session_pages = 0
        self._session_domains = set()
        self._max_scroll_this_session = 0
        self._total_sessions += 1
        self._log(f"Session {self._total_sessions} started")

    def end_session(self):
        """End current session and save state."""
        if not self._session_start:
            self._session_active = False
            return

        duration = (time.time() - self._session_start) / 60.0
        self._session_start = None
        self._session_active = False
        self._total_actions += self._session_actions
        self._save_state()
        self._log(
            f"Session ended: {self._session_actions} actions, "
            f"{self._session_pages} pages, {duration:.1f}min"
        )

    def record_action(self):
        """Record an action during session."""
        self._session_actions += 1

    @staticmethod
    def _domain_from_url(url: str) -> str:
        """Extract the domain recorded for a visited URL."""
        try:
            return url.split("://")[1].split("/")[0].split(":")[0]
        except (IndexError, AttributeError):
            return url

    def _site_variety_exceeded(
        self,
        limits: Dict[str, Any],
        url: Optional[str] = None,
        domain: Optional[str] = None,
    ) -> bool:
        """Whether a prospective visit would exceed the distinct-domain cap.

        Site variety counts DISTINCT domains. A visit to a domain already
        in this session adds none, so it is always allowed by this check.
        Without a prospective visit, reaching the cap still reports stop,
        preserving the no-argument behaviour existing callers rely on.
        """
        if domain is not None:
            prospective = domain.split(":")[0]
        elif url is not None:
            prospective = self._domain_from_url(url)
        else:
            return len(self._session_domains) >= limits["site_variety"]
        return (
            prospective not in self._session_domains
            and len(self._session_domains) >= limits["site_variety"]
        )

    def record_page_visit(self, url: str):
        """Record a page visit."""
        self._session_pages += 1
        self._session_domains.add(self._domain_from_url(url))

    def record_scroll(self, depth: int):
        """Record scroll depth."""
        self._max_scroll_this_session = max(self._max_scroll_this_session, depth)

    def get_session_limits(self) -> Dict[str, Any]:
        """Get current session limits based on warming phase."""
        phase = self.current_phase
        return {
            "max_actions": phase.max_actions,
            "max_pages": phase.max_pages,
            "max_scroll_depth": phase.max_scroll_depth,
            "max_session_minutes": phase.max_session_minutes,
            "site_variety": phase.site_variety,
            "action_delay_min": phase.action_delay_min,
            "action_delay_max": phase.action_delay_max,
            "phase": phase.phase,
            "progress": self.progress,
            "is_warmed": self.is_warmed(),
        }

    def should_stop_session(
        self, url: Optional[str] = None, domain: Optional[str] = None
    ) -> bool:
        """Check if session should end based on warming limits.

        ``url``/``domain`` optionally identify the prospective visit, so
        the site-variety check can allow a repeat of a known domain.
        """
        if not self._session_start:
            return False

        limits = self.get_session_limits()
        elapsed_minutes = (time.time() - self._session_start) / 60.0

        if elapsed_minutes >= limits["max_session_minutes"]:
            return True
        if self._session_actions >= limits["max_actions"]:
            return True
        if self._session_pages >= limits["max_pages"]:
            return True
        if self._max_scroll_this_session >= limits["max_scroll_depth"]:
            return True
        if self._site_variety_exceeded(limits, url=url, domain=domain):
            return True

        return False

    def get_reason_to_stop(
        self, url: Optional[str] = None, domain: Optional[str] = None
    ) -> Optional[str]:
        """Get reason why session should stop, or None."""
        if not self._session_start:
            return None

        limits = self.get_session_limits()
        elapsed_minutes = (time.time() - self._session_start) / 60.0

        if elapsed_minutes >= limits["max_session_minutes"]:
            return f"Session duration limit reached ({elapsed_minutes:.1f}/{limits['max_session_minutes']}min)"
        if self._session_actions >= limits["max_actions"]:
            return f"Action limit reached ({self._session_actions}/{limits['max_actions']})"
        if self._session_pages >= limits["max_pages"]:
            return f"Page limit reached ({self._session_pages}/{limits['max_pages']})"
        if self._max_scroll_this_session >= limits["max_scroll_depth"]:
            return f"Scroll depth limit reached ({self._max_scroll_this_session}/{limits['max_scroll_depth']})"
        if self._site_variety_exceeded(limits, url=url, domain=domain):
            return f"Site variety limit reached ({len(self._session_domains)}/{limits['site_variety']})"

        return None

    def get_status(self) -> Dict[str, Any]:
        """Get full warming status."""
        return {
            "account_id": self.account_id,
            "started_at": self._started_at,
            "days_elapsed": self.days_elapsed,
            "current_phase": self.phase_index,
            "progress": self.progress,
            "is_warmed": self.is_warmed(),
            "total_sessions": self._total_sessions,
            "total_actions": self._total_actions,
            "session_limits": self.get_session_limits(),
        }

    def reset(self):
        """Reset warming state (use with caution)."""
        self._started_at = None
        self._current_phase = 0
        self._total_sessions = 0
        self._total_actions = 0
        self._session_actions = 0
        self._session_pages = 0
        self._session_domains = set()
        self._session_start = None
        self._session_active = False
        self._max_scroll_this_session = 0
        self._save_state()
        self._log("Warming state reset")

    def _save_state(self):
        """Persist state to disk."""
        state = {
            "account_id": self.account_id,
            "started_at": self._started_at,
            "current_phase": self._current_phase,
            "total_sessions": self._total_sessions,
            "total_actions": self._total_actions,
        }
        state_file = self.data_dir / f"{self.account_id}.json"
        with open(state_file, "w") as f:
            json.dump(state, f, indent=2)

    def _load_state(self):
        """Load state from disk."""
        state_file = self.data_dir / f"{self.account_id}.json"
        if not state_file.exists():
            return

        with open(state_file) as f:
            state = json.load(f)

        self._started_at = state.get("started_at")
        self._current_phase = state.get("current_phase", 0)
        self._total_sessions = state.get("total_sessions", 0)
        self._total_actions = state.get("total_actions", 0)

    def _log(self, msg: str):
        """Log a message."""
        if self._logger and hasattr(self._logger, "log_action"):
            self._logger.log_action(
                "account_warming",
                {"account_id": self.account_id, "message": msg},
                level="info",
            )
        else:
            print(f"[AccountWarmer:{self.account_id}] {msg}")
