"""
Session Manager for Agentic Browser
Supports named sessions, anonymous sessions, and isolation

#87 multi-instance isolation (final closer): FS-level isolation per session name for
user_data, cookies, state. Complements AgentBrowser per-instance rate_limiter/metrics.
Basic guidance + warnings:
- Always pass unique session_name (or let it auto-generate) per logical agent/account.
- Concurrent AgentBrowsers in one process still share some globals (network, some recovery).
- For production fleets: run one AgentBrowser (or process) per identity, or use containers.
- See AgentBrowser class docstring for constructor options to share/coordinate limiters.
"""

import json
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any


class SessionManager:
    """Manages browser sessions with isolation (#87: FS isolation; pair with AgentBrowser instance isolation for rate/metrics)"""
    
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

    def cleanup_session(self, name: str, remove_dir: bool = False) -> Dict[str, Any]:
        """Mark or remove a session as compromised (addresses P1 #90 cookie/session cleanup on account restriction).

        Prevents accidental reuse of stale/compromised cookies after ACCOUNT_RESTRICTION detection.
        Default: marks the session meta with 'compromised' flag (safe, reversible).
        With remove_dir=True: hard delete of the entire session directory (use with caution).
        """
        session_path = self.base_dir / name
        if not session_path.exists():
            return {"status": "not_found", "name": name}

        meta_file = session_path / "meta.json"
        marked = False
        if meta_file.exists():
            try:
                with open(meta_file, "r") as f:
                    meta = json.load(f)
                meta["compromised"] = True
                meta["cleaned_at"] = datetime.now(timezone.utc).isoformat()
                meta["cleanup_reason"] = "account_restriction_or_compromise"
                with open(meta_file, "w") as f:
                    json.dump(meta, f, indent=2)
                marked = True
            except Exception:
                pass

        if remove_dir:
            try:
                import shutil
                shutil.rmtree(session_path, ignore_errors=True)
                return {"status": "removed", "name": name, "marked": marked}
            except Exception as e:
                return {"status": "partial", "name": name, "marked": marked, "error": str(e)}

        return {"status": "marked_compromised", "name": name}
