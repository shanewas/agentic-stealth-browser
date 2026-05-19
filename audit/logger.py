"""
Audit & Logging System for Agentic Browser
Production-grade logging for reliability and service offering
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional


class AuditLogger:
    """
    Comprehensive logging system for agentic browser operations.
    Supports both file logging and structured JSON audit trails.
    """
    
    def __init__(self, session_name: str, log_dir: str = "~/.agentic-browser/logs"):
        self.session_name = session_name
        self.log_dir = Path(log_dir).expanduser()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Structured audit log
        self.audit_file = self.log_dir / f"{session_name}_audit.jsonl"
        
        # Human-readable log
        self.log_file = self.log_dir / f"{session_name}.log"
        
        # Setup standard logger
        self.logger = logging.getLogger(f"agentic.{session_name}")
        self.logger.setLevel(logging.INFO)
        
        handler = logging.FileHandler(self.log_file)
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
    
    def log_action(self, action: str, details: Optional[Dict] = None, level: str = "info"):
        """Log a browser action with structured data"""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "session": self.session_name,
            "action": action,
            "details": details or {},
        }
        
        # Write to JSONL audit trail
        with open(self.audit_file, "a") as f:
            f.write(json.dumps(entry) + "\n")
        
        # Also log to human-readable log
        msg = f"{action}"
        if details:
            msg += f" | {details}"
        
        if level == "error":
            self.logger.error(msg)
        elif level == "warning":
            self.logger.warning(msg)
        else:
            self.logger.info(msg)
    
    def log_error(self, action: str, error: str, details: Optional[Dict] = None):
        """Log errors with full context"""
        self.log_action(action, {
            "error": error,
            **(details or {})
        }, level="error")
    
    def log_block_detected(self, platform: str, details: Optional[Dict] = None):
        """Special logging for blocks / rate limits"""
        self.log_action("BLOCK_DETECTED", {
            "platform": platform,
            **(details or {})
        }, level="warning")
    
    def get_recent_actions(self, limit: int = 50) -> list:
        """Read recent audit entries"""
        if not self.audit_file.exists():
            return []
        
        entries = []
        with open(self.audit_file) as f:
            for line in f:
                if line.strip():
                    entries.append(json.loads(line))
        
        return entries[-limit:]
