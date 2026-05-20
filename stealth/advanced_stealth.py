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
    // === Advanced Agentic Stealth v0.4 (canvas/Offscreen/WebGL2/font fixes #25 #27 #94 #150 #210 #262 #95 + webrtc #170) ===
    
    // Core anti-detection (improved for #138)
    Object.defineProperty(navigator, 'webdriver', {
        get: () => false,
        configurable: true
    });
    
    // Hide webdriver from property descriptors (stronger than simple getter)
    try {
        delete Object.getPrototypeOf(navigator).webdriver;
    } catch (e) {}
    
    // Plugins & mimeTypes (common bot detection)
    Object.defineProperty(navigator, 'plugins', {
        get: () => ({ length: 5, item: () => null, namedItem: () => null })
    });
    Object.defineProperty(navigator, 'mimeTypes', {
        get: () => ({ length: 2, item: () => null, namedItem: () => null })
    });
    
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
    
    // === Canvas, OffscreenCanvas, WebGL2, Font protection (v0.4 - fixes #25 #27 #94 #150 #210 #262 #95) ===
    // - Non-destructive tiny seeded subpixel jitter on fillText/strokeText (changes raster pixels for toDataURL fp consistently; content/visibility identical; defeats old mangling)
    // - Seeded small noise on getImageData (covers pixel read-back, OffscreenCanvas 2d, workers)
    // - measureText jitter for realistic font measurement spoofing (#95)
    // - Unified robust prototype patching for HTMLCanvasElement + OffscreenCanvas (#262)
    // - DPR/zoom-aware jitterScale for consistent fingerprints across zoom levels (#210)
    // - Patches re-applied automatically on nav/reload via context init_script (#150)
    (function(fpSeed) {
      const SEED = fpSeed || "agentic-default-seed-2026";
      function seededRand(n) {
        let x = 2166136261 >>> 0;
        for (let i=0; i<SEED.length; i++) x = (Math.imul(x ^ SEED.charCodeAt(i), 16777619)) >>> 0;
        x = (Math.imul(x ^ (n|0), 16777619)) >>> 0;
        return ((x >>> 0) % 100000) / 100000.0;
      }
      const dpr = (typeof window !== "undefined" && window.devicePixelRatio) ? window.devicePixelRatio : 1;
      const jitterScale = 0.55 / Math.max(1, dpr);  // #210: DPR-aware subpixel jitter

      function installCanvasPatches(Proto) {
        if (!Proto || !Proto.prototype || Proto.prototype.__stealthPatchedCanvas) return;
        const origGetContext = Proto.prototype.getContext;
        Proto.prototype.getContext = function(type, attrs) {
          const ctx = origGetContext.call(this, type, attrs);
          if (ctx && (type === "2d" || type === "webgl" || type === "webgl2" || type === "experimental-webgl")) {
            if (ctx.__stealthPatched) return ctx;
            if (type === "2d") {
              // fillText/strokeText jitter: pixel fp changes without mangling drawn text/numbers (#25 #27)
              const origFill = ctx.fillText;
              ctx.fillText = function(text, x, y, maxWidth) {
                const h = ((text || "").length + (x|0) + ((y|0)<<3)) >>> 0;
                const jx = (seededRand(h) - 0.5) * jitterScale;
                const jy = (seededRand(h + 1337) - 0.5) * jitterScale * 0.6;
                return origFill.call(this, text, x + jx, y + jy, maxWidth);
              };
              const origStroke = ctx.strokeText;
              if (origStroke) {
                ctx.strokeText = function(text, x, y, maxWidth) {
                  const h = 4242 + ((text || "").length + (x|0) + ((y|0)<<3)) >>> 0;
                  const jx = (seededRand(h) - 0.5) * jitterScale;
                  const jy = (seededRand(h + 1337) - 0.5) * jitterScale * 0.6;
                  return origStroke.call(this, text, x + jx, y + jy, maxWidth);
                };
              }
              // getImageData noise for read fp (#262 Offscreen too via shared proto)
              const origGetImageData = ctx.getImageData;
              if (origGetImageData) {
                ctx.getImageData = function(sx, sy, sw, sh, settings) {
                  const id = origGetImageData.call(this, sx, sy, sw, sh, settings);
                  const d = id.data;
                  const base = ((sx|0) * 31 + (sy|0) * 17 + (sw|0)) >>> 0;
                  for (let i = 0; i < d.length; i += 4) {
                    const rj = (seededRand(base + i) - 0.5) * 2.2;
                    const gj = (seededRand(base + i + 1) - 0.5) * 2.2;
                    const bj = (seededRand(base + i + 2) - 0.5) * 2.2;
                    d[i]     = Math.max(0, Math.min(255, (d[i]     || 0) + Math.floor(rj)));
                    d[i + 1] = Math.max(0, Math.min(255, (d[i + 1] || 0) + Math.floor(gj)));
                    d[i + 2] = Math.max(0, Math.min(255, (d[i + 2] || 0) + Math.floor(bj)));
                  }
                  return id;
                };
              }
              // measureText jitter (#95 font spoofing via canvas)
              const origMeasure = ctx.measureText;
              if (origMeasure) {
                ctx.measureText = function(text) {
                  const m = origMeasure.call(this, text);
                  const j = (seededRand( ((text||"").length % 17) * 51 + 9001 ) - 0.5) * 0.9;
                  try { Object.defineProperty(m, "width", {value: m.width + j, configurable: true}); } catch(e){}
                  return m;
                };
              }
            }
            ctx.__stealthPatched = true;
          }
          return ctx;
        };
        Proto.prototype.__stealthPatchedCanvas = true;
      }
      installCanvasPatches(HTMLCanvasElement);
      if (typeof OffscreenCanvas !== "undefined" && OffscreenCanvas.prototype) {
        installCanvasPatches(OffscreenCanvas);
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
    
    // WebRTC protection (improved #170 P1 leak prevention)
    // Prevents local IP / private network leaks via ICE candidates + prototype tampering resistance
    (function() {
        const RTC = window.RTCPeerConnection || window.mozRTCPeerConnection || window.webkitRTCPeerConnection;
        if (!RTC) return;
        const OrigRTC = RTC;
        const fakePublicIP = "203.0.113." + Math.floor(Math.random()*200 + 10); // RFC5737 TEST-NET-3
        window.RTCPeerConnection = function(config, constraints) {
            try {
                if (config && Array.isArray(config.iceServers)) {
                    config.iceServers = config.iceServers.filter(s => !/stun:.*(local|private|10\.|192\.168|172\.)/i.test(JSON.stringify(s)));
                }
                const pc = new OrigRTC(config || {iceServers: [{urls: "stun:stun.l.google.com:19302"}]}, constraints);
                const origCreateOffer = pc.createOffer;
                pc.createOffer = async function(...a) {
                    const offer = await origCreateOffer.apply(this, a);
                    return offer;
                };
                // Mangle candidates to never expose real private IPs
                const origSet = Object.getOwnPropertyDescriptor(OrigRTC.prototype, "onicecandidate");
                Object.defineProperty(pc, "onicecandidate", {
                    set: function(h) {
                        const wrapped = h ? function(ev) {
                            if (ev && ev.candidate && ev.candidate.candidate) {
                                let c = ev.candidate.candidate;
                                // replace any private / local IP with safe public fake
                                c = c.replace(/(\d{1,3}\.){3}\d{1,3}/g, (m) => {
                                    if (/^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.|127\.|169\.254\.)/.test(m)) return fakePublicIP;
                                    return m;
                                });
                                try { ev.candidate.candidate = c; } catch(e){}
                            }
                            return h.call(this, ev);
                        } : h;
                        OrigRTC.prototype.onicecandidate = wrapped; // best effort
                    },
                    get: function() { return OrigRTC.prototype.onicecandidate; }
                });
                pc.createDataChannel = function() { return { label: "stealth", readyState: "open" }; };
                return pc;
            } catch(e) {
                return new OrigRTC(config, constraints);
            }
        };
        // Prototype robustness (sites checking modified prototypes)
        if (window.RTCPeerConnection && window.RTCPeerConnection.prototype) {
            window.RTCPeerConnection.prototype.__stealthPatched = true;
        }
    })();
    
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
