#!/usr/bin/env python3
"""Generate a demo GIF showing terminal output for Show HN."""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _tcl_escape(value: str) -> str:
    """Escape a string for use as a bare Tcl word (no braces)."""
    out = []
    for ch in value:
        if ch in '\\"$[]{}; \t\n':
            out.append("\\" + ("n" if ch == "\n" else "t" if ch == "\t" else ch))
        else:
            out.append(ch)
    return "".join(out)


def build_expect_script(output_path, repo=REPO) -> str:
    """Build the expect script recording to *output_path* (real path, no braces)."""
    cast = _tcl_escape(str(output_path))
    return f"""#!/usr/bin/expect -f
set timeout 20
set prompt ">"

spawn asciinema rec {cast} --overwrite --quiet
expect -re {{[$#] }} {{sleep 0.5}}
send "clear\\r"
expect -re {{[$#] }} {{sleep 0.5}}
send "pip install dist/agentic_stealth_browser-2.1.1-py3-none-any.whl\\r"
expect -re {{[$#] }} {{sleep 1}}
send "python3 scripts/hn-demo.py\\r"
expect -re {{[$#] }} {{sleep 1}}
send "echo '--- Show HN ready ---'\\r"
expect -re {{[$#] }} {{sleep 1}}
send "exit\\r"
expect eof
"""


def write_expect_script(output_path, repo=REPO) -> Path:
    """Write the expect script to a non-predictable, privately-created temp file."""
    fd, name = tempfile.mkstemp(prefix="hn-demo-", suffix=".expect")
    # mkstemp creates the file with 0o600; do not widen permissions.
    with open(fd, "w", encoding="utf-8") as f:
        f.write(build_expect_script(output_path, repo=repo))
    return Path(name)


def main(runner=subprocess.run, cast_file=None, gif_path=None, repo=REPO) -> int:
    repo = Path(repo)
    if cast_file is None:
        fd, name = tempfile.mkstemp(prefix="hn-demo-", suffix=".cast")
        os.close(fd)
        cast_file = Path(name)
    else:
        cast_file = Path(cast_file)
    gif_path = Path(gif_path) if gif_path is not None else repo / "assets" / "hn-demo.gif"
    expect_path = write_expect_script(cast_file, repo=repo)
    try:
        try:
            result = runner(
                ["expect", str(expect_path)],
                cwd=str(repo),
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"Recording failed: {exc}", file=sys.stderr)
            return 1
        print("STDOUT:", result.stdout[-500:] if result.stdout else "")
        print("STDERR:", result.stderr[-500:] if result.stderr else "")
        print("RC:", result.returncode)
        if result.returncode != 0:
            print("Recording failed", file=sys.stderr)
            return 1
        if not cast_file.exists():
            print("Cast file not found", file=sys.stderr)
            return 1
        print(f"Cast file created: {cast_file.stat().st_size} bytes")
        gif_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            result2 = runner(
                ["/tmp/agg", str(cast_file), str(gif_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"GIF conversion failed: {exc}", file=sys.stderr)
            return 1
        print("agg:", result2.stdout, result2.stderr)
        if result2.returncode != 0 or not gif_path.exists():
            print("GIF not created", file=sys.stderr)
            return 1
        print(f"GIF created: {gif_path.stat().st_size} bytes")
        return 0
    finally:
        expect_path.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
