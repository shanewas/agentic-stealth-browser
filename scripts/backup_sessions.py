#!/usr/bin/env python3
"""Tar up sessions/ (and checkpoints/ if present) into a timestamped archive.

Usage: python scripts/backup_sessions.py [output_dir]
"""

import argparse
import os
import tarfile


def main() -> None:
    from datetime import datetime

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output_dir", nargs="?", default=".", help="dir to write archive to"
    )
    args = parser.parse_args()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_name = f"backup-sessions-{timestamp}.tar.gz"
    archive_path = os.path.join(args.output_dir, archive_name)

    with tarfile.open(archive_path, "w:gz") as tar:
        if os.path.isdir("sessions"):
            tar.add("sessions")
        if os.path.isdir("checkpoints"):
            tar.add("checkpoints")

    print(archive_path)


if __name__ == "__main__":
    main()
