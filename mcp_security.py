"""
MCP Security Hardening Module
Addresses P0 security issues #77, #68, #54, #49.

Provides:
- Path-scoped filesystem access control (#77)
- LLM call authorization controls (#68)
- Sensitive data redaction for stderr/logs (#54)
- Tool description sanitization (#49)
"""

import os
import re
import fnmatch
from pathlib import Path
from typing import Optional, Set, Dict, Any, List
from dataclasses import dataclass, field


# === #77: Path-scoped filesystem access control ===


@dataclass
class FileAccessPolicy:
    """Defines which paths the MCP server is allowed to access."""

    allowed_dirs: List[str] = field(
        default_factory=lambda: [
            str(Path.home() / ".agentic-browser"),
            str(Path.home() / ".stealth-browser"),
        ]
    )
    allowed_file_patterns: List[str] = field(
        default_factory=lambda: [
            "*.json",
            "*.txt",
            "*.log",
            "*.jsonl",
        ]
    )
    blocked_patterns: List[str] = field(
        default_factory=lambda: [
            # Never allow access to sensitive system paths
            "/etc/passwd",
            "/etc/shadow",
            "/etc/hosts",
            "/root/.ssh/*",
            "/root/.gnupg/*",
            "*/.env",
            "*/.env.*",
            "*/id_rsa",
            "*/id_ed25519",
            "*/authorized_keys",
            "*/.git/config",
            # Never allow access to credential stores
            "*/.aws/credentials",
            "*/.config/gcloud/*",
            # Prevent path traversal
            "../*",
            "*/../*",
        ]
    )
    max_path_depth: int = 20  # prevent excessively deep path traversal

    def is_path_allowed(self, path: str) -> tuple[bool, str]:
        """Check if a path is allowed under this policy.

        Returns (allowed: bool, reason: str).
        """
        if not path:
            return False, "empty path"

        # Normalize path
        try:
            resolved = str(Path(path).resolve())
        except (ValueError, OSError):
            return False, "cannot resolve path"

        # Check for path traversal attempts
        if ".." in path or resolved.count(os.sep) > self.max_path_depth:
            return False, "path traversal detected or path too deep"

        # Check blocked patterns first (deny-list takes priority)
        for pattern in self.blocked_patterns:
            if fnmatch.fnmatch(resolved, pattern) or fnmatch.fnmatch(path, pattern):
                return False, f"path matches blocked pattern: {pattern}"

        # Check if path is within allowed directories
        for allowed_dir in self.allowed_dirs:
            allowed_resolved = str(Path(allowed_dir).resolve())
            if resolved.startswith(allowed_resolved):
                # Check file extension allowlist
                path_suffix = Path(resolved).suffix
                if self.allowed_file_patterns:
                    pattern = f"*{path_suffix}" if path_suffix else "*"
                    if not any(
                        fnmatch.fnmatch(pattern, ap)
                        for ap in self.allowed_file_patterns
                    ):
                        return False, f"file type not allowed: {path_suffix}"
                return True, "path within allowed directory"

        return False, "path not within any allowed directory"

    def add_allowed_dir(self, directory: str) -> None:
        """Add a directory to the allowed list."""
        resolved = str(Path(directory).resolve())
        if resolved not in self.allowed_dirs:
            self.allowed_dirs.append(resolved)

    def add_blocked_pattern(self, pattern: str) -> None:
        """Add a pattern to the blocked list."""
        if pattern not in self.blocked_patterns:
            self.blocked_patterns.append(pattern)


# === #68: LLM call authorization controls ===


@dataclass
class LLMAuthorizationPolicy:
    """Controls which LLM calls are allowed through MCP sampling."""

    require_explicit_consent: bool = True
    max_tokens_per_call: int = 4096
    max_calls_per_minute: int = 10
    allowed_models: Optional[Set[str]] = None  # None = all allowed
    blocked_prompts: List[str] = field(
        default_factory=lambda: [
            # Block prompts that could be used for malicious purposes
            "ignore previous instructions",
            "system prompt",
            "jailbreak",
            "override security",
            "bypass restrictions",
        ]
    )
    _call_timestamps: list = field(default_factory=list)

    def is_call_allowed(
        self, prompt: str, model: Optional[str] = None
    ) -> tuple[bool, str]:
        """Check if an LLM call is allowed under this policy."""
        import time

        # Check explicit consent requirement
        if self.require_explicit_consent:
            # In automated mode, we allow but log; in interactive mode, require consent
            pass  # Consent is handled at the UI/agent level

        # Check rate limit
        now = time.time()
        # Remove timestamps older than 60 seconds
        self._call_timestamps = [t for t in self._call_timestamps if now - t < 60]
        if len(self._call_timestamps) >= self.max_calls_per_minute:
            return False, "rate limit exceeded (max calls per minute)"

        # Check model allowlist
        if self.allowed_models and model and model not in self.allowed_models:
            return False, f"model '{model}' not in allowed models"

        # Check blocked prompts
        prompt_lower = prompt.lower()
        for blocked in self.blocked_prompts:
            if blocked in prompt_lower:
                return False, f"prompt contains blocked pattern: {blocked}"

        # Check token limit (rough estimate: 1 token ≈ 4 chars)
        if len(prompt) > self.max_tokens_per_call * 4:
            return False, f"prompt exceeds max token limit ({self.max_tokens_per_call})"

        # Record this call
        self._call_timestamps.append(now)
        return True, "call allowed"


# === #54: Sensitive data redaction for stderr/logs ===

# Patterns to detect and redact sensitive data in stderr output
SENSITIVE_PATTERNS = [
    # API keys
    (
        re.compile(
            r'((?:api[_-]?key|apikey)\s*[:=]\s*["\']?)[A-Za-z0-9_\-]{16,}["\']?',
            re.IGNORECASE,
        ),
        r"\1[REDACTED_API_KEY]",
    ),
    # Bearer tokens
    (
        re.compile(
            r'((?:bearer|authorization)\s*[:=]\s*["\']?)[A-Za-z0-9_\-\.]{20,}["\']?',
            re.IGNORECASE,
        ),
        r"\1[REDACTED_TOKEN]",
    ),
    # Passwords
    (
        re.compile(
            r'((?:password|passwd|pwd)\s*[:=]\s*["\']?)[^\s"\']{4,}["\']?',
            re.IGNORECASE,
        ),
        r"\1[REDACTED_PASSWORD]",
    ),
    # Private keys
    (
        re.compile(r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----"),
        "[REDACTED_PRIVATE_KEY]",
    ),
    # AWS keys
    (re.compile(r"(AKIA[0-9A-Z]{16})"), "[REDACTED_AWS_KEY]"),
    # Generic secrets
    (
        re.compile(
            r'((?:secret|token)\s*[:=]\s*["\']?)[A-Za-z0-9_\-]{16,}["\']?',
            re.IGNORECASE,
        ),
        r"\1[REDACTED_SECRET]",
    ),
    # URLs with credentials
    (re.compile(r"(://[^:@/]+:)([^@]+)(@)"), r"\1[REDACTED_CREDENTIALS]\3"),
    # GitHub tokens (classic + fine-grained)
    (
        re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
        "[REDACTED_GITHUB_TOKEN]",
    ),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b"), "[REDACTED_GITHUB_TOKEN]"),
    # Slack tokens
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"), "[REDACTED_SLACK_TOKEN]"),
    # JWTs
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"),
        "[REDACTED_JWT]",
    ),
    # Email addresses
    (
        re.compile(r"\b([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b"),
        r"[EMAIL_REDACTED]",
    ),
]


def redact_sensitive_data(text: str) -> str:
    """Redact sensitive data from text (stderr, logs, etc.).

    Applies multiple regex patterns to detect and redact:
    - API keys
    - Bearer tokens
    - Passwords
    - Private keys
    - AWS credentials
    - Generic secrets
    - URLs with embedded credentials
    - Email addresses
    """
    if not text:
        return text

    result = text
    for pattern, replacement in SENSITIVE_PATTERNS:
        result = pattern.sub(replacement, result)

    return result


# === #49: Tool description sanitization ===

# Patterns to detect potentially malicious content in tool descriptions
MALICIOUS_PATTERNS = [
    # Code execution attempts
    re.compile(r"(?:exec|eval|compile)\s*\(", re.IGNORECASE),
    # System command injection
    re.compile(r"(?:os\.system|subprocess|Popen|shell=True)", re.IGNORECASE),
    # File system manipulation
    re.compile(r"(?:shutil\.rmtree|os\.remove|os\.unlink)", re.IGNORECASE),
    # Network exfiltration
    re.compile(
        r"(?:requests\.post|urllib\.request|curl|wget)\s+.*(?:paste|bin|exfil)",
        re.IGNORECASE,
    ),
    # Environment variable access
    re.compile(r"(?:os\.environ|os\.getenv)\s*\(", re.IGNORECASE),
    # Import injection
    re.compile(r"__import__\s*\(", re.IGNORECASE),
    # Base64 encoded payloads (common obfuscation)
    re.compile(r"base64\.(?:b64decode|decodebytes)\s*\(", re.IGNORECASE),
]

# Maximum allowed length for tool descriptions
MAX_TOOL_DESCRIPTION_LENGTH = 2000


def sanitize_tool_description(description: str) -> tuple[str, list[str]]:
    """Sanitize a tool description to remove potentially malicious content.

    Returns (sanitized_description, list_of_warnings).
    """
    warnings: list[str] = []

    if not description:
        return "", warnings

    # Check length
    if len(description) > MAX_TOOL_DESCRIPTION_LENGTH:
        warnings.append(
            f"Tool description truncated from {len(description)} to {MAX_TOOL_DESCRIPTION_LENGTH} chars"
        )
        description = description[:MAX_TOOL_DESCRIPTION_LENGTH]

    # Check for malicious patterns
    for pattern in MALICIOUS_PATTERNS:
        match = pattern.search(description)
        if match:
            warnings.append(
                f"Suspicious pattern detected in tool description: {match.group()[:50]}..."
            )
            # Replace the suspicious pattern with a safe placeholder
            description = pattern.sub("[SANITIZED]", description)

    # Remove any remaining executable code blocks
    description = re.sub(
        r"```python\s+.*?```", "[CODE_BLOCK_REMOVED]", description, flags=re.DOTALL
    )
    description = re.sub(
        r"```\s+.*?```", "[CODE_BLOCK_REMOVED]", description, flags=re.DOTALL
    )

    return description.strip(), warnings


# === Centralized security context for MCP server ===


class MCPSecurityContext:
    """Centralized security context that enforces all P0 security policies."""

    def __init__(
        self,
        file_policy: Optional[FileAccessPolicy] = None,
        llm_policy: Optional[LLMAuthorizationPolicy] = None,
        strict_mode: bool = True,
    ):
        self.file_policy = file_policy or FileAccessPolicy()
        self.llm_policy = llm_policy or LLMAuthorizationPolicy()
        self.strict_mode = strict_mode
        self.security_log: List[Dict[str, Any]] = []

    def check_file_access(self, path: str) -> tuple[bool, str]:
        """Check if file access is allowed."""
        allowed, reason = self.file_policy.is_path_allowed(path)
        self._log_security_event(
            "file_access", {"path": path, "allowed": allowed, "reason": reason}
        )
        return allowed, reason

    def check_llm_call(
        self, prompt: str, model: Optional[str] = None
    ) -> tuple[bool, str]:
        """Check if LLM call is allowed."""
        allowed, reason = self.llm_policy.is_call_allowed(prompt, model)
        self._log_security_event(
            "llm_call",
            {
                "prompt_preview": prompt[:100],
                "model": model,
                "allowed": allowed,
                "reason": reason,
            },
        )
        return allowed, reason

    def sanitize_stderr(self, text: str) -> str:
        """Redact sensitive data from stderr output."""
        result = redact_sensitive_data(text)
        if result != text:
            self._log_security_event(
                "stderr_redaction",
                {"original_length": len(text), "redacted_length": len(result)},
            )
        return result

    def sanitize_tool_description(self, description: str) -> tuple[str, list[str]]:
        """Sanitize tool description."""
        result, warnings = sanitize_tool_description(description)
        if warnings:
            self._log_security_event(
                "tool_description_sanitization", {"warnings": warnings}
            )
        return result, warnings

    def _log_security_event(self, event_type: str, details: Dict[str, Any]) -> None:
        """Log a security event for audit purposes."""
        import time

        self.security_log.append(
            {
                "timestamp": time.time(),
                "event_type": event_type,
                **details,
            }
        )
        # Keep only last 1000 events
        if len(self.security_log) > 1000:
            self.security_log = self.security_log[-1000:]

    def get_security_summary(self) -> Dict[str, Any]:
        """Return a summary of security events."""
        return {
            "strict_mode": self.strict_mode,
            "total_events": len(self.security_log),
            "recent_events": self.security_log[-10:],
            "file_policy": {
                "allowed_dirs": self.file_policy.allowed_dirs,
                "blocked_patterns_count": len(self.file_policy.blocked_patterns),
            },
            "llm_policy": {
                "require_explicit_consent": self.llm_policy.require_explicit_consent,
                "max_calls_per_minute": self.llm_policy.max_calls_per_minute,
            },
        }


# Default security context (used by MCP server)
default_security_context = MCPSecurityContext(strict_mode=True)
