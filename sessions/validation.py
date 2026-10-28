"""Shared identifier and path-containment validation.

Leaf module (stdlib only, no project imports) so both
``sessions.session_manager`` and ``core.session_checkpoint`` /
``core.agent_browser`` can import it without an import cycle:
``core/__init__`` imports ``core.agent_browser``, which imports
``sessions.session_manager`` -- putting these helpers under ``core/``
would make that chain circular.
"""

from pathlib import Path, PureWindowsPath


def validate_identifier(value: str, *, field: str = "identifier") -> str:
    """Return ``value`` if it is safe as a single path component.

    Rejects empty/blank names, path separators (``/`` and ``\\``),
    ``.``/``..`` segments, absolute or drive-qualified paths, and
    control characters. Raises ``ValueError`` otherwise.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ValueError(f"{field} contains control characters: {value!r}")
    if "/" in value or "\\" in value:
        raise ValueError(f"{field} must not contain path separators: {value!r}")
    if value in (".", "..") or ".." in value:
        raise ValueError(f"{field} must not contain '..': {value!r}")
    if Path(value).is_absolute() or PureWindowsPath(value).drive:
        raise ValueError(f"{field} must not be an absolute path: {value!r}")
    return value


def resolve_contained_path(
    base_dir: str | Path,
    filename: str,
    *,
    required_suffix: str | None = None,
) -> Path:
    """Resolve ``filename`` under ``base_dir`` or raise ``ValueError``.

    Rejects absolute paths, ``..`` components, backslashes, and
    (when given) files without ``required_suffix``. The resolved
    candidate must lie strictly inside the resolved base directory,
    so symlinks cannot escape it either.
    """
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("filename must be a non-empty string")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in filename):
        raise ValueError(f"filename contains control characters: {filename!r}")
    if "\\" in filename:
        raise ValueError(f"filename must not contain backslashes: {filename!r}")
    raw = Path(filename)
    if raw.is_absolute() or PureWindowsPath(filename).drive:
        raise ValueError(f"filename must not be an absolute path: {filename!r}")
    if ".." in raw.parts:
        raise ValueError(f"filename must not contain '..': {filename!r}")
    if required_suffix is not None and raw.suffix != required_suffix:
        raise ValueError(f"filename must end with {required_suffix}: {filename!r}")
    base_resolved = Path(base_dir).resolve()
    candidate = (base_resolved / raw).resolve()
    if candidate == base_resolved or not candidate.is_relative_to(base_resolved):
        raise ValueError(f"filename escapes base directory: {filename!r}")
    return candidate
