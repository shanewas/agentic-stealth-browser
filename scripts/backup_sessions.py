#!/usr/bin/env python3
"""Tar up sessions/ (and checkpoints/ if present) into a timestamped archive.

Usage: python scripts/backup_sessions.py [output_dir]

Source directories are resolved relative to the repo root (this script's
parent directory), not the caller's working directory. If neither source
exists, or both contain no files, the script fails non-zero before
creating any archive — an empty tar is not a successful backup.
"""

import argparse
import os
import sys
import tarfile
from datetime import datetime
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _source_dirs(root: Path) -> list[Path]:
    return [
        root / name
        for name in ("sessions", "checkpoints")
        if (root / name).is_dir()
    ]


def _has_files(directories: list[Path]) -> bool:
    return any(
        path.is_file()
        for directory in directories
        for path in directory.rglob("*")
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output_dir", nargs="?", default=".", help="dir to write archive to"
    )
    args = parser.parse_args(argv)

    sources = _source_dirs(_repo_root())
    if not sources or not _has_files(sources):
        print(
            "No session data to back up: neither sessions/ nor checkpoints/ "
            f"under {_repo_root()} exists or contains any files.",
            file=sys.stderr,
        )
        return 1

    # Microsecond resolution: two runs in the same second must not
    # truncate each other's archive (L4).
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    archive_name = f"backup-sessions-{timestamp}.tar.gz"
    archive_path = os.path.join(args.output_dir, archive_name)

    with tarfile.open(archive_path, "w:gz") as tar:
        for source in sources:
            tar.add(source, arcname=source.name)

    print(archive_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
