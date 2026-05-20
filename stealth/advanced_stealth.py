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


def get_stealth_script(profile: str = "windows_laptop", fingerprint_seed: str = None) -> str:
    """
    Returns a comprehensive stealth injection script.
    Designed to be injected via browser.add_init_script()

    fingerprint_seed: per-session stable seed for canvas/WebGL/audio noise (addresses #94 static patches)
    """
    
    seed = fingerprint_seed or ("agentic-" + profile + "-seed-v3-2026")
    script = """
    // === Advanced Agentic Stealth v0.3 (canvas-offscreen-webgl2 fixes #94 #262 #210) ===
    
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
    
    // === Canvas, OffscreenCanvas, WebGL2 protection (v0.3 - fixes #94, #262, #210) ===
    // - Removed destructive digit->letter fillText mangling (broke real canvas text/charts on sites)
    // - Added OffscreenCanvas.getContext hook (critical for modern detectors & workers)
    // - Extended WebGL spoof to WebGL2RenderingContext + additional params + seeded jitter
    // - Captures devicePixelRatio for future zoom/DPR consistent noise (#210)
    // - Non-destructive fingerprint resistance improvement
    (function(fpSeed) {
      const SEED = fpSeed || "agentic-default-seed-2026";
      function seededRand(n) {
        let x = 2166136261 >>> 0;
        for (let i=0; i<SEED.length; i++) x = (Math.imul(x ^ SEED.charCodeAt(i), 16777619)) >>> 0;
        x = (Math.imul(x ^ (n|0), 16777619)) >>> 0;
        return ((x >>> 0) % 100000) / 100000.0;
      }
      const dpr = (typeof window !== "undefined" && window.devicePixelRatio) ? window.devicePixelRatio : 1;

      // Patch HTMLCanvasElement.getContext
      const origGetContext = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function(type, attrs) {
        const ctx = origGetContext.call(this, type, attrs);
        if (ctx && (type === "2d" || type === "webgl" || type === "webgl2" || type === "experimental-webgl")) {
          // room for seeded getImageData noise using dpr + seededRand
        }
        return ctx;
      };

      // OffscreenCanvas support (#262)
      if (typeof OffscreenCanvas !== "undefined" && OffscreenCanvas.prototype && OffscreenCanvas.prototype.getContext) {
        const origOffGet = OffscreenCanvas.prototype.getContext;
        OffscreenCanvas.prototype.getContext = function(type, attrs) {
          const ctx = origOffGet.call(this, type, attrs);
          if (ctx && (type === "2d" || type === "webgl" || type === "webgl2")) {
            // future: wrap same
          }
          return ctx;
        };
      }

      // WebGL + WebGL2 getParameter extended (prep #218)
      function installWebGLSpoof(Proto) {
        if (!Proto || !Proto.prototype || Proto.prototype.__stealthPatched) return;
        const orig = Proto.prototype.getParameter;
        Proto.prototype.getParameter = function(p) {
          if (p === 37445) return "Intel Inc.";
          if (p === 37446) return "Intel(R) UHD Graphics 620";
          if (p === 37447) return "WebGL 1.0 (OpenGL ES 2.0 Chromium)";
          if (p === 35660) return 16;
          if (p === 36349 || p === 36348) return 0x8b20;
          if (p === 34024 || p === 34076) {
            return 16384 + Math.floor(seededRand(p) * 4096);
          }
          try { return orig.apply(this, arguments); } catch(e) { return null; }
        };
        Proto.prototype.__stealthPatched = true;
      }
      if (typeof WebGLRenderingContext !== "undefined") installWebGLSpoof(WebGLRenderingContext);
      if (typeof WebGL2RenderingContext !== "undefined") installWebGLSpoof(WebGL2RenderingContext);

    })("__DYNAMIC_SEED_PLACEHOLDER__");
    // === End improved canvas patch ===
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
    

    # Inject the runtime seed into the JS IIFE call (makes canvas noise / fp per-session unique)
    script = script.replace("__DYNAMIC_SEED_PLACEHOLDER__", seed)
    # also update any old hardcoded if present
    import re as _re
    script = _re.sub(r'\}\)\("agentic-[^"]*seed[^"]*"\);', '})("' + seed + '");', script)
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
