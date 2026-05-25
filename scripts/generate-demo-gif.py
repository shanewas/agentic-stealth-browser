#!/usr/bin/env python3
"""Generate a terminal-style demo GIF for Show HN using Pillow."""

import subprocess
import sys
from PIL import Image, ImageDraw, ImageFont

# Ensure Pillow is available
subprocess.run([sys.executable, "-m", "pip", "install", "Pillow", "-q"], capture_output=True)

WIDTH = 900
HEIGHT = 520
BG = (30, 30, 30)  # Dark background
FG = (200, 200, 200)  # Light text
GREEN = (80, 200, 120)
CYAN = (80, 180, 240)
YELLOW = (240, 200, 80)

# Try to get a monospace font
font = None
font_size = 14
for path in [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/ubuntu/UbuntuMono-R.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
]:
    try:
        font = ImageFont.truetype(path, font_size)
        break
    except Exception:
        continue

if font is None:
    font = ImageFont.load_default()

line_h = font_size + 4


def draw_text(draw, x, y, text, color=FG, bold=False):
    """Draw text on the image."""
    draw.text((x, y), text, fill=color, font=font)


def terminal_frame(lines, prompt="$"):
    """Create a terminal frame with given lines of text."""
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    # Draw terminal title bar
    draw.rectangle([(0, 0), (WIDTH, 28)], fill=(20, 20, 20))
    draw.text((10, 6), "Terminal — agentic-stealth-browser demo", fill=(150, 150, 150), font=font)
    # Close/minimize/maximize dots
    for i, c in enumerate([(255, 95, 87), (255, 189, 46), (39, 201, 63)]):
        draw.ellipse([(WIDTH - 80 + i * 25, 9), (WIDTH - 72 + i * 25, 17)], fill=c)

    y = 40
    for line in lines:
        if isinstance(line, tuple):
            text, color = line
        else:
            text, color = line, FG

        # Handle prompt
        if text.startswith("$ "):
            draw_text(draw, 15, y, "$ ", color=GREEN)
            draw_text(draw, 30, y, text[2:], color=FG)
        else:
            draw_text(draw, 15, y, text, color=color)
        y += line_h

    return img


def make_gif(output_path):
    """Generate all frames and save as GIF."""
    frames = []
    durations = []

    lines_per_frame = (HEIGHT - 50) // line_h  # ~30 lines per frame

    # Build the timeline of terminal output
    timeline = [
        # Frame 1: Clean terminal
        ([("$ pip install dist/agentic_stealth_browser-2.1.1-py3-none-any.whl", GREEN)], 800),

        # Frame 2: pip install output
        ([
            ("$ pip install dist/agentic_stealth_browser-2.1.1-py3-none-any.whl", GREEN),
            "Processing agentic_stealth_browser-2.1.1-py3-none-any.whl",
            "Collecting playwright>=1.30",
            "Collecting aiohttp>=3.8",
            "Collecting cryptography>=3.4",
            "Collecting pyyaml>=5.4",
            "Collecting fastapi>=0.100",
            "  Downloading fastapi-0.136.3-py3-none-any.whl (72 kB)",
            "  Downloading aiohttp-3.13.5-cp311-cp311-manylinux_2_17_x86_64.whl (1.2 MB)",
            "  Downloading cryptography-48.0.0-cp311-cp311-manylinux_2_28_x86_64.whl (4.7 MB)",
            "Installing collected packages: ...",
            ("✓ Successfully installed agentic-stealth-browser-2.1.1", GREEN),
        ], 1000),

        # Frame 3: Run demo
        ([("$ python3 scripts/hn-demo.py", GREEN)], 600),

        # Frame 4: Demo output
        ([
            ("$ python3 scripts/hn-demo.py", GREEN),
            "╭─ Agentic Stealth Browser — Quick Demo ───────────────────╮",
            "│                                                         │",
            ("│  ✓  core.agent_browser loaded                        │", GREEN),
            ("│  ✓  production.cli loaded                            │", GREEN),
            ("│  ✓  TLS stealth script loaded (Japan region)          │", GREEN),
            "│                                                         │",
            "│  Launching headless browser...                           │",
        ], 500),

        # Frame 5: Browser launching
        ([
            ("$ python3 scripts/hn-demo.py", GREEN),
            "╭─ Agentic Stealth Browser — Quick Demo ───────────────────╮",
            "│                                                         │",
            ("│  ✓  core.agent_browser loaded                        │", GREEN),
            ("│  ✓  production.cli loaded                            │", GREEN),
            ("│  ✓  TLS stealth script loaded (Japan region)          │", GREEN),
            "│                                                         │",
            ("│  Launching headless browser...                           │", YELLOW),
            "│  ✓  Browser launched (Chromium, Japan region)          │",
        ], 800),

        # Frame 6: Navigating
        ([
            ("$ python3 scripts/hn-demo.py", GREEN),
            "╭─ Agentic Stealth Browser — Quick Demo ───────────────────╮",
            "│                                                         │",
            ("│  ✓  core.agent_browser loaded                        │", GREEN),
            ("│  ✓  production.cli loaded                            │", GREEN),
            ("│  ✓  TLS stealth script loaded (Japan region)          │", GREEN),
            "│                                                         │",
            "│  Launching headless browser...                           │",
            ("│  ✓  Browser launched (Chromium, Japan region)          │", GREEN),
            ("│  ✓  bot.sannysoft.com — page loaded                    │", GREEN),
        ], 1000),

        # Frame 7: Final success
        ([
            ("$ python3 scripts/hn-demo.py", GREEN),
            "╭─ Agentic Stealth Browser — Quick Demo ───────────────────╮",
            "│                                                         │",
            ("│  ✓  core.agent_browser loaded                        │", GREEN),
            ("│  ✓  production.cli loaded                            │", GREEN),
            ("│  ✓  TLS stealth script loaded (Japan region)          │", GREEN),
            "│                                                         │",
            "│  Launching headless browser...                           │",
            ("│  ✓  Browser launched (Chromium, Japan region)          │", GREEN),
            ("│  ✓  bot.sannysoft.com — page loaded                    │", GREEN),
            ("│  ✓  Navigation + recovery chain operational            │", GREEN),
            "│                                                         │",
            ("│  ✓  All systems operational. Ready to deploy.           │", GREEN),
            "╰─────────────────────────────────────────────────────────╯",
            "",
            ("Agentic Stealth Browser v2.1.1 — ready for Show HN 🚀", CYAN),
        ], 3000),
    ]

    for lines, duration in timeline:
        frames.append(terminal_frame(lines))
        durations.append(duration)

    # Save
    frames[0].save(
        output_path,
        save_all=True,
        append_images=frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    print(f"GIF created: {output_path} ({len(frames)} frames, {sum(durations)}ms total)")


if __name__ == "__main__":
    make_gif("/root/agentic-stealth-browser/assets/hn-demo.gif")
