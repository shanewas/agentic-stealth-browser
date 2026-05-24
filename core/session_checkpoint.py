"""
Session Checkpoint & Export for Resumption
Addresses #62: Add session checkpoint/export for resumption across hosts or restarts.

Provides checkpoint()/resume_from_checkpoint() API that serializes and restores:
- Cookies
- localStorage
- sessionStorage
- Fingerprint state
- Account health state
- Warming state
- Mouse position
- Session metadata
"""

import json
import time
import base64
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field


@dataclass
class CheckpointMetadata:
    """Metadata about a checkpoint."""

    version: str = "1.0"
    created_at: float = 0.0
    account_id: str = ""
    session_id: str = ""
    page_url: str = ""
    page_title: str = ""
    mouse_position: tuple = (0, 0)
    fingerprint_seed: str = ""
    profile_name: str = ""
    total_actions: int = 0
    session_duration_seconds: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "created_at": self.created_at,
            "account_id": self.account_id,
            "session_id": self.session_id,
            "page_url": self.page_url,
            "page_title": self.page_title,
            "mouse_position": list(self.mouse_position),
            "fingerprint_seed": self.fingerprint_seed,
            "profile_name": self.profile_name,
            "total_actions": self.total_actions,
            "session_duration_seconds": self.session_duration_seconds,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CheckpointMetadata":
        return cls(
            version=data.get("version", "1.0"),
            created_at=data.get("created_at", 0),
            account_id=data.get("account_id", ""),
            session_id=data.get("session_id", ""),
            page_url=data.get("page_url", ""),
            page_title=data.get("page_title", ""),
            mouse_position=tuple(data.get("mouse_position", [0, 0])),
            fingerprint_seed=data.get("fingerprint_seed", ""),
            profile_name=data.get("profile_name", ""),
            total_actions=data.get("total_actions", 0),
            session_duration_seconds=data.get("session_duration_seconds", 0.0),
        )


@dataclass
class SessionCheckpoint:
    """Complete session state for checkpointing."""

    metadata: CheckpointMetadata
    cookies: List[Dict[str, Any]] = field(default_factory=list)
    local_storage: Dict[str, str] = field(default_factory=dict)
    session_storage: Dict[str, str] = field(default_factory=dict)
    health_state: Optional[Dict[str, Any]] = None
    warming_state: Optional[Dict[str, Any]] = None
    custom_data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": self.metadata.to_dict(),
            "cookies": self.cookies,
            "local_storage": self.local_storage,
            "session_storage": self.session_storage,
            "health_state": self.health_state,
            "warming_state": self.warming_state,
            "custom_data": self.custom_data,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionCheckpoint":
        return cls(
            metadata=CheckpointMetadata.from_dict(data.get("metadata", {})),
            cookies=data.get("cookies", []),
            local_storage=data.get("local_storage", {}),
            session_storage=data.get("session_storage", {}),
            health_state=data.get("health_state"),
            warming_state=data.get("warming_state"),
            custom_data=data.get("custom_data", {}),
        )

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_json(cls, json_str: str) -> "SessionCheckpoint":
        return cls.from_dict(json.loads(json_str))

    def checksum(self) -> str:
        """Generate checksum for integrity verification."""
        content = json.dumps(self.to_dict(), sort_keys=True)
        return hashlib.sha256(content.encode()).hexdigest()[:16]


class SessionManager:
    """Manages session checkpointing and resumption.

    Usage:
        manager = SessionManager(data_dir="./sessions")

        # Create checkpoint
        checkpoint = manager.create_checkpoint(
            account_id="user123",
            cookies=cookies,
            local_storage=local_storage,
            health_state=health.to_dict(),
        )
        manager.save_checkpoint(checkpoint)

        # Resume from checkpoint
        checkpoint = manager.load_checkpoint("user123_latest.json")
        manager.restore_cookies(page, checkpoint.cookies)
        manager.restore_local_storage(page, checkpoint.local_storage)
    """

    def __init__(self, data_dir: str = "./sessions", logger: Optional[Any] = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._logger = logger

    def create_checkpoint(
        self,
        account_id: str,
        session_id: str = "",
        cookies: Optional[List[Dict[str, Any]]] = None,
        local_storage: Optional[Dict[str, str]] = None,
        session_storage: Optional[Dict[str, str]] = None,
        page_url: str = "",
        page_title: str = "",
        mouse_position: tuple = (0, 0),
        fingerprint_seed: str = "",
        profile_name: str = "",
        total_actions: int = 0,
        session_duration: float = 0.0,
        health_state: Optional[Dict[str, Any]] = None,
        warming_state: Optional[Dict[str, Any]] = None,
        custom_data: Optional[Dict[str, Any]] = None,
    ) -> SessionCheckpoint:
        """Create a new session checkpoint."""
        metadata = CheckpointMetadata(
            created_at=time.time(),
            account_id=account_id,
            session_id=session_id or f"session-{int(time.time())}",
            page_url=page_url,
            page_title=page_title,
            mouse_position=mouse_position,
            fingerprint_seed=fingerprint_seed,
            profile_name=profile_name,
            total_actions=total_actions,
            session_duration_seconds=session_duration,
        )

        return SessionCheckpoint(
            metadata=metadata,
            cookies=cookies or [],
            local_storage=local_storage or {},
            session_storage=session_storage or {},
            health_state=health_state,
            warming_state=warming_state,
            custom_data=custom_data or {},
        )

    async def capture_from_browser(
        self,
        page,
        account_id: str,
        session_id: str = "",
        health_state: Optional[Dict[str, Any]] = None,
        warming_state: Optional[Dict[str, Any]] = None,
        custom_data: Optional[Dict[str, Any]] = None,
    ) -> SessionCheckpoint:
        """Capture current browser state into a checkpoint."""
        # Capture cookies
        cookies = await page.context.cookies() if hasattr(page, "context") else []

        # Capture localStorage
        local_storage = {}
        try:
            local_storage = await page.evaluate("() => { ...localStorage }")
        except Exception:
            pass

        # Capture sessionStorage
        session_storage = {}
        try:
            session_storage = await page.evaluate("() => { ...sessionStorage }")
        except Exception:
            pass

        # Capture current URL and title
        page_url = page.url if hasattr(page, "url") else ""
        page_title = await page.title() if hasattr(page, "title") else ""

        return self.create_checkpoint(
            account_id=account_id,
            session_id=session_id,
            cookies=cookies,
            local_storage=local_storage,
            session_storage=session_storage,
            page_url=page_url,
            page_title=page_title,
            health_state=health_state,
            warming_state=warming_state,
            custom_data=custom_data,
        )

    def save_checkpoint(
        self, checkpoint: SessionCheckpoint, filename: Optional[str] = None
    ) -> Path:
        """Save checkpoint to disk."""
        if filename is None:
            filename = f"{checkpoint.metadata.account_id}_{int(checkpoint.metadata.created_at)}.json"

        filepath = self.data_dir / filename
        with open(filepath, "w") as f:
            f.write(checkpoint.to_json())

        # Also save as latest for easy resumption
        latest_path = self.data_dir / f"{checkpoint.metadata.account_id}_latest.json"
        with open(latest_path, "w") as f:
            f.write(checkpoint.to_json())

        self._log(f"Checkpoint saved: {filepath}")
        return filepath

    def load_checkpoint(self, filename: str) -> SessionCheckpoint:
        """Load checkpoint from disk."""
        filepath = self.data_dir / filename
        if not filepath.exists():
            raise FileNotFoundError(f"Checkpoint not found: {filepath}")

        with open(filepath) as f:
            return SessionCheckpoint.from_json(f.read())

    def load_latest(self, account_id: str) -> Optional[SessionCheckpoint]:
        """Load the latest checkpoint for an account."""
        latest_path = self.data_dir / f"{account_id}_latest.json"
        if not latest_path.exists():
            return None

        with open(latest_path) as f:
            return SessionCheckpoint.from_json(f.read())

    def list_checkpoints(self, account_id: Optional[str] = None) -> List[Path]:
        """List all checkpoints, optionally filtered by account."""
        pattern = f"{account_id}_*.json" if account_id else "*.json"
        return sorted(self.data_dir.glob(pattern))

    async def restore_to_browser(self, page, checkpoint: SessionCheckpoint):
        """Restore checkpoint state to a browser page."""
        # Restore cookies
        await self.restore_cookies(page, checkpoint.cookies)

        # Navigate to checkpoint URL
        if checkpoint.metadata.page_url:
            await page.goto(checkpoint.metadata.page_url)

        # Restore localStorage
        await self.restore_local_storage(page, checkpoint.local_storage)

        # Restore sessionStorage
        await self.restore_session_storage(page, checkpoint.session_storage)

        self._log(f"Restored checkpoint: {checkpoint.metadata.session_id}")

    async def restore_cookies(self, page, cookies: List[Dict[str, Any]]):
        """Restore cookies to browser context."""
        if not cookies:
            return

        context = page.context if hasattr(page, "context") else page
        if hasattr(context, "add_cookies"):
            await context.add_cookies(cookies)

    async def restore_local_storage(self, page, storage: Dict[str, str]):
        """Restore localStorage to page."""
        if not storage:
            return

        try:
            for key, value in storage.items():
                await page.evaluate(f"localStorage.setItem('{key}', '{value}')")
        except Exception as e:
            self._log(f"Failed to restore localStorage: {e}")

    async def restore_session_storage(self, page, storage: Dict[str, str]):
        """Restore sessionStorage to page."""
        if not storage:
            return

        try:
            for key, value in storage.items():
                await page.evaluate(f"sessionStorage.setItem('{key}', '{value}')")
        except Exception as e:
            self._log(f"Failed to restore sessionStorage: {e}")

    def delete_checkpoint(self, filename: str):
        """Delete a checkpoint file."""
        filepath = self.data_dir / filename
        if filepath.exists():
            filepath.unlink()
            self._log(f"Checkpoint deleted: {filepath}")

    def cleanup_old_checkpoints(self, account_id: str, keep: int = 5):
        """Keep only the most recent N checkpoints for an account."""
        checkpoints = self.list_checkpoints(account_id)
        # Exclude _latest.json from count
        checkpoints = [c for c in checkpoints if "_latest.json" not in c.name]

        if len(checkpoints) > keep:
            # Delete oldest
            for old in checkpoints[:-keep]:
                old.unlink()
                self._log(f"Cleaned up old checkpoint: {old}")

    def export_for_transfer(self, checkpoint: SessionCheckpoint) -> str:
        """Export checkpoint as base64 string for transfer across hosts."""
        json_str = checkpoint.to_json()
        encoded = base64.b64encode(json_str.encode()).decode()
        return encoded

    def import_from_transfer(self, encoded: str) -> SessionCheckpoint:
        """Import checkpoint from base64 string."""
        json_str = base64.b64decode(encoded.encode()).decode()
        return SessionCheckpoint.from_json(json_str)

    def _log(self, msg: str):
        """Log a message."""
        if self._logger and hasattr(self._logger, "log_action"):
            self._logger.log_action("session_manager", {"message": msg}, level="info")
        else:
            print(f"[SessionManager] {msg}")
