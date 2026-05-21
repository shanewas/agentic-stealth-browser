"""
Advanced Stealth Module for Agentic Browsers
Production-grade fingerprint spoofing + anti-detection
"""

import random
import functools
import json
import re as _re
from typing import Dict, Any
from .cache import get_cached_script as _get_cached_script, make_cache_key, _script_cache

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


def get_playwright_version() -> str:
    """Detect installed Playwright version for #279 future-proofing (new signals on updates)."""
    try:
        import playwright
        return getattr(playwright, "__version__", "unknown")
    except Exception:
        try:
            from importlib.metadata import version as _v
            return _v("playwright")
        except Exception:
            return "unknown"


def check_stealth_compatibility() -> Dict[str, Any]:
    """#279: Detect potential new automation signals from newer Playwright/Chromium.
    Returns dict with warning for graceful handling (log + continue with existing robust patches).
    """
    pw_ver = get_playwright_version()
    warning = None
    try:
        major = int(str(pw_ver).split(".")[0]) if pw_ver not in ("unknown", "") else 0
    except Exception:
        major = 0
    if pw_ver != "unknown" and major >= 2:
        warning = (
            f"Playwright {pw_ver} detected (post baseline). New automation signals may appear after Chromium updates. "
            "Existing patches are try-wrapped/configurable for graceful degradation. Review #279."
        )
    return {
        "playwright_version": pw_ver,
        "warning": warning,
        "stealth_version": "0.4-p2",
        "recommended": "monitor https://github.com/shanewas/agentic-stealth-browser/issues/279",
    }


# lru_cache removed (hardware dict unhashable; fp_seed varies per session so hit rate low anyway)
# P3 #72/#63: use StealthCache for profile-keyed caching with TTL
def get_stealth_script(profile: str = "windows_laptop", fingerprint_seed: str = None, hardware: Dict[str, Any] = None, screen: Dict[str, Any] = None) -> str:
    """
    Returns a comprehensive stealth injection script.
    Designed to be injected via browser.add_init_script()

    fingerprint_seed: per-session stable seed for canvas/WebGL/audio noise (addresses #94 static patches)
    hardware: dict from persona.device.get_hardware_fingerprint() for #255 correlation
    screen: dict from persona.device.get_screen_profile() for #124 viewport realism + #198 screen/DPR/orient
    Cached by profile+seed+hardware+screen key with 2-hour TTL (#72 #63).
    """
    seed = fingerprint_seed or ("agentic-" + profile + "-seed-v3-2026")
    hw = hardware or {"hardwareConcurrency": 8, "deviceMemory": 8}
    scr = screen or {"width": 1920, "height": 1080, "availWidth": 1920, "availHeight": 1055, "colorDepth": 24, "pixelDepth": 24, "devicePixelRatio": 1.0, "orientation": "landscape-primary"}

    cache_key = make_cache_key(profile, fingerprint_seed, hardware, screen)
    cached = _script_cache.get(cache_key)
    if cached is not None:
        return cached

    script = _build_stealth_script(seed, hw, scr)
    _script_cache.put(cache_key, script)
    return script


def _build_stealth_script(seed: str, hw: Dict[str, Any], scr: Dict[str, Any]) -> str:
    """Build the stealth script string (internal, called when cache miss)."""
    script = """
    // === Advanced Agentic Stealth v0.4-p2-cluster (battery/speech/media #103, audio osc #162, viewport/screen/DPR/orient #124 #198, fonts #191, TLS docs #114; builds on #352) ===
    
    // Core anti-detection (improved for #138)
    Object.defineProperty(navigator, 'webdriver', {
        get: () => false,
        configurable: true
    });
    
    // Hide webdriver from property descriptors (stronger than simple getter)
    try {
        delete Object.getPrototypeOf(navigator).webdriver;
    } catch (e) {}
    
    // Plugins & mimeTypes will be defined later with proper prototype chain
    
    // Hardware fingerprint (consistent, persona power_level correlated via #255)
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => __HW_CONC__ });
    Object.defineProperty(navigator, 'deviceMemory', { get: () => __DEV_MEM__ });
    Object.defineProperty(navigator, 'platform', { get: () => 'Win32' });
    
    // Battery, SpeechSynthesis, MediaDevices spoofing (#103) - realistic stable per-session/persona values
    // getBattery returns fake BatteryManager; speech provides common real voices; mediaDevices returns consistent fake audio devices (no video cam to limit exposure)
    navigator.getBattery = navigator.getBattery || (() => Promise.resolve({ charging: true, chargingTime: null, dischargingTime: null, level: 0.82 + (Math.random()*0.13), addEventListener:()=>{}, removeEventListener:()=>{} }));
    (function spoofSpeech() {
      const voices = [
        {voiceURI:"Alex",name:"Alex",lang:"en-US",localService:true,default:true},
        {voiceURI:"Samantha",name:"Samantha",lang:"en-US",localService:true,default:false},
        {voiceURI:"Daniel",name:"Daniel",lang:"en-GB",localService:true,default:false},
        {voiceURI:"Karen",name:"Karen",lang:"en-AU",localService:true,default:false},
        {voiceURI:"Moira",name:"Moira",lang:"en-IE",localService:true,default:false}
      ];
      const synth = window.speechSynthesis || {};
      synth.getVoices = () => voices;
      if (typeof synth.onvoiceschanged === "function") { try { setTimeout(() => synth.onvoiceschanged(new Event("voiceschanged")), 5); } catch(e){} }
      window.speechSynthesis = synth;
    })();
    if (navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) {
      const fakeDevs = [
        {deviceId:"def1",kind:"audioinput",label:"Default - Microphone (Realtek High Definition Audio)",groupId:"g1"},
        {deviceId:"def2",kind:"audiooutput",label:"Default - Speakers (Realtek High Definition Audio)",groupId:"g1"},
        {deviceId:"com1",kind:"audioinput",label:"Communications - Microphone",groupId:"g2"}
      ];
      navigator.mediaDevices.enumerateDevices = () => Promise.resolve(fakeDevs);
      const _origGUM = navigator.mediaDevices.getUserMedia;
      navigator.mediaDevices.getUserMedia = async (c) => { if (c && c.video) throw new DOMException("Permission denied","NotAllowedError"); return _origGUM ? _origGUM.call(navigator.mediaDevices, c) : {getTracks:()=>[]}; };
    }
    
    // P2: __stealth marker + realistic font list (for #271 measureText correlation + #279 detection; enhanced #191)
    // List chosen to match common Windows desktop; measurements jittered consistently via font-aware seed.
    // Full document.fonts replacement avoided (risk of side-effects); exposed list + patched measure suffice for correlation.
    window.__stealth = window.__stealth || {
        version: "0.4-p2-cluster",
        patched: ["webdriver","canvas","offscreen","webgl","webgl2","measureText","hardware","webrtc","fonts","battery","speechSynthesis","mediaDevices","audio","screen","dpr","orientation"],
        fonts: ["Arial","Helvetica","Times New Roman","Courier New","Verdana","Georgia","Palatino Linotype","Garamond","Book Antiqua","Comic Sans MS","Trebuchet MS","Arial Black","Impact","Lucida Console","Segoe UI","Calibri","Cambria","Consolas","Tahoma","Microsoft Sans Serif","Lucida Sans Unicode"],
        playwright_compat: "baseline-124+",
        ts: Date.now()
    };
    
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
              // measureText jitter (#95 + #271: font-aware seed for list/measurement correlation)
              const origMeasure = ctx.measureText;
              if (origMeasure) {
                ctx.measureText = function(text) {
                  const m = origMeasure.call(this, text);
                  const font = (this && this.font) ? String(this.font).substring(0, 25) : "def";
                  const jseed = ((text||"").length % 17) * 51 + 9001 + font.length * 7;
                  const j = (seededRand( jseed ) - 0.5) * 0.85;
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
    // AudioContext noise + oscillator + sampleRate (#162 full coverage; builds on prior partial)
    // Uses per-session seeded noise for consistent fingerprints (same seed = same audio noise)
    const _audioSeed = "__DYNAMIC_SEED_PLACEHOLDER__" || "agentic-audio-v1";
    function _audioSeededRand(n) {
        let x = 2166136261 >>> 0;
        for (let i = 0; i < _audioSeed.length; i++) x = (Math.imul(x ^ _audioSeed.charCodeAt(i), 16777619)) >>> 0;
        x = (Math.imul(x ^ (n | 0), 16777619)) >>> 0;
        return ((x >>> 0) % 100000) / 100000.0;
    }
    let _audioRngCounter = 0;
    const AudioC = window.AudioContext || window.webkitAudioContext;
    if (AudioC) {
        const origCreate = AudioC.prototype.createAnalyser;
        AudioC.prototype.createAnalyser = function() {
            const a = origCreate.call(this);
            const origGet = a.getFloatFrequencyData;
            a.getFloatFrequencyData = function(arr) {
                origGet.call(this, arr);
                for (let i = 0; i < arr.length; i += 4) {
                    arr[i] *= 0.996 + _audioSeededRand(_audioRngCounter++) * 0.008;
                }
                return arr;
            };
            return a;
        };
        // sampleRate fixed realistic (common 44100 defeats sampleRate fp)
        try {
            Object.defineProperty(AudioC.prototype, "sampleRate", { get: function() { return 44100; }, configurable: true });
        } catch (e) {}
        // basic oscillator spoof for frequency-based fingerprinting
        // Use deterministic per-session perturbation rather than Math.random()
        const _oscOffset = (_audioSeededRand(42) - 0.5) * 2;  // stable per-session offset ~[-1, 1]
        const origOsc = AudioC.prototype.createOscillator;
        if (origOsc) {
            AudioC.prototype.createOscillator = function() {
                const o = origOsc.call(this);
                try {
                    const f = o.frequency;
                    if (f) {
                        // Return consistent perturbed value per-oscillator, not per-access
                        Object.defineProperty(f, "value", { get: () => 440 + _oscOffset, configurable: true });
                    }
                } catch (e) {}
                return o;
            };
        }
    }
    
    // Permissions
    const origQuery = navigator.permissions.query;
    navigator.permissions.query = (p) => {
        if (p.name === 'notifications') return Promise.resolve({ state: 'default' });
        return origQuery(p);
    };
    
    // Plugins (proper prototype chain for instanceof checks)
    (function() {
        // Create plugin objects with correct prototype
        function FakePlugin(name, filename, description) {
            this.name = name;
            this.filename = filename;
            this.description = description || name;
            this.length = 1;
            this[0] = { type: "application/pdf", suffixes: "pdf", description: description || name };
        }
        var pluginList = [
            new FakePlugin("PDF Viewer", "internal-pdf-viewer", "Portable Document Format"),
            new FakePlugin("Chrome PDF Viewer", "mhjfbmdgcfjbbpaeojofohoefgiehjai", "Portable Document Format"),
            new FakePlugin("Chromium PDF Viewer", "mhjfbmdgcfjbbpaeojofohoefgiehjai", "Portable Document Format")
        ];
        // Build a plugins-like object that passes `Object.prototype.toString` and `instanceof` checks
        var pluginsObj = Object.create(PluginArray.prototype, {
            length: { get: function() { return pluginList.length; }, configurable: true },
            item: { value: function(i) { return pluginList[i] || null; }, configurable: true },
            namedItem: { value: function(name) { return pluginList.find(function(p) { return p.name === name; }) || null; }, configurable: true },
            refresh: { value: function() {}, configurable: true }
        });
        for (var i = 0; i < pluginList.length; i++) {
            Object.defineProperty(pluginsObj, i, { get: function() { return pluginList[i]; }, configurable: true });
        }
        // MimeTypeArray mock (2 mime types)
        var mimeTypesObj = Object.create(MimeTypeArray.prototype, {
            length: { get: function() { return 2; }, configurable: true },
            item: { value: function(i) { return i < 2 ? pluginList[0][0] : null; }, configurable: true },
            namedItem: { value: function(n) { return null; }, configurable: true }
        });
        Object.defineProperty(navigator, 'plugins', { get: function() { return pluginsObj; }, configurable: true });
        Object.defineProperty(navigator, 'mimeTypes', { get: function() { return mimeTypesObj; }, configurable: true });
    })();
    
    // WebRTC protection (improved #170 P1 leak prevention)
    // Prevents local IP / private network leaks via ICE candidates + prototype tampering resistance
    // Uses per-session deterministic fake IP derived from fingerprint seed (not RFC5737, not Math.random)
    (function() {
        const RTC = window.RTCPeerConnection || window.mozRTCPeerConnection || window.webkitRTCPeerConnection;
        if (!RTC) return;
        const OrigRTC = RTC;
        // Stable per-session IP: last octet derived from seed hash (avoid detectable RFC5737 ranges)
        const fakePublicIP = "__FAKE_WEBRTC_IP__";
        window.RTCPeerConnection = function(config, constraints) {
            try {
                if (config && Array.isArray(config.iceServers)) {
                    config.iceServers = config.iceServers.filter(s => !/stun:.*(local|private|10\\.|192\\.168|172\\.)/i.test(JSON.stringify(s)));
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
                                c = c.replace(/(\\d{1,3}\\.){3}\\d{1,3}/g, (m) => {
                                    if (/^(10\\.|192\\.168\\.|172\\.(1[6-9]|2[0-9]|3[01])\\.|127\\.|169\\.254\\.)/.test(m)) return fakePublicIP;
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
    
    // Screen / viewport / DPR / orientation consistency (#124 #198) - injected from persona.screen for realistic variation
    Object.defineProperty(screen, 'width', { get: () => __SCREEN_W__ });
    Object.defineProperty(screen, 'height', { get: () => __SCREEN_H__ });
    Object.defineProperty(screen, 'availWidth', { get: () => __SCREEN_AW__ });
    Object.defineProperty(screen, 'availHeight', { get: () => __SCREEN_AH__ });
    Object.defineProperty(screen, 'colorDepth', { get: () => __SCREEN_CD__ });
    Object.defineProperty(screen, 'pixelDepth', { get: () => __SCREEN_PD__ });
    Object.defineProperty(window, 'devicePixelRatio', { get: () => __DPR__ });
    Object.defineProperty(screen, 'orientation', { get: () => ({ type: "__ORIENT__", angle: 0, onchange: null, addEventListener: () => {}, removeEventListener: () => {} }) });
    
    // === End Stealth ===
    """
    

    # Sanitize seed: remove JS-unsafe characters (quotes, backslashes, semicolons, angle brackets)
    # This prevents injection when the seed is interpolated into JS string literals.
    import re as _re_san  # use distinct name to avoid clash
    _safe_seed = _re_san.sub(r'["\'\\;<>]', '', seed)
    if not _safe_seed:
        _safe_seed = "agentic-default-seed"
    seed = _safe_seed

    # Inject the runtime seed into the JS IIFE call (makes canvas noise / fp per-session unique)
    # Use json.dumps for safe JS string interpolation (escapes quotes, backslashes, etc.)
    script = script.replace("__DYNAMIC_SEED_PLACEHOLDER__", json.dumps(seed)[1:-1])  # strip surrounding quotes
    # Generate a stable per-session WebRTC fake IP from the fingerprint seed.
    # Use realistic residential IP ranges (NOT RFC5737 TEST-NET ranges which are detectable).
    # Deterministic: same seed always produces the same fake IP.
    import hashlib as _hashlib
    _seed_hash = int(_hashlib.sha256(seed.encode()).hexdigest(), 16)
    _fake_ip_octet = (_seed_hash % 200) + 20  # 20-219 range for last octet
    _fake_ip_b = (_seed_hash >> 8) % 256
    _fake_ip_c = max(1, (_seed_hash >> 16) % 256)  # avoid .0.x subnet
    script = script.replace("__FAKE_WEBRTC_IP__", f"72.{_fake_ip_b}.{_fake_ip_c}.{_fake_ip_octet}")
    # P2: inject persona-correlated hardware (#255) + update placeholders
    # Use json.dumps for safe JS value interpolation (handles type coercion, prevents injection)
    script = script.replace("__HW_CONC__", json.dumps(hw.get("hardwareConcurrency", 8)))
    script = script.replace("__DEV_MEM__", json.dumps(hw.get("deviceMemory", 8)))
    # #124 #198: screen/vp/DPR/orient placeholders from persona (realistic per-persona variety)
    script = script.replace("__SCREEN_W__", json.dumps(scr.get("width", 1920)))
    script = script.replace("__SCREEN_H__", json.dumps(scr.get("height", 1080)))
    script = script.replace("__SCREEN_AW__", json.dumps(scr.get("availWidth", 1920)))
    script = script.replace("__SCREEN_AH__", json.dumps(scr.get("availHeight", 1055)))
    script = script.replace("__SCREEN_CD__", json.dumps(scr.get("colorDepth", 24)))
    script = script.replace("__SCREEN_PD__", json.dumps(scr.get("pixelDepth", 24)))
    script = script.replace("__DPR__", json.dumps(scr.get("devicePixelRatio", 1.0)))
    script = script.replace("__ORIENT__", json.dumps(scr.get("orientation", "landscape-primary")))
    # also update any old hardcoded if present (use sanitized seed)
    script = _re.sub(r'\}\)\("agentic-[^"]*seed[^"]*"\);', '})("' + seed + '");', script)
    return script.strip()


@functools.lru_cache(maxsize=8)
def get_behavior_script() -> str:
    """Returns script for human-like behavior helpers
    Caching (P2 perf): script is static; cache prevents rebuild on multi-browser launches.
    """
    return """
    // Human behavior simulation helpers (injected)
    window.__human = {
        randomDelay: (min, max) => new Promise(r => setTimeout(r, min + Math.random() * (max - min))),
        randomInt: (min, max) => Math.floor(min + Math.random() * (max - min + 1))
    };
    """
