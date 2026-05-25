#!/usr/bin/env python3
"""Generate a demo GIF showing terminal output for Show HN."""

import subprocess
import sys

# Paths
REPO = "/root/agentic-stealth-browser"

# Step 1: Run asciinema rec with expect-driven input
# Create the expect script
expect_script = """#!/usr/bin/expect -f
set timeout 20
set prompt ">"

# Start asciinema
spawn asciinema rec {output} --overwrite --quiet

# Wait for shell
expect -re {[$#] } {{sleep 0.5}}

# Clear
send "clear\\r"
expect -re {[$#] } {{sleep 0.5}}

# Install
send "pip install dist/agentic_stealth_browser-2.1.1-py3-none-any.whl\\r"
expect -re {[$#] } {{sleep 1}}

# Run demo
send "python3 scripts/hn-demo.py\\r"
expect -re {[$#] } {{sleep 1}}

# Done
send "echo '--- Show HN ready ---'\\r"
expect -re {[$#] } {{sleep 1}}

# Exit
send "exit\\r"
expect eof
"""

import os
os.chdir(REPO)

# Write expect script
with open("/tmp/hn-demo.expect", "w") as f:
    f.write(expect_script)

# Make executable
os.chmod("/tmp/hn-demo.expect", 0o755)

# Run asciinema
cast_file = "/tmp/hn-demo.cast"
result = subprocess.run(
    ["/tmp/hn-demo.expect"],
    env={**os.environ, "output": cast_file},
    capture_output=True,
    text=True,
    timeout=60
)
print("STDOUT:", result.stdout[-500:] if result.stdout else "")
print("STDERR:", result.stderr[-500:] if result.stderr else "")
print("RC:", result.returncode)

if os.path.exists(cast_file):
    print(f"Cast file created: {os.path.getsize(cast_file)} bytes")
    # Convert to GIF
    result2 = subprocess.run(
        ["/tmp/agg", cast_file, f"{REPO}/assets/hn-demo.gif"],
        capture_output=True, text=True, timeout=30
    )
    print("agg:", result2.stdout, result2.stderr)
    if os.path.exists(f"{REPO}/assets/hn-demo.gif"):
        print(f"GIF created: {os.path.getsize(f'{REPO}/assets/hn-demo.gif')} bytes")
    else:
        print("GIF not created")
else:
    print("Cast file not found")
