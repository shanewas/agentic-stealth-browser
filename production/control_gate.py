"""Control gate for dashboard control modes (issue #446, slice A1).

One ``ControlGate`` lives on the dashboard's ``BrowserRuntimeManager``
(one per dashboard session). It is the single writer of the mode /
paused / intervention state that the dashboard used to mutate without
anything reading it, and the object the workflow player will check at
step boundaries in slice A2.

Mode semantics:
- ``agent``: agent actions allowed; human-originated browser actions
  are rejected with ``CONTROL_MODE_AGENT``.
- ``human``: human actions allowed; agent actions are rejected with
  ``CONTROL_MODE_HUMAN`` (new workflow starts are refused here; a
  running workflow pauses cooperatively in A2).
- ``shared``: both allowed.

Pausing and an open intervention block agent actions only; they never
block the human, who is the one expected to resolve them. Viewing
(read-only endpoints) is never gated by this class.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

VALID_MODES = ("agent", "human", "shared")
VALID_ACTORS = ("agent", "human")


class ControlModeError(RuntimeError):
    """Structured refusal raised when the gate blocks an action."""

    def __init__(self, code: str, mode: str, actor: str, message: str = ""):
        self.code = code
        self.mode = mode
        self.actor = actor
        super().__init__(message or f"{code}: {actor} action blocked in {mode} mode")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "error": self.code,
            "mode": self.mode,
            "actor": self.actor,
            "message": str(self),
        }


class ControlGate:
    def __init__(self, mode: str = "shared"):
        if mode not in VALID_MODES:
            raise ValueError("mode must be agent, human, or shared")
        self._mode = mode
        self.paused: bool = False
        self.pause_reason: str = ""
        self.intervention: Optional[Dict[str, Any]] = None
        self._resume_event = asyncio.Event()
        self._sync_event()

    # -- state ---------------------------------------------------------

    @property
    def mode(self) -> str:
        return self._mode

    def _sync_event(self) -> None:
        if self.is_agent_allowed():
            self._resume_event.set()
        else:
            self._resume_event.clear()

    # -- checks --------------------------------------------------------

    def is_agent_allowed(self) -> bool:
        return (
            self._mode in ("agent", "shared")
            and not self.paused
            and self.intervention is None
        )

    def is_human_allowed(self) -> bool:
        return self._mode in ("human", "shared")

    def is_allowed(self, actor: str) -> bool:
        if actor == "agent":
            return self.is_agent_allowed()
        if actor == "human":
            return self.is_human_allowed()
        raise ValueError("actor must be agent or human")

    def _blocked_error(self, actor: str) -> ControlModeError:
        if actor == "agent":
            if self._mode == "human":
                return ControlModeError("CONTROL_MODE_HUMAN", self._mode, actor)
            if self.intervention is not None:
                return ControlModeError(
                    "CONTROL_INTERVENTION",
                    self._mode,
                    actor,
                    "CONTROL_INTERVENTION: agent action blocked while an "
                    "intervention is waiting for a human",
                )
            return ControlModeError(
                "CONTROL_PAUSED",
                self._mode,
                actor,
                "CONTROL_PAUSED: agent action blocked while execution is paused",
            )
        return ControlModeError("CONTROL_MODE_AGENT", self._mode, actor)

    def check_agent_allowed(self) -> None:
        if not self.is_agent_allowed():
            raise self._blocked_error("agent")

    def check_human_allowed(self) -> None:
        if not self.is_human_allowed():
            raise self._blocked_error("human")

    def check_allowed(self, actor: str) -> None:
        if actor == "agent":
            self.check_agent_allowed()
        elif actor == "human":
            self.check_human_allowed()
        else:
            raise ValueError("actor must be agent or human")

    # Aliases matching the spike's wording.
    require_agent = check_agent_allowed
    require_human = check_human_allowed

    async def wait_until_agent_allowed(self) -> None:
        """Block until agent actions are allowed (A2 step-boundary hook)."""
        while not self.is_agent_allowed():
            await self._resume_event.wait()

    # -- transitions (only writers of the gated state) -----------------

    def set_mode(self, mode: str) -> str:
        if mode not in VALID_MODES:
            raise ValueError("mode must be agent, human, or shared")
        self._mode = mode
        self._sync_event()
        return self._mode

    def pause(self, reason: str = "manual") -> None:
        self.paused = True
        self.pause_reason = reason
        self._sync_event()

    def resume(self) -> None:
        self.paused = False
        self.pause_reason = ""
        self.intervention = None
        self._sync_event()

    def request_intervention(
        self, reason: str, message: str = "", checkpoint_id: Optional[str] = None
    ) -> Dict[str, Any]:
        self.intervention = {
            "reason": reason,
            "message": message,
            "requested_at": time.time(),
        }
        if checkpoint_id is not None:
            self.intervention["checkpoint_id"] = checkpoint_id
        self._sync_event()
        return self.intervention

    def resolve_intervention(self, note: str = "") -> Optional[Dict[str, Any]]:
        _ = note
        previous = self.intervention
        self.intervention = None
        self._sync_event()
        return previous
