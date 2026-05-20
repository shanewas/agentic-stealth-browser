"""
Session Manager for Agentic Browser
Supports named sessions, anonymous sessions, and isolation
"""

import json
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, List


class SessionManager:
    """Manages browser sessions with isolation"""
    
    def __init__(self, base_dir: str = "~/.agentic-browser/sessions"):
        self.base_dir = Path(base_dir).expanduser()
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def create_session(self, name: Optional[str] = None, anonymous: bool = False) -> Dict:
        """Create a new isolated session"""
        if name is None:
            name = f"session-{uuid.uuid4().hex[:12]}"
        
        if anonymous:
            name = f"anon-{uuid.uuid4().hex[:10]}"
        
        session_path = self.base_dir / name
        session_path.mkdir(exist_ok=True)
        
        meta = {
            "name": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "anonymous": anonymous,
            "user_data_dir": str(session_path / "user_data"),
            "cookies_file": str(session_path / "cookies.json"),
            "state_file": str(session_path / "state.json"),
        }
        
        with open(session_path / "meta.json", "w") as f:
            json.dump(meta, f, indent=2)
        
        return meta
    
    def get_session(self, name: str) -> Optional[Dict]:
        """Load existing session metadata"""
        session_path = self.base_dir / name
        meta_file = session_path / "meta.json"
        if not meta_file.exists():
            return None
        with open(meta_file, "r") as f:
            return json.load(f)
    
    def list_sessions(self) -> List[Dict]:
        """List all sessions"""
        sessions = []
        for meta_file in self.base_dir.glob("*/meta.json"):
            try:
                with open(meta_file, "r") as f:
                    sessions.append(json.load(f))
            except Exception:
                continue
        return sessions
