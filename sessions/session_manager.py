"""
Session Manager for Agentic Browser
Supports named sessions, anonymous sessions, and isolation

#87 (multi-instance isolation):
  Each session *name* provides fully independent on-disk state:
    - user_data/   (full browser profile: cache, localStorage, IndexedDB, etc.)
    - cookies.json
    - state.json
    - meta.json

  This delivers strong *filesystem-level* isolation for different logical
  agents, accounts, or fleet members.

**STRONG MULTI-INSTANCE WARNINGS (P1 #87):**

  Rate limiters, metrics collectors, stealth profiles, and other
  process-global singletons remain SHARED across ALL sessions that live
  inside the same Python interpreter / process.

  Merely using distinct session names inside one process does NOT isolate:
    - rate limiting state (risk of one account's traffic affecting another's)
    - metrics (cross-contamination of counters/gauges)
    - certain in-memory caches or fingerprint state

  Running multiple AgentBrowser (or equivalent) instances that target
  different accounts/identities from within a SINGLE PROCESS is unsafe
  and can cause blocks, account linkage, or incorrect observability.

  FOR ANY REAL MULTI-AGENT / MULTI-ACCOUNT / PARALLEL WORKLOADS:
    Use SEPARATE PROCESSES or separate containers (Docker, etc.).
    This is the only reliable way to achieve end-to-end isolation today.

  Recommendation: one dedicated OS process (or container) per session/account.
  Threads / concurrent asyncio tasks inside one interpreter are insufficient.

  Always pick stable, unique, human-meaningful names per identity
  (e.g. "linkedin-alice", "twitter-bob-prod").
"""

import json
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any


class SessionManager:
    """Manages browser sessions with isolation (#87: see module header for strong multi-instance warnings)"""
    
    def __init__(self, base_dir: str = "~/.agentic-browser/sessions"):
        self.base_dir = Path(base_dir).expanduser()
        self.base_dir.mkdir(parents=True, exist_ok=True)
    
    def create_session(self, name: Optional[str] = None, anonymous: bool = False, ephemeral: bool = False) -> Dict:
        """Create a new isolated session.

        When a name is supplied it is used verbatim (caller is responsible
        for uniqueness across accounts). Anonymous sessions receive random
        names.

        ephemeral=True (P2 #278): tags the session for throwaway use.
        Ephemeral sessions are auto-prunable and cleaned up on AgentBrowser.close()
        when using the ephemeral flag. They still use the standard isolated dir
        layout for full compatibility with cookies/state, but are intended for
        short one-off tasks.

        See module docstring for critical #87 multi-instance isolation
        warnings and the process/container separation requirement.
        """
        if name is None:
            name = f"session-{uuid.uuid4().hex[:12]}"
        
        if anonymous:
            name = f"anon-{uuid.uuid4().hex[:10]}"
        
        if ephemeral:
            prefix = "ephemeral-"
            if not name.startswith(prefix):
                name = prefix + name
        
        session_path = self.base_dir / name
        session_path.mkdir(exist_ok=True)
        
        meta = {
            "name": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "anonymous": anonymous,
            "ephemeral": ephemeral,
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

    def prune_ephemeral(self, max_age_hours: Optional[int] = None) -> Dict[str, Any]:
        """Prune (delete) all sessions tagged as ephemeral (#278 throwaway support).

        Useful for cleanup of one-off / A/B test sessions.
        If max_age_hours is provided, only prune ephemerals older than that.
        Always safe (ignores missing dirs).

        Returns summary with count of removed sessions.
        """
        removed = 0
        errors = []
        now = datetime.now(timezone.utc)
        for meta_file in self.base_dir.glob("*/meta.json"):
            try:
                with open(meta_file, "r") as f:
                    meta = json.load(f)
                if not meta.get("ephemeral"):
                    continue
                if max_age_hours is not None:
                    created = meta.get("created_at")
                    if created:
                        try:
                            created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                            age_h = (now - created_dt).total_seconds() / 3600
                            if age_h < max_age_hours:
                                continue
                        except Exception:
                            pass
                session_path = meta_file.parent
                import shutil
                shutil.rmtree(session_path, ignore_errors=True)
                removed += 1
            except Exception as e:
                errors.append(str(e))
                continue
        return {
            "status": "success",
            "removed": removed,
            "errors": len(errors),
            "max_age_hours": max_age_hours,
        }

    def clone_session(self, source_name: str, new_name: Optional[str] = None, copy_user_data: bool = False) -> Dict[str, Any]:
        """Clone or fork an existing session for A/B testing or shadow runs (#261).

        Creates a new independent session entry.
        - Always copies cookies.json and state.json if present (lightweight, sufficient for most A/B).
        - If copy_user_data=True, recursively copies the entire user_data/ dir (full fidelity but I/O heavy; use sparingly).

        Returns the new session meta dict.
        Original session is untouched. New session gets its own meta with "cloned_from".
        """
        import shutil
        src_meta = self.get_session(source_name)
        if not src_meta:
            return {"status": "error", "message": f"Source session not found: {source_name}"}

        if new_name is None:
            new_name = f"clone-{uuid.uuid4().hex[:8]}-of-{source_name}"

        # ensure not colliding
        if (self.base_dir / new_name).exists():
            new_name = f"{new_name}-{uuid.uuid4().hex[:4]}"

        new_meta = self.create_session(new_name, anonymous=src_meta.get("anonymous", False))
        new_path = self.base_dir / new_name
        src_path = self.base_dir / source_name

        # copy key state files (cookies + state) for functional clone
        for fname in ("cookies.json", "state.json", "meta.json"):
            src_f = src_path / fname
            if src_f.exists():
                try:
                    shutil.copy2(src_f, new_path / fname)
                except Exception:
                    pass

        # optional deep user_data copy (caches, localStorage, etc for full shadow)
        if copy_user_data:
            src_ud = src_path / "user_data"
            dst_ud = new_path / "user_data"
            if src_ud.exists():
                try:
                    shutil.copytree(src_ud, dst_ud, dirs_exist_ok=True)
                except Exception:
                    pass

        # update meta to record provenance
        try:
            with open(new_path / "meta.json", "r") as f:
                m = json.load(f)
            m["cloned_from"] = source_name
            m["cloned_at"] = datetime.now(timezone.utc).isoformat()
            m["clone_full_user_data"] = bool(copy_user_data)
            with open(new_path / "meta.json", "w") as f:
                json.dump(m, f, indent=2)
            new_meta.update(m)
        except Exception:
            pass

        return {"status": "success", "new_session": new_meta, "source": source_name, "full_copy": copy_user_data}


# Basic isolation helper for #87 (additive, zero breaking changes)
def create_isolated_session(
    name: Optional[str] = None,
    anonymous: bool = False,
    ephemeral: bool = False,
    base_dir: str = "~/.agentic-browser/sessions",
) -> Dict:
    """Basic isolation helper targeting P1 #87 + P2 #278 ephemeral.

    Returns session metadata for a dedicated on-disk profile
    (user_data + cookies + state). This is the supported way to obtain
    filesystem isolation for distinct logical agents.

    ephemeral=True creates a throwaway tagged session (auto-prunable).

    All the strong multi-instance warnings from the module docstring apply:
    use separate processes/containers for true safety when operating
    multiple accounts in parallel.

    This helper exists so callers can be explicit about isolation intent
    without needing to construct SessionManager themselves.
    """
    return SessionManager(base_dir=base_dir).create_session(
        name=name, anonymous=anonymous, ephemeral=ephemeral
    )
