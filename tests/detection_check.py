"""
Basic Detection Evasion Checklist
Run this to verify stealth effectiveness
"""

DETECTION_VECTORS = [
    "navigator.webdriver",
    "navigator.plugins length",
    "WebGL vendor/renderer",
    "Canvas fingerprint",
    "AudioContext fingerprint",
    "hardwareConcurrency",
    "deviceMemory",
    "Permissions API",
    "WebRTC local IP leak",
    "Mouse movement patterns",
    "Typing rhythm consistency",
    "Header consistency",
    "TLS fingerprint",
]

def print_checklist():
    print("=== Detection Evasion Checklist ===")
    for v in DETECTION_VECTORS:
        print(f"[ ] {v}")
    print("\nRun actual browser tests against these vectors.")


if __name__ == "__main__":
    print_checklist()
