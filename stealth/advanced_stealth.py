"""
Advanced Stealth Module for Agentic Browsers
Production-grade fingerprint spoofing + anti-detection
"""

import random
from typing import Dict, Any

class StealthConfig:
    """Consistent high-quality fingerprint profile"""
    
    # Stable fingerprint (looks like a real mid-range Windows laptop)
    HARDWARE = {
        "hardwareConcurrency": 8,
        "deviceMemory": 8,
        "platform": "Win32",
    }
    
    WEBGL = {
        "vendor": "Intel Inc.",
        "renderer": "Intel(R) UHD Graphics 620",
        "version": "WebGL 1.0 (OpenGL ES 2.0 Chromium)",
    }
    
    SCREEN = {
        "colorDepth": 24,
        "pixelDepth": 24,
    }
    
    LANGUAGES = ["en-US", "en"]
    
    PLUGINS = [
        {"name": "PDF Viewer", "filename": "internal-pdf-viewer"},
        {"name": "Chrome PDF Viewer", "filename": "mhjfbmdgcfjbbpaeojofohoefgiehjai"},
        {"name": "Chromium PDF Viewer", "filename": "mhjfbmdgcfjbbpaeojofohoefgiehjai"},
    ]


def get_stealth_script(profile: str = "windows_laptop") -> str:
    """
    Returns a comprehensive stealth injection script.
    Designed to be injected via browser.add_init_script()
    """
    
    script = """
    // === Advanced Agentic Stealth v0.2 ===
    
    // Core anti-detection
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    
    // Hardware fingerprint (consistent)
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
    Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
    Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
    
    // Languages
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    Object.defineProperty(navigator, 'language', { get: () => 'en-US' });
    
    // Chrome runtime
    if (!window.chrome) {
        window.chrome = { runtime: {}, app: { isInstalled: false } };
    }
    
    // Canvas protection (character substitution)
    const origGetContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(type, attrs) {
        const ctx = origGetContext.call(this, type, attrs);
        if (ctx && (type === '2d' || type === 'webgl' || type === 'webgl2')) {
            const origFill = ctx.fillText;
            ctx.fillText = function(str, x, y, maxW) {
                if (typeof str === 'string') {
                    str = str.replace(/[0-9]/g, d => String.fromCharCode(97 + (parseInt(d) % 26)));
                }
                return origFill.call(this, str, x, y, maxW);
            };
        }
        return ctx;
    };
    
    // WebGL fingerprint (Intel UHD - very common)
    const getParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(p) {
        if (p === 37445) return 'Intel Inc.';
        if (p === 37446) return 'Intel(R) UHD Graphics 620';
        if (p === 37447) return 'WebGL 1.0 (OpenGL ES 2.0 Chromium)';
        return getParam.apply(this, arguments);
    };
    
    // AudioContext noise
    const AudioC = window.AudioContext || window.webkitAudioContext;
    if (AudioC) {
        const origCreate = AudioC.prototype.createAnalyser;
        AudioC.prototype.createAnalyser = function() {
            const a = origCreate.call(this);
            const origGet = a.getFloatFrequencyData;
            a.getFloatFrequencyData = function(arr) {
                origGet.call(this, arr);
                for (let i = 0; i < arr.length; i += 4) {
                    arr[i] *= 0.996 + Math.random() * 0.008;
                }
                return arr;
            };
            return a;
        };
    }
    
    // Permissions
    const origQuery = navigator.permissions.query;
    navigator.permissions.query = (p) => {
        if (p.name === 'notifications') return Promise.resolve({ state: 'default' });
        return origQuery(p);
    };
    
    // Plugins
    Object.defineProperty(navigator, 'plugins', {
        get: () => ({
            length: 3,
            0: { name: 'PDF Viewer', filename: 'internal-pdf-viewer' },
            1: { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
            2: { name: 'Chromium PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' }
        })
    });
    
    // WebRTC protection
    const RTC = window.RTCPeerConnection || window.mozRTCPeerConnection || window.webkitRTCPeerConnection;
    if (RTC) {
        window.RTCPeerConnection = function(...args) {
            const pc = new RTC(...args);
            pc.createDataChannel = () => ({});
            return pc;
        };
    }
    
    // Screen consistency
    Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
    Object.defineProperty(screen, 'pixelDepth', { get: () => 24 });
    
    // === End Stealth ===
    """
    
    return script.strip()


def get_behavior_script() -> str:
    """Returns script for human-like behavior helpers"""
    return """
    // Human behavior simulation helpers (injected)
    window.__human = {
        randomDelay: (min, max) => new Promise(r => setTimeout(r, min + Math.random() * (max - min))),
        randomInt: (min, max) => Math.floor(min + Math.random() * (max - min + 1))
    };
    """
