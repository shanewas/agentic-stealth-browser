Output assets/hn-demo.gif
Set FontSize 16
Set Width 900
Set Height 520
Set Theme "Dracula"
Set Shell "bash"
Set TypingSpeed 80ms

Type "cd /root/agentic-stealth-browser"
Enter
Sleep 200ms
Type "clear"
Enter
Sleep 300ms

# Show pip install from dist
Type "pip install dist/agentic_stealth_browser-2.1.1-py3-none-any.whl"
Sleep 300ms
Enter
Sleep 4s

# Run the stealth demo
Type "python3 scripts/hn-demo.py"
Sleep 400ms
Enter
Sleep 12s

# Finish
Type "echo ... ready for Show HN"
Enter
Sleep 2s
