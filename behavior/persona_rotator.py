"""
Rotating Behavioral Personas
Addresses #129: Add support for rotating between multiple behavioral personas per account over time.

Real users change devices, locations, and behavior patterns gradually.
PersonaRotator slowly evolves device profile, typing speed, scroll patterns, etc. over days/weeks.
"""

import time
import random
from typing import Optional, Dict, Any, List
from dataclasses import dataclass


@dataclass
class PersonaTrait:
    """A single behavioral trait that can evolve over time."""
    name: str
    current_value: float
    target_value: float
    evolution_rate: float  # Change per day (0.0-1.0)
    min_value: float = 0.0
    max_value: float = 1.0
    last_updated: float = 0.0

    def evolve(self, days_elapsed: float):
        """Evolve trait toward target value over time."""
        if days_elapsed <= 0:
            return

        change = (self.target_value - self.current_value) * self.evolution_rate * days_elapsed
        self.current_value = max(self.min_value, min(self.max_value, self.current_value + change))
        self.last_updated = time.time()

    def is_stable(self, tolerance: float = 0.01) -> bool:
        """Check if trait is close enough to target."""
        return abs(self.current_value - self.target_value) < tolerance


@dataclass
class PersonaProfile:
    """A complete behavioral persona profile."""
    name: str
    # Behavioral traits
    typing_speed: float = 0.5  # 0=slow, 1=fast
    scroll_depth: float = 0.5  # 0=shallow, 1=deep
    mouse_precision: float = 0.5  # 0=erratic, 1=precise
    pause_frequency: float = 0.5  # 0=rare, 1=frequent
    distraction_rate: float = 0.3  # 0=focused, 1=easily distracted
    session_length: float = 0.5  # 0=short, 1=long
    site_variety: float = 0.5  # 0=single-site, 1=multi-site
    # Device traits
    device_type: str = "laptop"
    os_preference: str = "windows"
    browser_preference: str = "chrome"
    # Location traits
    timezone: str = "UTC"
    locale: str = "en-US"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "typing_speed": self.typing_speed,
            "scroll_depth": self.scroll_depth,
            "mouse_precision": self.mouse_precision,
            "pause_frequency": self.pause_frequency,
            "distraction_rate": self.distraction_rate,
            "session_length": self.session_length,
            "site_variety": self.site_variety,
            "device_type": self.device_type,
            "os_preference": self.os_preference,
            "browser_preference": self.browser_preference,
            "timezone": self.timezone,
            "locale": self.locale,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PersonaProfile":
        return cls(
            name=data.get("name", "unknown"),
            typing_speed=data.get("typing_speed", 0.5),
            scroll_depth=data.get("scroll_depth", 0.5),
            mouse_precision=data.get("mouse_precision", 0.5),
            pause_frequency=data.get("pause_frequency", 0.5),
            distraction_rate=data.get("distraction_rate", 0.3),
            session_length=data.get("session_length", 0.5),
            site_variety=data.get("site_variety", 0.5),
            device_type=data.get("device_type", "laptop"),
            os_preference=data.get("os_preference", "windows"),
            browser_preference=data.get("browser_preference", "chrome"),
            timezone=data.get("timezone", "UTC"),
            locale=data.get("locale", "en-US"),
        )


# Predefined persona templates
PERSONA_TEMPLATES = {
    "casual_user": PersonaProfile(
        name="casual_user",
        typing_speed=0.4,
        scroll_depth=0.3,
        mouse_precision=0.4,
        pause_frequency=0.6,
        distraction_rate=0.5,
        session_length=0.3,
        site_variety=0.4,
    ),
    "power_user": PersonaProfile(
        name="power_user",
        typing_speed=0.8,
        scroll_depth=0.8,
        mouse_precision=0.9,
        pause_frequency=0.3,
        distraction_rate=0.2,
        session_length=0.8,
        site_variety=0.9,
    ),
    "mobile_user": PersonaProfile(
        name="mobile_user",
        typing_speed=0.3,
        scroll_depth=0.6,
        mouse_precision=0.3,
        pause_frequency=0.5,
        distraction_rate=0.6,
        session_length=0.4,
        site_variety=0.5,
        device_type="mobile",
    ),
    "researcher": PersonaProfile(
        name="researcher",
        typing_speed=0.6,
        scroll_depth=0.9,
        mouse_precision=0.7,
        pause_frequency=0.7,
        distraction_rate=0.3,
        session_length=0.9,
        site_variety=0.8,
    ),
    "shopper": PersonaProfile(
        name="shopper",
        typing_speed=0.5,
        scroll_depth=0.7,
        mouse_precision=0.6,
        pause_frequency=0.4,
        distraction_rate=0.4,
        session_length=0.6,
        site_variety=0.7,
    ),
}


class PersonaRotator:
    """Manages gradual evolution of behavioral personas over time.

    Usage:
        rotator = PersonaRotator(account_id="user123")
        rotator.set_current_persona("casual_user")

        # Get current behavioral parameters
        params = rotator.get_behavior_params()
        print(f"Typing delay: {params['typing_delay_min']}-{params['typing_delay_max']}ms")

        # Evolve persona over time
        rotator.evolve(days_elapsed=7)

        # Switch to new persona gradually
        rotator.transition_to("power_user", transition_days=14)
    """

    BEHAVIORAL_TRAITS = [
        "typing_speed", "scroll_depth", "mouse_precision",
        "pause_frequency", "distraction_rate", "session_length", "site_variety"
    ]

    def __init__(
        self,
        account_id: str = "default",
        rng: Optional[random.Random] = None,
        logger: Optional[Any] = None,
    ):
        self.account_id = account_id
        self.rng = rng or random.Random()
        self._logger = logger

        self._current_persona: Optional[PersonaProfile] = None
        self._target_persona: Optional[PersonaProfile] = None
        self._transition_start: Optional[float] = None
        self._transition_days: float = 0.0
        self._traits: Dict[str, PersonaTrait] = {}
        self._started_at: float = time.time()
        self._evolution_log: List[Dict[str, Any]] = []

    @property
    def current_persona(self) -> Optional[PersonaProfile]:
        return self._current_persona

    @property
    def days_active(self) -> float:
        return (time.time() - self._started_at) / 86400.0

    def set_current_persona(self, persona_name: str):
        """Set the current persona from templates or custom profile."""
        if persona_name in PERSONA_TEMPLATES:
            self._current_persona = PERSONA_TEMPLATES[persona_name]
        else:
            self._current_persona = PersonaProfile(name=persona_name)

        self._init_traits()
        self._log(f"Set current persona: {persona_name}")

    def set_custom_persona(self, profile: PersonaProfile):
        """Set a custom persona profile."""
        self._current_persona = profile
        self._init_traits()
        self._log(f"Set custom persona: {profile.name}")

    def transition_to(self, target_name: str, transition_days: float = 14.0):
        """Start gradual transition to a new persona."""
        if target_name in PERSONA_TEMPLATES:
            self._target_persona = PERSONA_TEMPLATES[target_name]
        else:
            self._target_persona = PersonaProfile(name=target_name)

        self._transition_start = time.time()
        self._transition_days = transition_days

        # Update trait targets
        for trait_name in self.BEHAVIORAL_TRAITS:
            if trait_name in self._traits:
                target_value = getattr(self._target_persona, trait_name, 0.5)
                self._traits[trait_name].target_value = target_value

        self._log(f"Transitioning to {target_name} over {transition_days} days")

    def evolve(self, days_elapsed: float = 1.0):
        """Evolve all traits over the given time period."""
        for trait in self._traits.values():
            trait.evolve(days_elapsed)

        # Check if transition is complete
        if self._is_transition_complete():
            self._complete_transition()

        self._evolution_log.append({
            "timestamp": time.time(),
            "days_elapsed": days_elapsed,
            "traits": {name: t.current_value for name, t in self._traits.items()},
        })

    def get_behavior_params(self) -> Dict[str, Any]:
        """Get current behavioral parameters for use in human behavior simulation."""
        if not self._current_persona:
            return self._default_params()

        traits = {name: t.current_value for name, t in self._traits.items()}

        # Map traits to actual behavior parameters
        typing_speed = traits.get("typing_speed", 0.5)
        typing_delay_min = int(30 + (1 - typing_speed) * 70)  # 30-100ms
        typing_delay_max = int(80 + (1 - typing_speed) * 120)  # 80-200ms

        scroll_depth = traits.get("scroll_depth", 0.5)
        scroll_pixels = int(200 + scroll_depth * 800)  # 200-1000px

        mouse_precision = traits.get("mouse_precision", 0.5)
        mouse_steps = int(10 + mouse_precision * 20)  # 10-30 steps

        pause_frequency = traits.get("pause_frequency", 0.5)
        pause_probability = 0.1 + pause_frequency * 0.3  # 0.1-0.4

        distraction_rate = traits.get("distraction_rate", 0.3)
        distraction_probability = distraction_rate * 0.3  # 0-0.09

        session_length = traits.get("session_length", 0.5)
        max_session_minutes = int(5 + session_length * 55)  # 5-60 min

        site_variety = traits.get("site_variety", 0.5)
        max_domains = int(1 + site_variety * 9)  # 1-10 domains

        return {
            "typing_delay_min": typing_delay_min,
            "typing_delay_max": typing_delay_max,
            "scroll_pixels": scroll_pixels,
            "mouse_steps": mouse_steps,
            "pause_probability": pause_probability,
            "distraction_probability": distraction_probability,
            "max_session_minutes": max_session_minutes,
            "max_domains": max_domains,
            "persona_name": self._current_persona.name,
            "days_active": self.days_active,
        }

    def get_trait_values(self) -> Dict[str, float]:
        """Get current trait values."""
        return {name: t.current_value for name, t in self._traits.items()}

    def get_transition_progress(self) -> float:
        """Get transition progress (0.0-1.0)."""
        if not self._transition_start or not self._target_persona:
            return 0.0

        elapsed = (time.time() - self._transition_start) / 86400.0
        return min(1.0, elapsed / self._transition_days)

    def is_transitioning(self) -> bool:
        """Check if currently transitioning."""
        return self._target_persona is not None and not self._is_transition_complete()

    def get_status(self) -> Dict[str, Any]:
        """Get full rotator status."""
        return {
            "account_id": self.account_id,
            "current_persona": self._current_persona.name if self._current_persona else None,
            "target_persona": self._target_persona.name if self._target_persona else None,
            "transition_progress": self.get_transition_progress(),
            "is_transitioning": self.is_transitioning(),
            "days_active": self.days_active,
            "traits": self.get_trait_values(),
            "behavior_params": self.get_behavior_params(),
        }

    def _init_traits(self):
        """Initialize traits from current persona."""
        if not self._current_persona:
            return

        for trait_name in self.BEHAVIORAL_TRAITS:
            value = getattr(self._current_persona, trait_name, 0.5)
            self._traits[trait_name] = PersonaTrait(
                name=trait_name,
                current_value=value,
                target_value=value,
                evolution_rate=0.1,  # 10% per day
                last_updated=time.time(),
            )

    def _is_transition_complete(self) -> bool:
        """Check if all traits have reached their targets."""
        if not self._target_persona:
            return True

        return all(
            trait.is_stable()
            for trait in self._traits.values()
        )

    def _complete_transition(self):
        """Complete the transition and set target as current."""
        if self._target_persona:
            self._current_persona = self._target_persona
            self._target_persona = None
            self._transition_start = None
            self._log(f"Transition complete: {self._current_persona.name}")

    def _default_params(self) -> Dict[str, Any]:
        """Default behavior parameters when no persona is set."""
        return {
            "typing_delay_min": 50,
            "typing_delay_max": 120,
            "scroll_pixels": 500,
            "mouse_steps": 15,
            "pause_probability": 0.2,
            "distraction_probability": 0.05,
            "max_session_minutes": 30,
            "max_domains": 5,
            "persona_name": "default",
            "days_active": self.days_active,
        }

    def _log(self, msg: str):
        """Log a message."""
        if self._logger and hasattr(self._logger, "log_action"):
            self._logger.log_action(
                "persona_rotator",
                {"account_id": self.account_id, "message": msg},
                level="info"
            )
        else:
            print(f"[PersonaRotator:{self.account_id}] {msg}")
