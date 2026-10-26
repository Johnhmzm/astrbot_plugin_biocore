(() => {
  "use strict";
  const canvas = document.getElementById("orbCanvas");
  const signalCanvas = document.getElementById("signalCanvas");
  if (!canvas) return;
  const orbTip = document.getElementById("orbTip");
  const orbTipHost = orbTip ? orbTip.parentElement : null;
  const ctx = canvas.getContext("2d");
  const DPR = Math.min(2, window.devicePixelRatio || 1);
  const W = 520, H = 520;
  canvas.width = W * DPR; canvas.height = H * DPR;
  ctx.scale(DPR, DPR);
  const CX = W / 2, CY = H / 2 - 2, R = 76;
  let state = { intent: { emotion: "neutral" }, snapshot: { energy: .5, stress: .2, trust: .5, a: .4,
    noise: { stress: 0, energy: 0, social: 0, attention: 0, valence: 0 }, echo: 0, echo_trace: 0,
    ripple: { upper: .3, lower: .2, overlap: .1 }, spiking: { rate: .03 } },
    visual: { noise: true, echo: true, ripple: true, nodes: false, nodeLinks: false, intensity: 65 },
    events: [], memories: [] };
  let phase = 0, lastFrame = 0, frameCount = 0;
  const clamp = (v) => Math.max(0, Math.min(1, Number(v) || 0));
  // Two-sided numeric clamp for percentage/alpha bounds (the 0..1 clamp is
  // too narrow for sat/light/alpha floors). Module scope: memory-ball rings
  // draw before the center mood ball.
  const _bound = (v, lo, hi) => Math.max(lo, Math.min(hi,
    Number.isFinite(Number(v)) ? Number(v) : lo));
  // task-69: OKLab/OKLCH helpers for the mixed memory-ball colour.
  // Colours in the dashboard palette are "r,g,b" strings.
  const _srgbToLinear = (c) => {
    const x = Math.max(0, Math.min(1, c / 255));
    return x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
  };
  const _linearToSrgb = (c) => {
    const x = Math.max(0, Math.min(1, c));
    const v = x <= 0.0031308 ? 12.92 * x : 1.055 * Math.pow(x, 1 / 2.4) - 0.055;
    return Math.round(Math.max(0, Math.min(1, v)) * 255);
  };
  const _rgbToOklab = (rgb) => {
    const parts = String(rgb || "116,146,168").split(",").map((x) => Number(x) || 0);
    const r = _srgbToLinear(parts[0]), g = _srgbToLinear(parts[1]), b = _srgbToLinear(parts[2]);
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b);
    return { L: 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
             a: 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
             b: 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s };
  };
  const _oklabToRgb = (L, a, b) => {
    const l = Math.pow(L + 0.3963377774 * a + 0.2158037573 * b, 3);
    const m = Math.pow(L - 0.1055613458 * a - 0.0638541728 * b, 3);
    const s = Math.pow(L - 0.0894841775 * a - 1.2914855480 * b, 3);
    return [_linearToSrgb(4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s),
            _linearToSrgb(-1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s),
            _linearToSrgb(-0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)];
  };
  const _mixOklch = (entries, primaryFloor) => {
    let L = 0, A = 0, B = 0, total = 0;
    (entries || []).forEach((entry) => {
      const w = Math.max(0, Number(entry && entry.weight) || 0);
      if (w <= 0) return;
      const lab = _rgbToOklab(entry.rgb);
      L += lab.L * w; A += lab.a * w; B += lab.b * w; total += w;
    });
    if (total <= 0) return null;
    L /= total; A /= total; B /= total;
    let C = Math.sqrt(A * A + B * B);
    const h = Math.atan2(B, A);
    // Clamp to a visible, non-gray/non-white band: floor chroma, cap chroma,
    // keep lightness in a readable mid range.
    C = Math.max(0.055, Math.min(0.24, C));
    L = Math.max(0.40, Math.min(0.74, L));
    const aa = Math.cos(h) * C, bb = Math.sin(h) * C;
    const rgb = _oklabToRgb(L, aa, bb);
    return { l: Number(L.toFixed(3)), c: Number(C.toFixed(3)),
             h: Number((h * 180 / Math.PI).toFixed(1)), rgb: rgb,
             css: "rgb(" + rgb[0] + "," + rgb[1] + "," + rgb[2] + ")" };
  };
  const isDark = () => document.documentElement.dataset.theme === "dark";
  // task-42/44: pure orbit math lives in orb_math.js so evals can run it in
  // node (world units, R applied once). The inline copy below is the same
  // formula if that script is missing.
  const _OM = (typeof window !== "undefined" && window.BioOrbMath) || (() => {
    const _clamp01 = (v) => { const n = Number(v); return Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : 0; };
    const _channels = [
      { key: "echo", tilt: .35, speed: .55, color: "255,107,0" },
      { key: "rippleU", tilt: -.36, speed: -.40, color: "48,48,46" },
      { key: "noise", tilt: .82, speed: .62, color: "142,132,120" },
      { key: "rippleL", tilt: -1.18, speed: .90, color: "255,138,40" },
      { key: "spike", tilt: .62, speed: -.28, color: "96,96,96" },
      { key: "trust", tilt: 1.12, speed: 1.10, color: "196,148,82" },
      { key: "dominance", tilt: -.70, speed: .34, color: "96,140,255" },
      { key: "social", tilt: 1.34, speed: -.46, color: "64,196,168" }
    ];
    const _ident = (index, count) => {
      const n = Math.max(2, Number(count) || _channels.length);
      return (Math.max(0, Math.min(n - 1, Number(index) || 0)) / (n - 1) - 0.5) * 0.06;
    };
    const _lane = (i) => (Math.max(0, Math.min(_channels.length - 1, Number(i) || 0)) - 3.5) * 0.07;
    const _build = () => _channels.map((c, i) => ({
      key: c.key, tilt: c.tilt, speed: c.speed, color: c.color, angle: 0,
      lane: _lane(i),
      ident: _ident(i, _channels.length), tiltOff: _ident(i, _channels.length) * 1.5
    }));
    const _radius = (metric) => 0.9 + 0.7 * _clamp01(metric);
    const _project = (x, y, z, ry, rx, R) => {
      const cY = Math.cos(Number(ry) || 0), sY = Math.sin(Number(ry) || 0);
      const cX = Math.cos(Number(rx) || 0), sX = Math.sin(Number(rx) || 0);
      const x0 = Number(x) || 0, y0 = Number(y) || 0, z0 = Number(z) || 0;
      let x1 = x0 * cY - z0 * sY;
      let z1 = x0 * sY + z0 * cY;
      let y1 = y0 * cX - z1 * sX;
      z1 = y0 * sX + z1 * cX;
      const p = 1 + z1 * .16;
      return { x: x1 * Number(R) * p, y: y1 * Number(R) * p, z: z1 };
    };
    const _ringPts = (orbit, metric, angle, ry, rx, R, samples) => {
      const n = Math.max(8, Math.floor(Number(samples) || 160));
      const rBase = _radius(metric) + Number(orbit && orbit.lane || 0);
      const tilt = Number(orbit && orbit.tilt || 0) + Number(orbit && orbit.tiltOff || 0);
      const idShift = Number(orbit && orbit.ident || 0);
      const ay = Number(angle) || 0;
      const cA = Math.cos(ay), sA = Math.sin(ay), sT = Math.sin(tilt), cT = Math.cos(tilt);
      const pts = [];
      for (let i = 0; i <= n; i++) {
        const a = i / n * Math.PI * 2;
        const x = Math.cos(a) * rBase + idShift;
        const y = Math.sin(a) * rBase * sT + idShift * .5;
        const z = Math.sin(a) * rBase * cT;
        const x1 = x * cA - z * sA;
        const z1 = x * sA + z * cA;
        pts.push(_project(x1, y, z1, ry, rx, R));
      }
      return pts;
    };
    const _lerp = (cur, target, alpha) => {
      const a = Number.isFinite(Number(alpha)) ? Math.max(0, Math.min(1, Number(alpha))) : 0;
      const c = Number.isFinite(Number(cur)) ? Number(cur) : (Number(target) || 0);
      const t = Number.isFinite(Number(target)) ? Number(target) : c;
      return c + (t - c) * a;
    };
    const _camPoint = (x, y, cam, cx, cy) => {
      const z = (cam && Number.isFinite(Number(cam.zoom))) ? Number(cam.zoom) : 1;
      const fx = (cam && Number.isFinite(Number(cam.x))) ? Number(cam.x) : Number(cx);
      const fy = (cam && Number.isFinite(Number(cam.y))) ? Number(cam.y) : Number(cy);
      return { x: Number(cx) + (Number(x) - fx) * z, y: Number(cy) + (Number(y) - fy) * z };
    };
    const _camTarget = (ball, cx, cy, focused) => {
      if (!focused) return { x: Number(cx), y: Number(cy), zoom: 1 };
      return { x: ball && Number.isFinite(Number(ball.x)) ? Number(ball.x) : Number(cx),
               y: ball && Number.isFinite(Number(ball.y)) ? Number(ball.y) : Number(cy),
               zoom: 1.8 };
    };
    const _camStep = (cam, target, camLerp, zoomLerp) => {
      const cur = cam || {}, tgt = target || {};
      const cl = Number.isFinite(Number(camLerp)) ? Number(camLerp) : 0.18;
      const zl = Number.isFinite(Number(zoomLerp)) ? Number(zoomLerp) : 0.12;
      return { x: _lerp(cur.x, tgt.x, cl), y: _lerp(cur.y, tgt.y, cl),
               zoom: _lerp(cur.zoom == null ? 1 : cur.zoom, tgt.zoom == null ? 1 : tgt.zoom, zl) };
    };
    const _tap = (sx, sy, ex, ey, dt, maxMove, maxMs) => {
      const mx = maxMove == null ? 8 : Number(maxMove);
      const mt = maxMs == null ? 700 : Number(maxMs);
      if (![sx, sy, ex, ey, dt].every((v) => Number.isFinite(Number(v)))) return false;
      if (Number(dt) < 0 || Number(dt) > mt) return false;
      return Math.hypot(Number(ex) - Number(sx), Number(ey) - Number(sy)) <= mx;
    };
    return {
      ORBIT_COUNT: 8,
      ORBIT_CHANNELS: _channels,
      buildOrbits: _build,
      orbitRadius: _radius,
      laneOffset: _lane,
      identityOffset: _ident,
      projectPoint: _project,
      orbitRingPoints: _ringPts,
      FOCUS_ZOOM: 1.8,
      CAM_LERP: 0.18,
      ZOOM_LERP: 0.12,
      zoomTarget: (focused) => (focused ? 1.8 : 1),
      lerp: _lerp,
      cameraPoint: _camPoint,
      cameraTarget: _camTarget,
      cameraStep: _camStep,
      isTap: _tap,
      DEPTH_FAR: .72, DEPTH_NEAR: 1,
      DIM_FOCUSED: 1.25, DIM_DIMMED: .32, DIM_IDLE: 1, DIM_TAU: .2,
      depthFactor: (z) => {
        const t = Math.max(0, Math.min(1, (Number(z) + 1) / 2));
        return .72 + .28 * t;
      },
      dimTarget: (focused, anyFocus) => (anyFocus ? (focused ? 1.25 : .32) : 1),
      inferredSecondaryHsl: (hue, sat, light) => ({
        h: ((Number(hue) || 0) + 40) % 360,
        s: Math.max(22, Math.min(100, (Number(sat) || 0) * 0.62)),
        l: Math.max(28, Math.min(72, Number(light) || 55)),
        alpha: 0.55
      }),
      RING_FAR: .68, RING_NEAR: 1,
      ringDepth: (z) => Math.max(0, Math.min(1, (Number(z) + 1) / 2)),
      ringShade: (z) => {
        const d = Math.max(0, Math.min(1, (Number(z) + 1) / 2));
        return .68 + .32 * d;
      },
      smoothToward: (cur, tgt, dt, tau) => {
        const c = Number.isFinite(Number(cur)) ? Number(cur) : (Number(tgt) || 0);
        const t = Number.isFinite(Number(tgt)) ? Number(tgt) : c;
        const d = Number(dt);
        if (!Number.isFinite(d) || d <= 0) return c;
        const tv = (Number.isFinite(Number(tau)) && Number(tau) > 0) ? Number(tau) : .2;
        const a = 1 - Math.exp(-d / tv);
        return c + (t - c) * Math.max(0, Math.min(1, a));
      },
      orbitVolatility(prev, cur, dt, prevEma) {
        if (prev == null || !Number.isFinite(Number(prev)) || !Number.isFinite(Number(cur))) return 0.5;
        const secs = Number(dt);
        if (!Number.isFinite(secs) || secs <= 0) return 0.5;
        const raw = _clamp01(Math.abs(Number(cur) - Number(prev)) / secs);
        const base = (prevEma == null || !Number.isFinite(Number(prevEma))) ? 0.5 : _clamp01(prevEma);
        return _clamp01(0.15 * raw + 0.85 * base);
      },
      orbitSpeed(base, vol) { return Number(base || 0) * (0.4 + 1.8 * _clamp01(vol)); }
    };
  })();
  window.addEventListener("biocore:state", (e) => { if (e.detail) state = Object.assign({}, state, e.detail); });

  // task-43: memory-ball click/tap focus. The pure camera/tap math lives in
  // orb_math.js; this block owns state/DOM and reuses that math through _OM.
  const _focusState = { key: "", ev: null, prev: null };
  const _cam = { x: CX, y: CY, zoom: 1 };
  const _pointerTap = { active: false, x: 0, y: 0, t: 0 };
  const _focusHost = canvas.parentElement || null;
  let _focusExitBtn = null;
  function _ballKey(ev) {
    return String((ev && (ev.id || ev.event_key || ev.title)) || 0);
  }
  function _ensureFocusUi() {
    if (!_focusHost || _focusExitBtn) return;
    _focusExitBtn = document.createElement("button");
    _focusExitBtn.type = "button";
    _focusExitBtn.id = "orbFocusExit";
    _focusExitBtn.className = "orb-focus-exit";
    _focusExitBtn.textContent = "退出聚焦";
    _focusExitBtn.hidden = true;
    _focusExitBtn.addEventListener("click", (e) => {
      e.preventDefault(); e.stopPropagation(); exitBallFocus();
    });
    _focusHost.appendChild(_focusExitBtn);
  }
  // task-45: the left CURRENT EMOTION block is driven by app.js, so orb.js only
  // dispatches focus/exit events with the selected memory's display data. The
  // old bottom-right card is removed to avoid duplicating that panel.
  // task-46: only llm / fallback / legacy are valid summary states; records
  // written by older versions have no field and are treated as legacy.
  function _summaryStatusOf(ev) {
    const s = String((ev && ev.summary_status) || "legacy").trim().toLowerCase();
    if (s === "llm" || s === "fallback" || s === "edited") return s;
    return "legacy";
  }
  function _focusEventDetail(ev) {
    const e = ev || {};
    const check = (e.source_check && typeof e.source_check === "object") ? e.source_check : {};
    return {
      key: String(_focusState.key || ""),
      event_id: String(e.id || e.event_key || ""),
      title: _tipClean(String(e.title || e.event_key || "记忆球"), 80),
      summary_status: _summaryStatusOf(e),
      summary_edited: e.summary_edited === true,
      summary_updated_ts: Number(e.summary_updated_ts || 0),
      emotion: String(e.emotion || ""),
      emotion_secondary: String(e.emotion_secondary || ""),
      importance: Number(e.importance == null ? .5 : e.importance),
      ts: Number(e.ts || 0),
      source: String(check.status || "ok"),
      confidence: (e.confidence == null || e.confidence === "") ? null : Number(e.confidence),
      recall_count: Number(e.recall_count || 0),
      small_summary: _tipClean(String(e.small_summary || ""), 80),
      big_summary: String(e.big_summary || ""),
      event: String(e.event || ""),
      central_details: String(e.central_details || "")
    };
  }
  function _dispatchFocusEvent(name, ev) {
    try {
      const detail = _focusEventDetail(ev);
      if (typeof CustomEvent === "function") {
        document.dispatchEvent(new CustomEvent(name, { detail: detail }));
      } else if (document && document.createEvent) {
        const evt = document.createEvent("CustomEvent");
        evt.initCustomEvent(name, false, false, detail);
        document.dispatchEvent(evt);
      }
    } catch (err) { /* never let panel glue break the orb */ }
  }
  function focusBall(hit) {
    if (!hit) return;
    _focusState.key = String(hit.key || _ballKey(hit.ev));
    _focusState.ev = hit.ev || {};
    _focusState.prev = { x: Number(hit.x) || CX, y: Number(hit.y) || CY };
    window.__biocoreFocusKey = _focusState.key;   // task-43 observability
    _ensureFocusUi();
    if (_focusExitBtn) _focusExitBtn.hidden = false;
    _dispatchFocusEvent("biocore:focus", _focusState.ev);   // task-45 panel data
    hideOrbTip();
  }
  function exitBallFocus() {
    const wasFocused = !!_focusState.key;
    _focusState.key = "";
    _focusState.ev = null;
    _focusState.prev = null;
    window.__biocoreFocusKey = "";               // task-43 observability
    if (_focusExitBtn) _focusExitBtn.hidden = true;
    if (wasFocused) _dispatchFocusEvent("biocore:focus-exit", null);
    hideOrbTip();
  }
  function toggleBallFocus(hit) {
    if (!hit) return;
    const key = String(hit.key || _ballKey(hit.ev));
    if (_focusState.key && _focusState.key === key) exitBallFocus();
    else focusBall(hit);
  }

  // task-42/44: 8 centre channels share one world-unit distance law. Identity =
  // colour + fixed +/-0.03 world-unit offset (orb_math.js buildOrbits); the
  // speed sign stays fixed as part of the identity.
  const orbits = _OM.buildOrbits();
  function orbitMetric(o, s) {
    const n = s.noise || {}, rp = s.ripple || {}, sp = s.spiking || {};
    if (o.key === "echo") return clamp(Math.abs(s.echo_trace || s.echo || 0));
    if (o.key === "rippleU") return clamp(rp.upper || 0);
    if (o.key === "rippleL") return clamp(rp.lower || 0);
    if (o.key === "noise") return clamp((Math.abs(n.stress || 0) + Math.abs(n.energy || 0)) * 1.6);
    if (o.key === "spike") return clamp((sp.rate || 0) * 6);
    if (o.key === "trust") return clamp(s.trust || 0);
    if (o.key === "dominance") return clamp((1 + Number(s.d == null ? 0.5 : s.d)) / 2);
    if (o.key === "social") return clamp(s.social == null ? .5 : s.social);
    return .5;
  }
  // Particle field: three concentric orbital rings instead of a dense sphere.
  // Each ring has its own plane and slow direction; dot spacing stays even so
  // individual particles remain readable. 1 unit = R px.
  const _PN = 30;
  const _PARTICLE_RINGS = [
    { r: 1.30, tilt: .32, yaw: .10, n: 12, speed: .72, phase: 0.0 },
    { r: 1.60, tilt: -.55, yaw: 1.25, n: 10, speed: -.48, phase: 2.1 },
    { r: 1.90, tilt: .78, yaw: 2.30, n: 8, speed: .34, phase: 4.2 }
  ];
  const particles = [];
  _PARTICLE_RINGS.forEach((ring, ri) => {
    for (let k = 0; k < ring.n; k++) {
      particles.push({ ring: ri, a0: (k / ring.n) * Math.PI * 2 + ri * .9,
                       r: ring.r, tilt: ring.tilt, yaw: ring.yaw,
                       speed: ring.speed, phase: k * .7 + ri, i: particles.length });
    }
  });
  // Fixed links: neighbouring dots on the same ring only (sparse constellation).
  const LINK_PAIRS = (() => {
    const pairs = [];
    let offset = 0;
    _PARTICLE_RINGS.forEach((ring) => {
      for (let k = 0; k < ring.n; k++) {
        pairs.push({ a: offset + k, b: offset + ((k + 1) % ring.n), w: .9 });
      }
      offset += ring.n;
    });
    return pairs;
  })();
  const _linkFade = new Float32Array(LINK_PAIRS.length);
  let _hoverOrb = false;
  const _memHit = [];
  const _mouse = { x: -1, y: -1, inside: false };
  // task-48: per-ball smooth focus dim state + last frame timestamp.
  const _ballDims = new Map();
  // task-70: smoothed visual-only gravity offsets per memory ball
  const _ballGravityOffsets = new Map();
  let _lastDrawTs = 0;
  // convert the emotion rgb to a saturated, slightly deep hsl so balls keep hue
  // separation instead of turning into desaturated dark blobs
  const _vividHsl = (rgb, imp) => {
    const parts = String(rgb || "124,154,146").split(",").map((x) => Number(x) || 0);
    const r = (parts[0] || 0) / 255, g = (parts[1] || 0) / 255, b = (parts[2] || 0) / 255;
    const max = Math.max(r, g, b), min = Math.min(r, g, b), d = max - min;
    let h = 0;
    if (d > 0) {
      if (max === r) h = ((g - b) / d) % 6;
      else if (max === g) h = (b - r) / d + 2;
      else h = (r - g) / d + 4;
      h *= 60;
      if (h < 0) h += 360;
    }
    const l0 = (max + min) / 2;
    const s0 = d > 0 ? d / (1 - Math.abs(2 * l0 - 1)) : 0;
    const s = Math.max(55, Math.min(100, s0 * 145 + 12 + imp * 10));
    const l = Math.max(32, Math.min(54, l0 * 82 - imp * 6));
    return { h, s, l };
  };
  const _hashStr = (value) => {
    let h = 2166136261 >>> 0;
    const str = String(value == null ? "" : value);
    for (let i = 0; i < str.length; i++) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 16777619) >>> 0;
    }
    return h >>> 0;
  };
  canvas.addEventListener("pointermove", (e) => {
    try {
      const rect = canvas.getBoundingClientRect();
      _mouse.x = (e.clientX - rect.left) * (W / Math.max(1, rect.width));
      _mouse.y = (e.clientY - rect.top) * (H / Math.max(1, rect.height));
      _mouse.clientX = e.clientX;
      _mouse.clientY = e.clientY;
      _mouse.inside = true;
    } catch (err) { _mouse.inside = false; }
  });
  canvas.addEventListener("pointerenter", () => { _hoverOrb = true; });
  canvas.addEventListener("pointerleave", () => { _hoverOrb = false; _mouse.inside = false; hideOrbTip(); });
  // task-43: tap/click focus. pointerdown/up are paired; a drag/rotate (moving
  // past TAP_MAX_MOVE) or a long press is NOT a tap, so it never changes focus.
  // Blank click while focused, Escape, or the "退出聚焦" button restores view.
  function _canvasPoint(e) {
    const rect = canvas.getBoundingClientRect();
    return { x: (e.clientX - rect.left) * (W / Math.max(1, rect.width)),
             y: (e.clientY - rect.top) * (H / Math.max(1, rect.height)) };
  }
  function _pickMemHit(mx, my) {
    let hit = null, best = Infinity;
    for (let k = 0; k < _memHit.length; k++) {
      const hb = _memHit[k];
      const sp = _OM.cameraPoint(hb.x, hb.y, _cam, CX, CY);
      const dist = Math.hypot(sp.x - mx, sp.y - my);
      const reach = Math.max(18 * _cam.zoom, hb.r * _cam.zoom + 10);
      if (dist <= reach && dist < best) { hit = hb; best = dist; }
    }
    return hit;
  }
  canvas.addEventListener("pointerdown", (e) => {
    if (e.button != null && e.button !== 0) return;
    try {
      const pt = _canvasPoint(e);
      _pointerTap.active = true;
      _pointerTap.x = pt.x; _pointerTap.y = pt.y; _pointerTap.t = Date.now();
      try { if (canvas.setPointerCapture) canvas.setPointerCapture(e.pointerId); } catch (err) {}
      hideOrbTip();   // tooltip must not fight the tap target
    } catch (err) { _pointerTap.active = false; }
  });
  canvas.addEventListener("pointerup", (e) => {
    if (!_pointerTap.active) return;
    _pointerTap.active = false;
    try {
      const pt = _canvasPoint(e);
      const dt = Date.now() - _pointerTap.t;
      if (!_OM.isTap(_pointerTap.x, _pointerTap.y, pt.x, pt.y, dt)) return;
      const hit = _pickMemHit(pt.x, pt.y);
      if (hit) toggleBallFocus(hit);
      else if (_focusState.key) exitBallFocus();
    } catch (err) {}
  });
  canvas.addEventListener("pointercancel", () => { _pointerTap.active = false; });
  document.addEventListener("keydown", (e) => {
    if (String(e.key || "") === "Escape" && _focusState.key) exitBallFocus();
  });
  const _tipEsc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function hideOrbTip() {
    if (!orbTip) return;
    orbTip.classList.remove("show");
    orbTip.hidden = true;
  }
  // G11: merge_count is stored raw; consumers see a 30-day half-life effective
  // value (memory_meta.time_decay). Display-only: never rewrites the archive.
  const MERGE_HALF_LIFE_DAYS = 30;
  function _effectiveMergeCount(ev) {
    const raw = Math.max(0, Number((ev && ev.merge_count) || 0));
    if (!(raw > 0)) return 0;
    const ts = Number((ev && ev.ts) || 0);
    if (!(ts > 0)) return raw;
    const ageDays = Math.max(0, (Date.now() / 1000 - ts) / 86400);
    return Math.max(0, Math.round(raw * Math.pow(0.5, ageDays / MERGE_HALF_LIFE_DAYS)));
  }
  function _mergeTip(ev) {
    const raw = Math.max(0, Number((ev && ev.merge_count) || 0));
    if (!(raw > 0)) return "";
    const eff = _effectiveMergeCount(ev);
    return " · 合并 " + raw + (eff !== raw ? ("（有效 " + eff + "）") : "");
  }
  function _tipClean(value, limit) {
    let text = String(value == null ? "" : value).replace(/\s+/g, " ").trim();
    if (text.length > limit) text = text.slice(0, limit - 1).trimEnd() + "…";
    return text;
  }
  function updateOrbTip(hit) {
    if (!orbTip) return;
    const ev = hit.ev || {};
    const title = _tipClean(ev.title || ev.event_key || "事件", 60);
    const when = hit.tsS > 0 ? new Date(hit.tsS * 1000).toLocaleString("zh-CN",
      { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
    const impLine = "重要度 " + Number(hit.imp || 0).toFixed(2) +
      " · 年龄 " + Math.round(hit.ageDays) + "d" +
      (ev.peripheral_forgotten ? " · 外围已遗忘" : "") +
      _mergeTip(ev);
    const _secKey = String(ev.emotion_secondary || "").trim();
    const _status = String((ev.source_check && ev.source_check.status) || "ok");
    const _emoLine = "情绪：" + _emotionZh(ev.emotion) +
      (_secKey ? " / 次情绪：" + _emotionZh(_secKey) : " / 次情绪：推断（示意）") +
      " · 来源 " + _status;
    // Keep the hover card small: prefer the <=80-char small_summary (task-41);
    // old events without it fall back to the archived event / central details,
    // never to a whole raw chat turn.
    const small = _tipClean(ev.small_summary || "", 80);
    const fallbackText = _tipClean(ev.event || ev.central_details || ev.meaning_to_her || "", 180);
    const bodyHtml = small
      ? '<div class="orb-tip-body">小总结：' + _tipEsc(small) + "</div>"
      : (fallbackText ? '<div class="orb-tip-body">' + _tipEsc(fallbackText) + "</div>" : "");
    orbTip.innerHTML = "<b>" + _tipEsc(title) + "</b>" +
      (when ? '<div class="orb-tip-meta">' + _tipEsc(when) + "</div>" : "") +
      '<div class="orb-tip-meta">' + _tipEsc(_emoLine) + "</div>" +
      '<div class="orb-tip-meta">' + _tipEsc(impLine) + "</div>" +
      bodyHtml;
    orbTip.hidden = false;
    orbTip.classList.add("show");
    if (!orbTipHost) return;
    const r = orbTipHost.getBoundingClientRect();
    const cx = _mouse.clientX == null ? r.left + r.width / 2 : _mouse.clientX;
    const cy = _mouse.clientY == null ? r.top + r.height / 2 : _mouse.clientY;
    const tw = orbTip.offsetWidth || 280, th = orbTip.offsetHeight || 80;
    let x = cx - r.left + 14, y = cy - r.top + 14;
    x = Math.max(8, Math.min(r.width - tw - 8, x));
    y = Math.max(8, Math.min(r.height - th - 8, y));
    orbTip.style.left = x + "px";
    orbTip.style.top = y + "px";
  }

  // task-58: full emotion vocabulary (EMOTION_SPECTRUM 30+) in Chinese; a
  // missing key never leaks raw English into the tooltip/focus/card UI.
  const _EMO_ZH = {
    neutral:"平静", joy:"开心", sadness:"难过", fear:"害怕", anger:"生气",
    surprise:"惊讶", trust:"信任", loneliness:"孤独", admiration:"钦佩",
    adoration:"爱慕", aesthetic:"审美欣赏", amusement:"好笑", anxiety:"焦虑",
    awe:"敬畏", awkwardness:"尴尬", boredom:"无聊", calmness:"平静",
    confusion:"困惑", contempt:"轻蔑", contentment:"满足", desire:"欲望",
    disappointment:"失望", disgust:"厌恶", empathic_pain:"共情痛苦",
    entrancement:"入迷", envy:"嫉妒", excitement:"兴奋", guilt:"内疚",
    horror:"恐惧", interest:"兴趣", nostalgia:"怀念", pride:"自豪",
    satisfaction:"满足", shame:"羞耻"
  };
  const _SECONDARY_FAMILY = {
    admiration:"joy", adoration:"joy", aesthetic:"joy", amusement:"joy", awe:"joy",
    contentment:"joy", desire:"joy", excitement:"joy", interest:"joy", joy:"joy", pride:"joy",
    nostalgia:"sadness", sadness:"sadness", disappointment:"sadness", empathic_pain:"sadness", guilt:"sadness",
    anger:"anger", contempt:"anger", disgust:"anger", envy:"anger",
    fear:"fear", anxiety:"fear", horror:"fear",
    loneliness:"loneliness", boredom:"neutral", confusion:"neutral", calmness:"trust"
  };
  const _UNKNOWN_EMOTION_ZH = "未知情绪";
  function _emotionZh(key){
    const k=String(key==null?"":key).trim().toLowerCase();
    if(!k) return _UNKNOWN_EMOTION_ZH;
    return _EMO_ZH[k] || _UNKNOWN_EMOTION_ZH;
  }

  function palette() {
    const it = state.intent || {}, s = state.snapshot || {};
    const e = String(it.emotion || "neutral");
    let hue = { joy: 42, trust: 168, sadness: 214, fear: 260, anger: 12, surprise: 286, loneliness: 232, neutral: 196 }[e] || 196;
    hue = hue + (12 - hue) * clamp(s.stress) * .22;
    return { hue, sat: 26 + clamp(s.energy) * 18, stress: clamp(s.stress) };
  }
  function project(x, y, z, ry, rx) {
    // task-44: single geometry source in orb_math.js; R is applied exactly once
    // there, so callers pass WORLD units (1 unit = R px).
    const q = _OM.projectPoint(x, y, z, ry, rx, R);
    return { x: CX + q.x, y: CY + q.y, z: q.z };
  }

  let sig = null;
  if (signalCanvas) { const SD = Math.min(2, window.devicePixelRatio || 1); signalCanvas.width = 1000 * SD; signalCanvas.height = 160 * SD; sig = signalCanvas.getContext("2d"); sig.scale(SD, SD); }
  const hist = { echo: [], upper: [], lower: [], noise: [], spike: [], bio: [] };
  Object.keys(hist).forEach(k => { for (let i = 0; i < 120; i++) hist[k].push(.5); });
  function pushHistory(s) {
    const rp = s.ripple || {}, n = s.noise || {}, t = phase * 2.2;
    hist.echo.push(clamp((s.echo_trace || 0) * .5 + .5 + Math.sin(t * 1.3) * .045));
    hist.upper.push(clamp((rp.upper || 0) + Math.sin(t * .9 + 1.2) * .06));
    hist.lower.push(clamp((rp.lower || 0) + Math.cos(t * 1.1 + .4) * .06));
    hist.noise.push(clamp(.5 + (Number(n.energy || 0) + Number(n.social || 0)) * 1.6 + Math.sin(t * 1.8) * .08));
    hist.spike.push(clamp((s.spiking && s.spiking.rate || 0) * 6 + Math.max(0, Math.sin(t * 3.4)) * .25));
    // State-driven bio signal (not white noise): valence/arousal/energy/stress/echo.
    // Noise channels only modulate the high-frequency texture below.
    const _v = clamp((Number(s.v || 0) + 1) / 2);
    const _a = clamp(s.a == null ? .5 : s.a);
    const _energy = clamp(s.energy == null ? .5 : s.energy);
    const _stress = clamp(Math.abs(Number(n.stress || 0)) * 2 + Math.abs(Number(n.attention || 0)));
    const _echo = clamp(Math.abs(Number(s.echo_trace || s.echo || 0)));
    const _bio = clamp(.30 * _v + .22 * _a + .16 * _energy + .12 * (1 - _stress) + .10 * _echo +
                       .10 * (.5 + .5 * Math.sin(t * 1.1)));
    hist.bio.push(_bio);
    Object.keys(hist).forEach(k => { if (hist[k].length > 120) hist[k].shift(); });
  }
  function drawSignal() {
    if (!sig) return;
    const SW = 1000, SH = 160, LEFT = 42, RIGHT = 14, TOP = 18, BOT = SH - 24;
    sig.clearRect(0, 0, SW, SH);
    const zero = (TOP + BOT) / 2;

    // reference grid: vertical time ticks + horizontal +1 / 0 / -1
    sig.strokeStyle = "rgba(80,75,65,.12)"; sig.lineWidth = 1;
    for (let i = 0; i <= 6; i++) {
      const x = LEFT + i / 6 * (SW - LEFT - RIGHT);
      sig.beginPath(); sig.moveTo(x, TOP); sig.lineTo(x, BOT); sig.stroke();
    }
    [TOP, zero, BOT].forEach((y, i) => {
      sig.setLineDash(i === 1 ? [5, 7] : []);
      sig.strokeStyle = i === 1 ? "rgba(80,75,65,.34)" : "rgba(80,75,65,.16)";
      sig.beginPath(); sig.moveTo(LEFT, y); sig.lineTo(SW - RIGHT, y); sig.stroke();
    });
    sig.setLineDash([]);
    sig.fillStyle = "rgba(80,75,65,.46)";
    sig.font = "9px Bahnschrift, Segoe UI, sans-serif";
    sig.textBaseline = "middle";
    sig.fillText("+1", 8, TOP);
    sig.fillText("0", 8, zero);
    sig.fillText("-1", 8, BOT);

    const n = hist.echo.length;
    const s = state.snapshot || {};
    const noise = s.noise || {}, rp = s.ripple || {};
    const nAmp = clamp((Math.abs(noise.stress || 0) + Math.abs(noise.energy || 0) + Math.abs(noise.social || 0)) * 2.6);
    const echo = clamp(Math.abs(s.echo_trace || s.echo || 0));
    const overlap = clamp(rp.overlap || 0);
    const ripple = clamp((rp.upper || 0) + (rp.lower || 0));
    const spike = clamp((s.spiking && s.spiking.rate || 0) * 6);

    let reflection = 0;
    const vals = [];
    for (let i = 0; i < n; i++) {
      const t = i / (n - 1);
      const w1 = Math.sin(t * Math.PI * 6.0 + phase * 1.4);
      const w2 = Math.sin(t * Math.PI * 9.4 - phase * 1.0 + ripple * 2.6);
      const interference = (w1 + w2) * .5 * (1 + overlap * .9);
      const jitter = (Math.sin(t * Math.PI * 37 + phase * 7.0) + Math.sin(t * Math.PI * 23 - phase * 4.0)) * .5 * nAmp;
      let v = (hist.bio[i] - .5) * 2 * .58
            + interference * .34 + jitter * .20 + (hist.echo[i] - .5) * echo * .24;
      reflection = reflection * .93 + v * .18;
      v += reflection * .55 + (hist.spike[i] - .5) * spike * .50;
      vals.push(Math.max(-1, Math.min(1, v)));
    }
    const X = i => LEFT + i / (n - 1) * (SW - LEFT - RIGHT);
    const Y = v => zero - v * (BOT - TOP) / 2 * .92;

    // soft glow under the single line
    sig.beginPath();
    vals.forEach((v, i) => { if (i === 0) sig.moveTo(X(i), Y(v)); else sig.lineTo(X(i), Y(v)); });
    sig.lineTo(SW - RIGHT, zero); sig.lineTo(LEFT, zero); sig.closePath();
    const fill = sig.createLinearGradient(0, TOP, 0, BOT);
    fill.addColorStop(0, "rgba(255,107,0,.16)");
    fill.addColorStop(.5, "rgba(255,107,0,.04)");
    fill.addColorStop(1, "rgba(255,107,0,0)");
    sig.fillStyle = fill; sig.fill();

    const grad = sig.createLinearGradient(LEFT, 0, SW - RIGHT, 0);
    grad.addColorStop(0, "#ff6b00"); grad.addColorStop(.6, "#e99a3c"); grad.addColorStop(1, "#b85c40");
    sig.save();
    sig.shadowColor = "rgba(255,107,0,.34)"; sig.shadowBlur = 6;
    sig.beginPath();
    vals.forEach((v, i) => { if (i === 0) sig.moveTo(X(i), Y(v)); else sig.lineTo(X(i), Y(v)); });
    sig.strokeStyle = grad; sig.lineWidth = 2.1; sig.lineJoin = "round"; sig.lineCap = "round";
    sig.stroke();
    sig.restore();
    // current point
    const lv = vals[vals.length - 1];
    sig.beginPath(); sig.arc(X(n - 1), Y(lv), 2.4, 0, Math.PI * 2);
    sig.fillStyle = "#ff6b00"; sig.fill();
  }

  function ring(orbit, ry, rx, front, centerY) {
    const mv = orbitMetric(orbit, state.snapshot || {});
    // task-44: world-unit geometry sampled in orb_math.js; projectPoint applies
    // R once, so every channel is a CLOSED 3D ellipse of on-screen radius
    // R * (0.9 + 0.7 * metric) = 0.9R .. 1.6R (never a radial line / open arc).
    const dy = (typeof centerY === "number" ? centerY : CY) - CY;
    const pts = _OM.orbitRingPoints(orbit, mv, orbit.angle, ry, rx, R, 160)
      .map((q) => ({ x: CX + q.x, y: CY + q.y + dy, z: q.z }));
    let _c = orbit.color;
    if (isDark()) {
      if (/36,36,36|96,96,96/.test(_c)) _c = "228,224,214";
      else if (/142,132,120|196,148,82/.test(_c)) _c = "188,168,138";
    }
    // task-48 addendum: no binary front alpha/width multiplier. front only
    // selects the DRAW-ORDER pass (back half behind the core, front half in
    // front); alpha and line width are smooth functions of segment depth:
    //   alpha = base * (0.68 + 0.32 * depth), width = baseW * same shade.
    // 20 contiguous chunks keep the closed ellipse while depth transitions.
    const baseAlpha = 0.22 + 0.62 * mv;
    const baseWidth = 0.45 + 1.2 * mv;
    const segStep = Math.max(1, Math.floor((pts.length - 1) / 20));
    const _prevCap = ctx.lineCap, _prevJoin = ctx.lineJoin;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (let start = 0; start < pts.length - 1; start += segStep) {
      const end = Math.min(pts.length - 1, start + segStep);
      const zMid = (pts[start].z + pts[end].z) / 2;
      if ((zMid >= 0) !== front) continue;   // draw-order pass only
      const shade = _OM.ringShade(zMid);
      ctx.beginPath();
      ctx.moveTo(pts[start].x, pts[start].y);
      for (let i = start + 1; i <= end; i++) ctx.lineTo(pts[i].x, pts[i].y);
      ctx.strokeStyle = "rgba(" + _c + "," + (baseAlpha * shade).toFixed(3) + ")";
      ctx.lineWidth = baseWidth * shade;
      ctx.stroke();
    }
    ctx.lineCap = _prevCap;
    ctx.lineJoin = _prevJoin;
  }

  function latitude(r, offset, alpha, color) {
    ctx.beginPath();
    ctx.ellipse(CX, CY + offset, r, r * .28, 0, 0, Math.PI * 2);
    ctx.strokeStyle = color;
    ctx.globalAlpha = alpha;
    ctx.lineWidth = .8;
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  function shell(radius, alpha, bands) {
    // transparent glass fill
    const g = ctx.createRadialGradient(CX - 20, CY - 30, radius * .1, CX, CY, radius);
    g.addColorStop(0, "rgba(255,255,255,.02)");
    g.addColorStop(.72, "rgba(255,255,255,.07)");
    g.addColorStop(.94, "rgba(255,255,255,.14)");
    g.addColorStop(1, "rgba(255,255,255,.02)");
    ctx.beginPath(); ctx.arc(CX, CY, radius, 0, Math.PI * 2);
    ctx.fillStyle = g; ctx.fill();
    ctx.strokeStyle = isDark() ? "rgba(230,225,215,.32)" : "rgba(30,30,30,.38)"; ctx.lineWidth = .9;
    ctx.beginPath(); ctx.arc(CX, CY, radius, 0, Math.PI * 2); ctx.stroke();
    // latitude bands showing layers
    for (let i = -3; i <= 3; i++) {
      const off = i * radius * .19;
      const rr = Math.sqrt(Math.max(0, radius * radius - off * off));
      latitude(rr, off, .20, isDark() ? "rgba(230,225,215,.30)" : "rgba(30,30,30,.55)");
    }
    // longitude lines (rotating, visible through glass)
    for (let k = 0; k < 4; k++) {
      ctx.save();
      ctx.translate(CX, CY);
      ctx.rotate(phase * .12 + k * Math.PI / 4);
      ctx.beginPath(); ctx.ellipse(0, 0, radius * .38, radius, 0, 0, Math.PI * 2);
      ctx.strokeStyle = isDark() ? "rgba(230,225,215,.18)" : "rgba(30,30,30,.22)"; ctx.lineWidth = .6; ctx.stroke();
      ctx.restore();
    }
    bands.forEach((b, i) => {
      const rr = radius * b.r;
      ctx.beginPath(); ctx.arc(CX, CY, rr, 0, Math.PI * 2);
      ctx.strokeStyle = b.color; ctx.globalAlpha = b.alpha; ctx.lineWidth = 1.1; ctx.stroke(); ctx.globalAlpha = 1;
    });
  }



  function draw(ts) {
    requestAnimationFrame(draw);
    window.__biocoreOrbAlive = true;
    if (document.hidden) return;
    if (ts - lastFrame < 33) return;
    lastFrame = ts; frameCount++;
    // task-48: frame delta drives the smooth focus dim (no instant switch).
    const _frameDt = Math.max(.001, Math.min(.1,
      (ts - (_lastDrawTs || (ts - 33))) / 1000));
    _lastDrawTs = ts;
    if (window.__biocoreState) state = window.__biocoreState;
    const p = palette(), s = state.snapshot || {};
    const energy = clamp(s.energy), stress = p.stress, arousal = clamp(s.a);
    phase += .0025 + energy * .004 + arousal * .003;
    const breathe = 1 + Math.sin(phase * 1.5) * .018;
    const bob = Math.sin(phase * 1.15) * 5;
    const ry = phase * .42, rx = -.12 + Math.sin(phase * .3) * .08;
    // task-43: smooth focus camera. It centres the selected ball and follows its
    // live orbital position each frame (the ball itself is never frozen).
    const _camTargetNow = _OM.cameraTarget(
      _focusState.key ? _focusState.prev : null, CX, CY, !!_focusState.key);
    const _camNext = _OM.cameraStep(_cam, _camTargetNow);
    _cam.x = _camNext.x; _cam.y = _camNext.y; _cam.zoom = _camNext.zoom;
    if (!_focusState.key && Math.abs(_cam.zoom - 1) < 0.002) {
      _cam.x = CX; _cam.y = CY; _cam.zoom = 1;
    }
    window.__biocoreOrbCam = { x: _cam.x, y: _cam.y, zoom: _cam.zoom };  // task-43 observability
    ctx.clearRect(0, 0, W, H);
    _memHit.length = 0;
    let _focusFoundNow = false;
    ctx.save();
    ctx.translate(CX, CY);
    ctx.scale(_cam.zoom, _cam.zoom);
    ctx.translate(-_cam.x, -_cam.y);
    const cy = CY + bob;
    const _pNoise = s.noise || {};
    const _ap = s.appraisal || {};
    const _pNovelty = clamp(Number(_ap.novelty || 0));
    const _pGoal = clamp(Number(_ap.goal_relevance || 0));
    const _pCoping = clamp(Number(_ap.coping == null ? .5 : _ap.coping));
    const _pAttention = clamp(Math.abs(Number(_pNoise.attention || 0)) * 2.5);
    const _pA = clamp(Number(s.a == null ? .5 : s.a));
    const _pStress = clamp(Number(s.stress == null ? .2 : s.stress));
    const _spread = .86 + .22 * _pA + .08 * _pStress;       // calm tight, alert wide
    const _jitter = .006 + .026 * _pA + .012 * _pStress;    // world units, slow drift
    const _ringSpin = phase * 1.0;
    const _pPos = particles.map((p, i) => {
      const rr = p.r * _spread * (1 + Math.sin(phase * .42 + p.phase * 1.4) * .02);
      const a = p.a0 + _ringSpin * p.speed + Math.sin(phase * .30 + p.phase) * .01;
      const u = Math.cos(a) * rr;
      const v = Math.sin(a) * rr + Math.sin(phase * .50 + p.phase * 1.1) * _jitter;
      const x = u * Math.cos(p.yaw);
      const y = v * Math.cos(p.tilt) - u * Math.sin(p.yaw) * Math.sin(p.tilt);
      const z = v * Math.sin(p.tilt) + u * Math.sin(p.yaw) * Math.cos(p.tilt);
      const inward = 1 - .10 * _pGoal;
      const q = project(x * inward, y * inward, z * inward, ry, rx);
      return { x: q.x, y: q.y + (cy - CY), z: q.z, i };
    });
    const _pDraw = _pPos.slice().sort((a, b) => a.z - b.z);  // back first
    // task-42: orbit speed follows the metric's EMA change rate, not its
    // current value. No history => neutral volatility 0.5; the sign of
    // o.speed keeps each channel's fixed direction.
    orbits.forEach(o => {
      const mv = orbitMetric(o, s);
      const dt = Math.max(.001, (ts - (o._lastTs == null ? ts : o._lastTs)) / 1000);
      const first = o._init !== true;
      o._vol = _OM.orbitVolatility(first ? null : o._prevMetric, mv, dt, o._vol);
      o._prevMetric = mv;
      o._lastTs = ts;
      o._init = true;
      o.angle += _OM.orbitSpeed(o.speed, o._vol) * 0.045;
    });

    // particle links: fixed topology + per-edge alpha fade, only on hover or
    // high attention. Never rewired per frame, so edges cannot pop/flash.
    {
      const linksOn = (!state.visual || state.visual.links !== false) &&
        (_pAttention > .65 || _hoverOrb);
      ctx.save();
      ctx.lineWidth = .45;
      for (let k = 0; k < LINK_PAIRS.length; k++) {
        const target = linksOn ? .20 * LINK_PAIRS[k].w : 0;
        _linkFade[k] += (target - _linkFade[k]) * .12;
        const fade = _linkFade[k];
        if (fade < .004) continue;
        const pa = _pPos[LINK_PAIRS[k].a], pb = _pPos[LINK_PAIRS[k].b];
        const depth = clamp(.5 + (pa.z + pb.z) / 3.6);
        const alpha = (fade * (.45 + .55 * depth)).toFixed(3);
        ctx.strokeStyle = "hsla(" + p.hue.toFixed(0) + "," +
          (24 + 26 * _pA).toFixed(0) + "%," + (isDark() ? 64 : 44) + "%," + alpha + ")";
        ctx.beginPath();
        ctx.moveTo(pa.x, pa.y);
        ctx.lineTo(pb.x, pb.y);
        ctx.stroke();
      }
      ctx.restore();
    }

    // light halo
    const halo = ctx.createRadialGradient(CX, cy, R * .65, CX, cy, 235);
    halo.addColorStop(0, "hsla(" + p.hue + "," + p.sat + "%,55%,.08)");
    halo.addColorStop(1, "hsla(" + p.hue + "," + p.sat + "%,55%,0)");
    ctx.fillStyle = halo; ctx.beginPath(); ctx.arc(CX, cy, 235, 0, Math.PI * 2); ctx.fill();

    const _ringVis = state.visual || {};
    const _ringOrbits = orbits.filter(o => {
      if (o.key === "echo") return _ringVis.echo !== false;
      if (o.key === "rippleU" || o.key === "rippleL") return _ringVis.ripple !== false;
      if (o.key === "noise") return _ringVis.noise !== false;
      if (o.key === "dominance") return _ringVis.dominance !== false;
      if (o.key === "social") return _ringVis.social !== false;
      return true;
    });
    _ringOrbits.forEach(o => ring(o, ry, rx, false, cy));

    // Emotion-intensity rings: how strongly she feels = how many outer rings.
    // Count 1..4 from arousal + |valence| + dominance deviation; deterministic.
    if (!state.visual || state.visual.emotionRings !== false) {
      const _ev = Number(s.v || 0), _ea = clamp(s.a == null ? .5 : s.a);
      const _ed = Number(s.d == null ? .5 : s.d);
      const _eI = clamp(.42 * _ea + .33 * Math.abs(_ev) + .15 * Math.abs(_ed - .5) * 2 +
                        .10 * clamp(s.stress == null ? 0 : s.stress));
      const _ringCount = 1 + Math.floor(_eI * 3.999);   // 1..4
      window.__biocoreEmotionRings = _ringCount;
      for (let k = 0; k < _ringCount; k++) {
        const rr = R * (1.58 + 0.17 * k);
        const rot = phase * (0.22 + 0.10 * k) * (k % 2 ? -1 : 1);
        ctx.save();
        ctx.globalAlpha = 0.10 + 0.14 * _eI;
        ctx.strokeStyle = isDark() ? "rgba(225,220,205,.8)" : "rgba(96,88,74,.8)";
        ctx.lineWidth = .55;
        ctx.setLineDash([2 + k, 5 + k]);
        ctx.beginPath();
        if (ctx.ellipse) ctx.ellipse(CX, cy, rr, rr * (0.26 + 0.03 * k), rot, 0, Math.PI * 2);
        else ctx.arc(CX, cy, rr, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      }
    }

    // emotion node layer: 7 nodes projected from affect space
    if (!state.visual || state.visual.nodes !== false) {
      const _en = [
        { k: "joy",        x: .80, y: .58, z: .20, c: "242,193,78" },
        { k: "trust",      x: .45, y: .25, z: .35, c: "84,181,139" },
        { k: "sadness",    x: -.70, y: .25, z: -.10, c: "91,141,239" },
        { k: "fear",       x: -.55, y: .75, z: -.30, c: "139,92,246" },
        { k: "anger",      x: -.60, y: .70, z: .55, c: "229,83,61" },
        { k: "loneliness", x: -.45, y: .20, z: .15, c: "79,93,170" },
        { k: "neutral",    x: .05, y: .05, z: .50, c: "116,146,168" }
      ];
      const cur = String((state.intent || {}).emotion || "neutral");
      const _ev = clamp((Number(s.v || 0) + 1) / 2);
      const _ea = clamp(s.a == null ? .5 : s.a);
      const _ed = clamp(((s.d == null ? .5 : s.d) + 1) / 2);
      const _es = clamp(s.social == null ? .5 : s.social);
      const _eint = clamp(.45 * Math.abs(Number(s.v || 0)) + .25 * _ea + .15 * Math.abs(Number(s.d == null ? .5 : s.d) - .5) * 2 + .15 * _es);
      const _eRot = phase * .09;
      const _ePos = _en.map(n => {
        const nx = n.x * 155, ny = n.y * 145, nz = n.z * 155;
        const x = nx * Math.cos(_eRot) - nz * Math.sin(_eRot);
        const z = nx * Math.sin(_eRot) + nz * Math.cos(_eRot);
        const persp = 1 + z / 760;
        const dist = Math.sqrt(Math.pow(nx - (_ev * 2 - 1) * 140, 2) + Math.pow(ny - (_ea * 2 - 1) * 130, 2) + Math.pow(nz - (_ed * 2 - 1) * 120, 2));
        const infl = clamp(_eint * Math.exp(-dist / 150) * 1.6 + (n.k === cur ? .45 : 0));
        return { n, x: CX + x * persp, y: cy + ny * persp, z, persp, infl };
      });
      // influence links: only nearest pairs, faint
      if (!state.visual || state.visual.nodeLinks !== false) {
        ctx.save();
        ctx.lineWidth = .55;
        for (let i = 0; i < _ePos.length; i++) {
          const a = _ePos[i];
          for (let j = i + 1; j < _ePos.length; j++) {
            const b = _ePos[j];
            const d = Math.hypot(a.n.x - b.n.x, a.n.y - b.n.y, a.n.z - b.n.z);
            if (d > 1.55) continue;
            const strength = clamp(a.infl * Math.exp(-d * 1.8));
            if (strength < .06) continue;
            ctx.strokeStyle = "rgba(" + a.n.c + "," + (strength * .30).toFixed(3) + ")";
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          }
        }
        ctx.restore();
      }
      _ePos.forEach(q => {
        const r = 2.6 + 6.5 * q.infl;
        const alpha = .20 + .75 * q.infl;
        const col = q.n.c;
        ctx.save();
        ctx.globalAlpha = alpha;
        ctx.beginPath(); ctx.arc(q.x, q.y, r, 0, Math.PI * 2);
        ctx.fillStyle = "rgb(" + col + ")"; ctx.fill();
        ctx.globalAlpha = .18 + .35 * q.infl;
        ctx.beginPath(); ctx.arc(q.x, q.y, r * 2.4, 0, Math.PI * 2);
        ctx.strokeStyle = "rgba(" + col + ",.55)"; ctx.lineWidth = .8; ctx.stroke();
        ctx.globalAlpha = .55;
        ctx.font = "8px ui-monospace, monospace";
        ctx.fillStyle = isDark() ? "rgba(230,225,215,.75)" : "rgba(70,66,58,.75)";
        ctx.fillText(q.n.k.toUpperCase(), q.x + r + 3, q.y - r - 2);
        ctx.restore();
      });
    }

    // memory event nodes: one ball per real archived event (max 10 shown).
    // Identity (phase / inclination / periapsis) comes from a hash of
    // id / event_key, so list reordering or new arrivals cannot move old balls.
    // Balls exist only after consolidation/summarization (app.js sends the
    // summarized subset); no raw per-turn memories, no event fallback.
    const _allMem = Array.isArray(state.memories) ? state.memories : [];
    const _importantOnly = !state.visual || state.visual.memoryBallsImportant !== false;
    let _pickedMem = _allMem;
    if (_allMem.length && _importantOnly) {
      _pickedMem = _allMem.filter((ev) => ev && (ev._kind === "event" ||
        ev.self_defining === true ||
        Number(ev.importance == null ? 0 : ev.importance) >= 0.60));
    }
    const _memSource = _pickedMem;
    const _memEvents = _memSource.filter((ev) => ev && typeof ev === "object");
    const _memShown = _memEvents.slice(0, 10);
    const _memExtra = Math.max(0, _memEvents.length - _memShown.length);
    const _nowS = Date.now() / 1000;
    // Kepler I: r = a(1-e*cosE); Kepler II: faster at periapsis, slower at
    // apoapsis; Kepler III: n ∝ a^(-3/2) so near balls orbit faster.
    // Time radius: older events inner, recent events outer (fixed 60 day scale).
    if (!state.visual || state.visual.memoryNodes !== false) {
      // task-58: neutral is a calm blue-gray (#7492a8, close to center-ball hue
      // 196), not a gray-green; spectrum emotions resolve through their family
      // colour instead of falling back to grey.
      const _ec = { joy: "242,193,78", sadness: "91,141,239", anger: "229,83,61",
                    fear: "139,92,246", loneliness: "79,93,170",
                    neutral: "116,146,168", trust: "84,181,139" };
      const _emotionFamily = { admiration:"joy", adoration:"joy", aesthetic:"joy",
        amusement:"joy", awe:"joy", contentment:"joy", desire:"joy",
        excitement:"joy", interest:"joy", joy:"joy", pride:"joy", satisfaction:"joy",
        nostalgia:"sadness", sadness:"sadness", disappointment:"sadness",
        empathic_pain:"sadness", guilt:"sadness", shame:"sadness",
        anger:"anger", contempt:"anger", disgust:"anger", envy:"anger",
        fear:"fear", anxiety:"fear", horror:"fear",
        loneliness:"loneliness", trust:"trust", calmness:"trust",
        neutral:"neutral", boredom:"neutral", confusion:"neutral",
        awkwardness:"neutral", relief:"trust" };
      const _memN0 = .55;                 // mean motion at a = 1 orb unit
      if (_memExtra > 0) {
        // events beyond the display cap collapse into an outer archive belt
        const beltR = R * 2.12;
        const ticks = Math.min(24, _memExtra);
        ctx.save();
        ctx.globalAlpha = .16;
        ctx.strokeStyle = isDark() ? "rgba(225,220,205,.9)" : "rgba(96,88,74,.9)";
        ctx.lineWidth = .8;
        for (let k = 0; k < ticks; k++) {
          const ang = -Math.PI * .5 + (k / Math.max(1, ticks)) * Math.PI * 2;
          const x1 = CX + Math.cos(ang) * (beltR - 3), y1 = cy + Math.sin(ang) * (beltR - 3);
          const x2 = CX + Math.cos(ang) * (beltR + 3), y2 = cy + Math.sin(ang) * (beltR + 3);
          ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
        }
        ctx.globalAlpha = .55;
        ctx.fillStyle = isDark() ? "rgba(225,220,205,.9)" : "rgba(96,88,74,.9)";
        ctx.font = "9px ui-monospace, monospace";
        ctx.fillText("档案 +" + _memExtra, CX + beltR + 4, cy - beltR * .28);
        ctx.restore();
      } else if (!_memEvents.length) {
        // empty archive: show the empty memory orbit, never fake balls
        ctx.save();
        ctx.globalAlpha = .10;
        ctx.setLineDash([2, 6]);
        ctx.strokeStyle = isDark() ? "rgba(225,220,205,.9)" : "rgba(96,88,74,.9)";
        ctx.lineWidth = .7;
        ctx.beginPath(); ctx.arc(CX, cy, R * 1.55, 0, Math.PI * 2); ctx.stroke();
        ctx.restore();
      }
      const _balls = _memShown.map((ev) => {
        const imp = Math.max(0, Math.min(1, Number(ev.importance == null ? .5 : ev.importance)));
        const cent = Math.max(0, Math.min(1, Number(ev.centrality == null ? .5 : ev.centrality)));
        const recall = Math.max(0, Number(ev.recall_count || 0));
        // G11: stored merge_count decays on read (30-day half-life); ball mass
        // uses the effective value so an old duplicate does not stay "heavy".
        const merge = _effectiveMergeCount(ev);
        const tsS = Number(ev.ts || 0) > 0 ? Number(ev.ts) : _nowS;
        const ageDays = Math.max(0, (_nowS - tsS) / 86400);
        const ageNorm = Math.min(1, ageDays / 60);          // fixed 60d scale
        const mass = Math.max(.30, Math.min(1.40, .35 + .60 * imp +
          .20 * Math.min(1, recall / 5) + .10 * Math.min(1, merge / 4)));
        const timeRadius = R * (1.95 - 1.32 * ageNorm);     // recent outer, old inner
        const pull = 26 * Math.min(1, (mass - .30) / 1.10); // mass pulls inward
        const radius = Math.max(40, timeRadius - pull);
        const a = radius / R;
        const key = String(ev.id || ev.event_key || ev.title || tsS);
        const h = _hashStr(key);
        const ph0 = (h % 1000) / 1000 * Math.PI * 2;
        const w = ((h >>> 9) % 1000) / 1000 * Math.PI * 2;
        const sessInc = ((_hashStr(ev.session || "default") % 200) / 200 - .5) * .18;
        const inc = ((((h >>> 19) % 1000) / 1000 - .5) * .8) + sessInc;
        // centrality: core events near-circular, peripheral more elliptical
        const ecc = .04 + .22 * (1 - cent) + (((h >>> 5) % 100) / 100) * .03;
        const M = ph0 + _memN0 * Math.pow(1 / Math.max(.35, a), 1.5) * phase;
        let E = M;
        for (let k = 0; k < 3; k++) {
          const d = (E - ecc * Math.sin(E) - M) / (1 - ecc * Math.cos(E));
          E -= d;
          if (Math.abs(d) < 1e-4) break;
        }
        const nu = 2 * Math.atan2(Math.sqrt(1 + ecc) * Math.sin(E / 2),
                                  Math.sqrt(1 - ecc) * Math.cos(E / 2));
        const r = a * (1 - ecc * Math.cos(E));
        const ox = r * Math.cos(nu + w);
        const oy0 = r * Math.sin(nu + w);
        const oy = oy0 * Math.cos(inc);
        const oz = oy0 * Math.sin(inc);
        const q = project(ox, oy, oz, ry, rx);
        return { ev, key, imp, cent, recall, merge, tsS, ageDays, ageNorm, mass,
                 x: q.x, y: q.y + (cy - CY), z: q.z,
                 front: q.z >= 0, size: 0 };
      });
      // task-70: memory-ball gravity (visual only). mass=.3+.7*importance,
      // range=R*(.25+.55*importance); pairs closer than range attract with
      // F=G*mass_i*mass_j/(dist^2+soft); offsets are lerped .12/frame, capped
      // at 10px, kept out of the centre ball and separated to avoid overlap.
      // The offset is applied to the Kepler (x,y) before z-sort/hit/tooltip/
      // rings/camera; event data is never touched.
      const _gravityOn = !(state.visual && state.visual.memoryBallGravity === false);
      if (_gravityOn && _balls.length > 1) {
        const _G = 2.4, _soft = 64, _capPx = 10;
        _balls.forEach((b, idx) => {
          const mass = .3 + .7 * b.imp;
          const range = R * (.25 + .55 * b.imp);
          b.gravityMass = mass;
          b.gravityRange = range;
          let fx = 0, fy = 0;
          _balls.forEach((o, j) => {
            if (j === idx) return;
            const dx = o.x - b.x, dy = o.y - b.y;
            const dist = Math.hypot(dx, dy);
            if (dist <= 1e-6 || dist >= range) return;
            const force = _G * mass * (.3 + .7 * o.imp) / (dist * dist + _soft);
            fx += dx / dist * force;
            fy += dy / dist * force;
          });
          const mag = Math.hypot(fx, fy);
          let tx = 0, ty = 0;
          if (mag > 1e-9) {
            const scaled = Math.min(_capPx, 1.8 * mag);
            tx = fx / mag * scaled;
            ty = fy / mag * scaled;
          }
          const prev = _ballGravityOffsets.get(b.key) || { x: 0, y: 0 };
          const nx = prev.x + (tx - prev.x) * 0.12;
          const ny = prev.y + (ty - prev.y) * 0.12;
          _ballGravityOffsets.set(b.key, { x: nx, y: ny });
          b.gravityMass = mass;
          b.gravityRange = range;
          b.gravityOffset = { x: nx, y: ny };
          b.gravityForce = { x: fx, y: fy };
        });
        _balls.forEach((b) => {
          b.x += (b.gravityOffset || { x: 0, y: 0 }).x;
          b.y += (b.gravityOffset || { x: 0, y: 0 }).y;
        });
        _balls.forEach((b) => {
          const dx = b.x - CX, dy = b.y - cy;
          const dist = Math.hypot(dx, dy) || 1;
          const minR = R * 0.75;
          if (dist < minR) {
            b.x = CX + dx / dist * minR;
            b.y = cy + dy / dist * minR;
          }
        });
        for (let i = 0; i < _balls.length; i++) {
          for (let j = i + 1; j < _balls.length; j++) {
            const a = _balls[i], c = _balls[j];
            const dx = c.x - a.x, dy = c.y - a.y;
            const dist = Math.hypot(dx, dy) || 0.001;
            const minD = 16;
            if (dist < minD) {
              const push = (minD - dist) / 2;
              const ux = dx / dist, uy = dy / dist;
              a.x -= ux * push; a.y -= uy * push;
              c.x += ux * push; c.y += uy * push;
            }
          }
        }
      } else {
        _balls.forEach((b) => {
          b.gravityMass = .3 + .7 * b.imp;
          b.gravityRange = R * (.25 + .55 * b.imp);
          b.gravityOffset = { x: 0, y: 0 };
          b.gravityForce = { x: 0, y: 0 };
        });
      }
      window.__biocoreGravity = { enabled: _gravityOn,
        balls: _balls.map((b) => ({
          id: b.key,
          mass: Number((b.gravityMass || .3 + .7 * b.imp).toFixed(4)),
          range: Number((b.gravityRange || R * (.25 + .55 * b.imp)).toFixed(2)),
          offset: Number(Math.hypot(
            (b.gravityOffset || {}).x || 0, (b.gravityOffset || {}).y || 0).toFixed(3)),
          force: Number(Math.hypot(
            (b.gravityForce || {}).x || 0, (b.gravityForce || {}).y || 0).toFixed(3))
        })) };
      _balls.sort((p, q) => p.z - q.z);   // back to front
      _balls.forEach((b) => {
        const ev = b.ev;
        // task-43: selected ball highlighted, every other ball dimmed.
        const focused = !!_focusState.key && b.key === _focusState.key;
        // task-48: continuous depth factor replaces the binary front multiplier
        // (front is now only used for draw order; balls stay z-sorted). dimK is
        // smoothed every frame toward its focus target (~200ms, no snap).
        const depthK = _OM.depthFactor(b.z);
        const dimTgt = _OM.dimTarget(focused, !!_focusState.key);
        const dimPrev = _ballDims.has(b.key) ? _ballDims.get(b.key) : dimTgt;
        const dimK = _OM.smoothToward(dimPrev, dimTgt, _frameDt, _OM.DIM_TAU);
        _ballDims.set(b.key, dimK);
        if (focused) {
          _focusFoundNow = true;
          _focusState.prev = { x: b.x, y: b.y };   // camera follow target next frame
        }
        const _emoRaw = String(ev.emotion || "neutral").trim().toLowerCase();
        let col = _ec[_emotionFamily[_emoRaw] || _emoRaw] || _ec.neutral;
        if (ev._kind === "memory" && !ev.emotion_known) col = "142,148,158";
        // task-69: mixed ball colour (default) blends the top-3 emotion layers
        // by p in OKLCH with a 60% primary-emotion floor; primary mode keeps
        // the old single primary colour.
        const _ballColorMode = String((state.visual && state.visual.memoryBallColorMode) || "mixed")
          .toLowerCase() === "primary" ? "primary" : "mixed";
        window.__biocoreBallColorMode = _ballColorMode;
        let _ballPrimaryWeight = 1;
        let _mixedBall = null;
        let _ballWeights = [];
        const _ballEmotionRgb = (emotion) => _ec[_emotionFamily[emotion] || emotion] || _ec.neutral;
        // task-68/69 final: emotion layers carry four independent signals.
        // Ring score = .45*intensity + .35*share + .20*centrality with
        // share = intensity/sum(all intensities). A layer becomes a ring only
        // when intensity >= .15 AND confidence >= .50 AND (share >= .10 OR
        // centrality >= .70); rings are taken by score until cumulative share
        // reaches .85 (dynamic 0-N). ONLY ring layers tint the ball; the ball
        // weights are intensity-normalized across the selected rings.
        const _layerItems = (Array.isArray(ev.emotion_layers) ? ev.emotion_layers : [])
          .map((item) => {
            const intensity = (item && item.intensity != null)
              ? item.intensity : (item && item.p);
            const confidence = (item && item.confidence != null)
              ? item.confidence : 0.5;
            const centrality = (item && item.centrality != null)
              ? item.centrality : 0.5;
            return { emotion: String((item && item.emotion) || "").trim().toLowerCase(),
                     intensity: _bound(Number(intensity) || 0, 0, 1),
                     confidence: _bound(Number(confidence) || 0, 0, 1),
                     centrality: _bound(Number(centrality) || 0, 0, 1) };
          })
          .filter((item) => item.emotion && item.intensity > 0)
          .sort((a, b2) => b2.intensity - a.intensity);
        const _layerSum = _layerItems.reduce((acc, x) => acc + x.intensity, 0);
        const _ringSelected = [];
        if (_layerItems.length && _layerSum > 0) {
          const _scored = _layerItems.map((item) => {
            const share = item.intensity / _layerSum;
            return Object.assign({}, item, {
              share: share,
              score: 0.45 * item.intensity + 0.35 * share + 0.20 * item.centrality,
              eligible: item.intensity >= 0.15 && item.confidence >= 0.50
                && (share >= 0.10 || item.centrality >= 0.70)
            });
          }).filter((x) => x.eligible).sort((a, b2) => b2.score - a.score);
          let _cumulative = 0;
          for (let _i = 0; _i < _scored.length; _i++) {
            _ringSelected.push(_scored[_i]);
            _cumulative += _scored[_i].share;
            if (_cumulative >= 0.85) break;
          }
          const _primaryAt = _ringSelected.findIndex((x) => x.emotion === _emoRaw);
          if (_primaryAt > 0) {
            const _primaryItem = _ringSelected.splice(_primaryAt, 1)[0];
            _ringSelected.unshift(_primaryItem);
          }
        }
        if (_ballColorMode === "mixed") {
          const _visible = [];
          if (_ringSelected.length) {
            // only ring layers participate in the ball colour
            _ringSelected.forEach((x) => _visible.push({ emotion: x.emotion, p: x.intensity }));
          } else if (_layerItems.length) {
            // layers exist but none became a ring: ball stays a pure base colour
            _visible.push({ emotion: _emoRaw, p: null });
          } else {
            const _secColor = String(ev.emotion_secondary || "").trim().toLowerCase();
            // old layers=null: ONE pure colour, never a fabricated mix
            if (_secColor && _secColor !== _emoRaw) {
              _visible.push({ emotion: _secColor, p: null });
            } else {
              _visible.push({ emotion: _emoRaw, p: null });
            }
          }
          const _weights = _visible.map((item) => (item.p == null ? 1 : item.p));
          const _weightSum = _weights.reduce((acc, w) => acc + w, 0);
          _ballWeights = _visible.map((item, idx) =>
            (_weightSum > 0 ? _weights[idx] / _weightSum : 0));
          const _entries = [];
          _visible.forEach((item, idx) => {
            if (_ballWeights[idx] > 0) {
              _entries.push({ rgb: _ballEmotionRgb(item.emotion),
                              weight: _ballWeights[idx] });
            }
          });
          _ballPrimaryWeight = (_visible.length && _visible[0].emotion === _emoRaw)
            ? _ballWeights[0] : 0;
          _mixedBall = _mixOklch(_entries);
        }
        const bodyHsl = _vividHsl(col, b.imp);   // saturated, slightly deep
        const primaryRingHsl = { h: bodyHsl.h, s: bodyHsl.s, l: Math.min(60, bodyHsl.l + 7) };
        const _secKey = String(ev.emotion_secondary || "").trim();
        const _secRgb = _secKey ? (_ec[_emotionFamily[_secKey] || _SECONDARY_FAMILY[_secKey] || _secKey] || "") : "";
        const _secHsl = _secRgb ? _vividHsl(_secRgb, b.imp) : null;
        // task-54 addendum: old records without emotion_secondary get an
        // INFERRED secondary colour (primary hue +40deg, 62% saturation, close
        // lightness) instead of gray or the primary colour. The UI marks it as
        // inferred (示意); a regenerated event gets a real secondary instead.
        const inferredRingHsl = _OM.inferredSecondaryHsl(bodyHsl.h, bodyHsl.s, bodyHsl.l);
        const ringHsl = _secHsl
          ? { h: _secHsl.h, s: _secHsl.s, l: Math.min(60, _secHsl.l + 7) }
          : inferredRingHsl;   // old data/no secondary: inferred secondary hue
        const bodyFill = (_ballColorMode === "mixed" && _mixedBall)
          ? _mixedBall.css
          : "hsl(" + bodyHsl.h.toFixed(0) + "," + bodyHsl.s.toFixed(0) + "%," + bodyHsl.l.toFixed(0) + "%)";
        const ringFill = "hsl(" + ringHsl.h.toFixed(0) + "," + ringHsl.s.toFixed(0) + "%," + ringHsl.l.toFixed(0) + "%)";
        const ageAlpha = .16 + .70 * (1 - b.ageNorm);
        const forgotten = ev.peripheral_forgotten === true;
        const status = String((ev.source_check && ev.source_check.status) || "ok").toLowerCase();
        const recallN = Math.min(1, b.recall / 5);
        const sinceRecall = Math.max(0, _nowS - Number(ev.last_recall || b.tsS));
        const recallFresh = Math.exp(-sinceRecall / 86400);
        const haloPulse = .85 + .15 * Math.sin(phase * (.55 + .45 * recallN) + b.ageDays);
        // Ball size is dominated by memory/event importance (not recall count).
        const size = (1.6 + 8.0 * Math.pow(b.imp, 0.75) +
          0.6 * Math.min(1, b.recall / 5)) * depthK;
        b.size = size;
        const fillAlpha = (.14 + .52 * b.imp) * ageAlpha * (.55 + .45 * b.cent) * depthK;
        const haloAlpha = (.06 + .12 * recallN + .05 * recallFresh) * ageAlpha *
          haloPulse * (forgotten ? .35 : 1);
        const suspect = status === "suspect";
        // [BC] memory ball: size=importance, orbit=time; only one secondary ring.
        ctx.save();
        // halo: brightness + pulse rate follow recall_count / last_recall
        ctx.globalAlpha = clamp(haloAlpha * dimK);
        ctx.beginPath(); ctx.arc(b.x, b.y, size * (2.1 + .35 * recallN), 0, Math.PI * 2);
        ctx.strokeStyle = "hsla(" + primaryRingHsl.h.toFixed(0) + "," + primaryRingHsl.s.toFixed(0) + "%," + primaryRingHsl.l.toFixed(0) + "%,.42)";
        ctx.lineWidth = .7; ctx.stroke();
        // body: centrality controls solidity; forgotten becomes a hollow ring
        // task-70: the body must stay more opaque than its rings. Base body
        // alpha floor .85 / cap .96; depth/dim are kept as a shared scene
        // factor so bodyAlpha >= ringAlpha holds in every state.
        const _sceneAlphaK = (0.94 + 0.06 * depthK) * dimK;
        const _bodyAlphaBase = _bound(.85 + .11 * b.imp, .85, .96);
        const bodyAlpha = _bound(_bodyAlphaBase * _sceneAlphaK,
          .85 * _sceneAlphaK, .96);
        if (forgotten) {
          ctx.globalAlpha = Math.max(.18, bodyAlpha * .50 * dimK);
          ctx.beginPath(); ctx.arc(b.x, b.y, size, 0, Math.PI * 2);
          ctx.strokeStyle = bodyFill; ctx.lineWidth = 1; ctx.stroke();
        } else {
          ctx.globalAlpha = clamp(bodyAlpha * dimK);
          ctx.beginPath(); ctx.arc(b.x, b.y, size, 0, Math.PI * 2);
          ctx.fillStyle = bodyFill; ctx.fill();
        }
        // task-65: 0-3 emotion rings, one per non-primary emotion layer.
        // New archive records carry emotion_layers (top-4 spectrum probs incl.
        // the primary). Rings exclude the primary, keep p >= .15, sort desc and
        // cap at 3 -- never pad to a fixed count. Old records fall back to ONE
        // secondary ring (or ONE inferred ring when no secondary was stored);
        // they never fabricate a 3rd/4th ring.
        const _primaryEmo = String(ev.emotion || "neutral").trim().toLowerCase();
        // task-66: ring rotation speed follows the archived emotion intensity.
        // Old records fall back to importance then emotion_layers[0].p.
        const _intensityRaw = Number(ev.emotion_intensity);
        let _emoIntensity = Number.isFinite(_intensityRaw) ? clamp(_intensityRaw) : null;
        const _rawLayers = Array.isArray(ev.emotion_layers) ? ev.emotion_layers : null;
        if (_emoIntensity == null && _rawLayers && _rawLayers.length) {
          _emoIntensity = clamp(Number((_rawLayers[0] || {}).p) || 0);
        }
        if (_emoIntensity == null) {
          _emoIntensity = clamp(Number(ev.importance == null ? 0.5 : ev.importance));
        }
        const speedFactor = 1.0 + 1.8 * _emoIntensity;
        window.__biocoreOrbitSpeed = { intensity: Number(_emoIntensity.toFixed(4)),
          speedFactor: Number(speedFactor.toFixed(3)) };
        let _rings = [];
        if (_ballColorMode === "mixed") {
          if (_rawLayers) {
            // ring selection already computed above (four-signal scorer)
            _rings = _ringSelected.map((item) => ({
              emotion: item.emotion, p: item.intensity, inferred: false,
              primary: item.emotion === _primaryEmo,
              score: Number(item.score.toFixed(4)),
              share: Number(item.share.toFixed(4))
            }));
          } else {
            // old layers=null: ONE pure ring (secondary if present, else primary)
            _rings = _secKey
              ? [{ emotion: _secKey, p: null, inferred: false }]
              : [{ emotion: _primaryEmo, p: null, inferred: false, primary: true }];
          }
        } else if (_rawLayers) {
          const _primaryModeRings = _rawLayers.map((item) => {
            const intensity = (item && item.intensity != null)
              ? Number(item.intensity) : Number((item && item.p) || 0);
            return {
              emotion: String((item && item.emotion) || "").trim().toLowerCase(),
              p: intensity,
              inferred: false
            };
          }).filter((item) => item.emotion && item.emotion !== _primaryEmo
              && item.p >= 0.15)
            .sort((a, b2) => b2.p - a.p)
            .slice(0, 3);
          _rings = _primaryModeRings;
        } else {
          _rings = [{ emotion: _secKey, p: null, inferred: !_secKey }];
        }
        const _ringWeights = _rings.map((item) => (item.p == null ? b.imp : item.p));
        const _ringWidths = _rings.map((item, idx) =>
          _bound(1.2 + 1.4 * _ringWeights[idx], 1.8, 2.8));
        const _primaryRingIdx = _rings.findIndex((item) => item.primary);
        if (_primaryRingIdx >= 0) {
          // primary ring is the closest and the thickest one
          _ringWidths[_primaryRingIdx] = Math.min(2.8,
            Math.max.apply(null, _ringWidths) + 0.15);
        }
        const _outerRing = size + 4.2 + Math.max(0, _rings.length - 1) * 2.4;
        const _ringStyle = String((state.visual && state.visual.memoryRingStyle) || "orbit")
          .toLowerCase() === "solid" ? "solid" : "orbit";
        window.__biocoreMemoryRingStyle = _ringStyle;
        window.__biocoreRing = {
          style: _ringStyle, ringCount: _rings.length, ringLayers: [],
          alpha: 0, width: 0, highlightAlpha: 0, highlightLen: 0,
          orbitTilt: 0.42, hasAuxEllipse: false, rotates: _ringStyle === "orbit",
          hasHighlight: false, spin: 0,
          orbitYaw: 0, orbitPitch: 0.42, orbitPts: [], highlightAngle: 0,
          orbitHighlightLen: 0, emotionIntensity: Number(_emoIntensity.toFixed(4)),
          speedFactor: Number(speedFactor.toFixed(3)),
          yawRate: Number((0.9 * speedFactor).toFixed(3)),
          colorMode: _ballColorMode, ballColor: bodyFill,
          ballOklch: _mixedBall,
          ballWeights: _ballWeights.map((w) => Number(w.toFixed(4))),
          primaryWeight: Number((_ballPrimaryWeight || 0).toFixed(3))
        };
        const fullTurn = Math.PI * 2;
        const highlightLen = fullTurn * (0.18 + 0.07 * b.imp);
        const _orbitTilts = [0.42, 0.30, 0.18];
        // task-66: yaw rate is faster than the old fixed .42 and scales with the
        // emotion intensity (low intensity stays slow but visible).
        const _phaseYaw = phase * 0.9 * speedFactor;
        const _phasePitch = 0.42 +
          (0.08 + 0.06 * _emoIntensity) * Math.sin(phase * (0.55 + 0.45 * speedFactor));
        _rings.forEach((ringItem, ringIdx) => {
          const weight = ringItem.p == null ? b.imp : ringItem.p;
          const ringBaseR = size + 4.2 + ringIdx * 2.4;
          // task-70: shared scene factor, ring alpha capped at .80
          const ringAlphaR = _bound((.55 + .30 * weight) * _sceneAlphaK,
            .55 * _sceneAlphaK, .80);
          const ringWidthR = _ringWidths[ringIdx];
          let ringColorR;
          if (ringItem.inferred) {
            ringColorR = "hsla(" + inferredRingHsl.h.toFixed(0) + "," +
              inferredRingHsl.s.toFixed(0) + "%," +
              inferredRingHsl.l.toFixed(0) + "%,0.95)";
          } else if (ringItem.primary && _ballColorMode === "mixed") {
            const _ringHsl = _vividHsl(_ballEmotionRgb(ringItem.emotion),
              _bound(weight, 0.15, 1));
            ringColorR = "hsl(" + _ringHsl.h.toFixed(0) + "," +
              _ringHsl.s.toFixed(0) + "%," + Math.min(60, _ringHsl.l + 7).toFixed(0) + "%)";
          } else if (ringItem.p == null && _secHsl) {
            ringColorR = ringFill;   // old records: keep the previous secondary colour
          } else {
            const rgb = _ec[_emotionFamily[ringItem.emotion] || ringItem.emotion] || _ec.neutral;
            const hsl = _vividHsl(rgb, _bound(weight, 0.15, 1));
            ringColorR = "hsl(" + hsl.h.toFixed(0) + "," + hsl.s.toFixed(0) + "%," +
              Math.min(60, hsl.l + 7).toFixed(0) + "%)";
          }
          ctx.save();
          ctx.globalAlpha = ringAlphaR;
          ctx.setLineDash([]);
          if (_ringStyle === "orbit") {
            const tilt = (typeof _orbitTilts[ringIdx] === "number")
              ? _orbitTilts[ringIdx]
              : Math.max(0.08, 0.42 - ringIdx * 0.12);
            const yaw = _phaseYaw;
            const pitch = _phasePitch + (tilt - 0.42) * 0.5;
            const steps = 48;
            const orbitPoint = (a, radius) => {
              const cx0 = Math.cos(a) * radius;
              const cz0 = Math.sin(a) * radius;
              const ey = cz0 * Math.sin(pitch);
              const ez = cz0 * Math.cos(pitch);
              const yawCos = Math.cos(yaw), yawSin = Math.sin(yaw);
              const ex2 = cx0 * yawCos - ez * yawSin;
              const ez2 = cx0 * yawSin + ez * yawCos;
              const persp = 1 + (ez2 / Math.max(1, radius)) * 0.16;
              return { x: b.x + ex2 * persp,
                       y: b.y + ey * persp + (ez2 / Math.max(1, radius)) * 2.0 };
            };
            ctx.beginPath();
            for (let sIdx = 0; sIdx <= steps; sIdx++) {
              const pnt = orbitPoint(sIdx / steps * fullTurn, ringBaseR);
              if (sIdx === 0) ctx.moveTo(pnt.x, pnt.y); else ctx.lineTo(pnt.x, pnt.y);
            }
            ctx.closePath();
            ctx.strokeStyle = ringColorR;
            ctx.lineWidth = ringWidthR;
            ctx.stroke();
            if (ringIdx === 0) {
              ctx.globalAlpha = _bound(ringAlphaR * 0.28, 0.10, 0.30);
              ctx.beginPath();
              for (let aIdx = 0; aIdx <= steps; aIdx++) {
                const pnt = orbitPoint(aIdx / steps * fullTurn, ringBaseR * 1.06);
                if (aIdx === 0) ctx.moveTo(pnt.x, pnt.y); else ctx.lineTo(pnt.x, pnt.y);
              }
              ctx.closePath();
              ctx.strokeStyle = ringColorR;
              ctx.lineWidth = _bound(ringWidthR * 0.5, 0.9, 1.4);
              ctx.stroke();
              window.__biocoreRing.hasAuxEllipse = true;
              window.__biocoreRing.orbitYaw = Number(yaw.toFixed(4));
              window.__biocoreRing.orbitPitch = Number(pitch.toFixed(4));
              window.__biocoreRing.orbitPts = [0, 0.25, 0.5, 0.75].map((t) => {
                const pnt = orbitPoint(t * fullTurn, ringBaseR);
                return [Number((pnt.x - b.x).toFixed(2)), Number((pnt.y - b.y).toFixed(2))];
              });
            }
          } else {
            // solid: complete 360° static circle for every layer (no rotation,
            // no highlight arc).
            ctx.beginPath();
            ctx.arc(b.x, b.y, ringBaseR, 0, fullTurn);
            ctx.strokeStyle = ringColorR;
            ctx.lineWidth = ringWidthR;
            ctx.stroke();
          }
          ctx.restore();
          window.__biocoreRing.ringLayers.push({
            emotion: ringItem.inferred ? "" : ringItem.emotion,
            inferred: !!ringItem.inferred,
            p: ringItem.p == null ? null : Number(weight.toFixed(4)),
            width: Number(ringWidthR.toFixed(2)),
            alpha: Number(ringAlphaR.toFixed(3)),
            tilt: _ringStyle === "orbit" ? _orbitTilts[Math.min(ringIdx, 2)] : 0,
            role: ringItem.primary ? "primary"
              : (ringItem.inferred ? "inferred" : "secondary"),
            score: ringItem.score == null ? null : Number(ringItem.score),
            share: ringItem.share == null ? null : Number(ringItem.share),
            color: ringColorR,
            family: ringItem.inferred ? "inferred"
              : (_emotionFamily[ringItem.emotion] || ringItem.emotion)
          });
          if (ringIdx === 0) {
            window.__biocoreRing.alpha = Number(ringAlphaR.toFixed(3));
            window.__biocoreBallVisual = {
              forgotten: !!forgotten,
              bodyBase: Number(_bodyAlphaBase.toFixed(3)),
              bodyAlpha: Number(bodyAlpha.toFixed(3)),
              ringMax: Number(ringAlphaR.toFixed(3)),
              sceneK: Number(_sceneAlphaK.toFixed(3))
            };
            window.__biocoreRing.width = Number(ringWidthR.toFixed(2));
            window.__biocoreRing.highlightAlpha = 0;
            window.__biocoreRing.spin = _ringStyle === "orbit" ? Number(phase.toFixed(4)) : 0;
          }
        });
        const ringBase = _outerRing;   // suspect/focus rings + hit radius
        // Source state lives in the tooltip; only a suspect source gets the
        // orange dashed ring (no normal source ring anymore).
        if (suspect) {
          ctx.globalAlpha = .9;
          ctx.setLineDash([2.5, 3]);
          ctx.beginPath(); ctx.arc(b.x, b.y, ringBase + 3.6, 0, Math.PI * 2);
          ctx.strokeStyle = "rgba(214,120,64,.9)";
          ctx.lineWidth = .8; ctx.stroke();
          ctx.setLineDash([]);
        }
        // task-43: highlighted focus ring around the selected ball.
        if (focused) {
          ctx.globalAlpha = .55 + .20 * Math.sin(phase * 2.4);
          ctx.beginPath(); ctx.arc(b.x, b.y, ringBase + 6.5, 0, Math.PI * 2);
          ctx.strokeStyle = isDark() ? "rgba(245,240,230,.9)" : "rgba(40,36,30,.75)";
          ctx.lineWidth = 1.2;
          ctx.setLineDash([1.5, 3.5]);
          ctx.stroke();
          ctx.setLineDash([]);
        }
        ctx.restore();
        _memHit.push({ x: b.x, y: b.y, r: ringBase + (suspect ? 5 : 2), ev, imp: b.imp,
                       key: b.key, tsS: b.tsS, ageDays: b.ageDays, front: b.front });
      });
      // keep the smooth dim cache bounded to the balls currently displayed.
      const _liveBallKeys = new Set(_balls.map((b) => b.key));
      _ballDims.forEach((value, key) => {
        if (!_liveBallKeys.has(key)) _ballDims.delete(key);
      });
      _ballGravityOffsets.forEach((value, key) => {
        if (!_liveBallKeys.has(key)) _ballGravityOffsets.delete(key);
      });
    }
    // selected ball vanished (visibility toggle / filter / archive change): fall
    // back to the global view instead of leaving a stale zoom.
    if (_focusState.key && !_focusFoundNow) exitBallFocus();
    // task-43 observability (used by scripts/eval_orb_focus.py runtime smoke).
    window.__biocoreMemHits = _memHit.map((h) => ({ x: h.x, y: h.y, r: h.r, key: h.key }));

    // solid emotion-colored core: color-sphere mapping
    // hue = emotion family, saturation/distance from white = intensity,
    // low arousal/low |valence| fades toward white (calm center).
    const sr = R * .58 * breathe;
    const _moodHue = {
      joy: 42, trust: 168, sadness: 214,
      fear: 260, anger: 12, surprise: 24,
      loneliness: 232, neutral: 196
    }[String((state.intent||{}).emotion || "neutral")] || 196;
    const _mv = Math.abs(Number(s.v || 0));
    const _ma = clamp(Number(s.a == null ? 0.4 : s.a));
    const _ms = clamp(Number(s.stress || 0));
    // a = baseline activation, |v| = emotional charge, stress = extra tint.
    // task-58: two-sided bounds keep the core readable at every intensity. A
    // calm state must not wash out to white (sat >= 45, light <= 76, alpha >=
    // .45) and a strong state must not oversaturate (sat <= 92, light >= 48,
    // alpha <= .88). The white glass highlight is a separate bounded overlay.
    const _miRaw = clamp(0.55 * _ma + 0.35 * _mv + 0.10 * _ms);
    const _mi = _bound(Math.max(0.35, _miRaw), 0.35, 1);
    const _mSat = _bound(40 + 55 * _mi, 45, 92);
    const _mLight = _bound(76 - 26 * _mi, 48, 76);
    const _mAlpha = _bound(0.45 + 0.43 * _mi, 0.45, 0.88);
    const moodColor = "hsl(" + _moodHue + " " + _mSat.toFixed(1) + "% " + _mLight.toFixed(1) + "%)";
    const _hlAlpha = _bound(0.08 + 0.12 * _mi, 0.04, 0.22);
    window.__biocoreMoodColor = {
      hue: _moodHue,
      sat: Number(_mSat.toFixed(2)),
      light: Number(_mLight.toFixed(2)),
      alpha: Number(_mAlpha.toFixed(3)),
      mi: Number(_mi.toFixed(3)),
      whiteHighlightAlpha: Number(_hlAlpha.toFixed(3))
    };
    // The core is always glassy: translucent emotion fill + one bounded white
    // specular highlight (total overlay 0.04..0.22, never enough to bleach it).
    ctx.save();
    ctx.globalAlpha = _mAlpha;
    ctx.beginPath(); ctx.arc(CX, cy, sr, 0, Math.PI * 2);
    ctx.fillStyle = moodColor; ctx.fill();
    ctx.strokeStyle = "rgba(20,20,20,.28)"; ctx.lineWidth = 1; ctx.stroke();
    ctx.restore();
    const _hl = ctx.createRadialGradient(CX - sr * 0.32, cy - sr * 0.38, sr * 0.08,
                                         CX - sr * 0.32, cy - sr * 0.38, sr * 1.05);
    _hl.addColorStop(0, "rgba(255,255,255," + _hlAlpha.toFixed(3) + ")");
    _hl.addColorStop(0.55, "rgba(255,255,255," + (_hlAlpha * 0.45).toFixed(3) + ")");
    _hl.addColorStop(1, "rgba(255,255,255,0)");
    ctx.save();
    ctx.globalAlpha = 1;
    ctx.beginPath(); ctx.arc(CX, cy, sr, 0, Math.PI * 2);
    ctx.fillStyle = _hl; ctx.fill();
    ctx.restore();

    // back halves remain visible through the translucent sphere
    const _vis = state.visual || {};
    const _orbits = orbits.filter(o => {
      if (o.key === "echo") return _vis.echo !== false;
      if (o.key === "rippleU" || o.key === "rippleL") return _vis.ripple !== false;
      if (o.key === "noise") return _vis.noise !== false;
      if (o.key === "dominance") return _vis.dominance !== false;
      if (o.key === "social") return _vis.social !== false;
      return true;
    });
    _orbits.forEach(o => ring(o, ry, rx, false, cy));
    _orbits.forEach(o => ring(o, ry, rx, true, cy));

    // noise particles: depth-sorted, back tier dimmer/smaller, hue follows
    // the current emotion palette instead of fixed grey dust.
    if (!state.visual || state.visual.noise !== false) {
      const sat = 24 + 24 * _pA + 10 * _pNovelty;
      _pDraw.forEach((q) => {
        const depthK = clamp(.5 + .5 * (q.z / 1.8));   // 0 back .. 1 front
        const back = q.z < 0;
        const tier = back ? .60 : 1;
        const size = (1.20 + 2.20 * depthK) * (back ? .82 : 1) * (1 + .18 * _pNovelty);
        const twinkle = .86 + .14 * Math.sin(q.i * 1.7 + phase * .9);
        const alpha = clamp((.07 + .20 * _pNovelty + .09 * (1 - _pCoping) + .08 * _pA)
                            * (.42 + .58 * depthK) * tier * twinkle);
        const hue = p.hue + ((q.i % 5) - 2) * 2.2;
        ctx.fillStyle = "hsla(" + hue.toFixed(0) + "," + sat.toFixed(0) + "%," +
          (back ? (isDark() ? 52 : 34) : (isDark() ? 70 : 46)) + "%," + alpha.toFixed(3) + ")";
        ctx.beginPath(); ctx.arc(q.x, q.y, size, 0, Math.PI * 2); ctx.fill();
      });
    }
    ctx.restore();   // end task-43 focus camera: preview label + tooltip are screen space
    // preview mode: app.js falls back to demo events when the page bridge is
    // absent. Label it explicitly so demo balls never masquerade as archive.
    let _previewMode = false;
    try {
      const _linkEl = document.getElementById("linkState");
      _previewMode = !!(_linkEl && /预览|Preview/i.test(String(_linkEl.textContent || "")));
    } catch (err) { _previewMode = false; }
    if (_previewMode) {
      ctx.save();
      ctx.globalAlpha = .85;
      ctx.font = "9px ui-monospace, monospace";
      ctx.fillStyle = isDark() ? "rgba(235,190,110,.95)" : "rgba(170,110,30,.95)";
      ctx.fillText("PREVIEW · 演示事件（非真实档案）", 14, 20);
      ctx.restore();
    }
    // hover tooltip: title / time / importance / meaning, never on the ball
    if (orbTip && (!_mouse.inside || !_memHit.length)) hideOrbTip();
    if (!_previewMode && _mouse.inside && _memHit.length) {
      // task-43: camera-aware picking; while a tap/drag is in progress the
      // tooltip stays out of the way so it never fights the click.
      const hit = _pointerTap.active ? null : _pickMemHit(_mouse.x, _mouse.y);
      canvas.style.cursor = hit ? "pointer" : "";
      if (orbTip) {
        if (hit) updateOrbTip(hit); else hideOrbTip();
      }
      if (hit && !orbTip) {
        const ev = hit.ev || {};
        const title = String(ev.title || ev.event_key || "事件");
        const when = hit.tsS > 0 ? new Date(hit.tsS * 1000).toLocaleString("zh-CN",
          { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
        const impLine = "重要度 " + Number(hit.imp || 0).toFixed(2) +
          " · 年龄 " + Math.round(hit.ageDays) + "d" +
          (ev.peripheral_forgotten ? " · 外围已遗忘" : "") +
          _mergeTip(ev);
        const small = String(ev.small_summary || "").trim();
        const fallbackText = small ? "小总结：" + small
          : String(ev.event || ev.central_details || ev.meaning_to_her || "");
        const lines = [title, when, impLine, fallbackText].filter(Boolean);
        const pad = 10, lineH = 17, boxW = 300;
        const boxH = pad * 2 + lines.length * lineH;
        let tx = _mouse.x + 14, ty = _mouse.y + 14;
        tx = Math.max(8, Math.min(W - boxW - 8, tx));
        ty = Math.max(8, Math.min(H - boxH - 8, ty));
        ctx.save();
        ctx.globalAlpha = .95;
        ctx.fillStyle = isDark() ? "rgba(18,22,26,.95)" : "rgba(251,250,245,.97)";
        ctx.strokeStyle = isDark() ? "rgba(120,128,136,.85)" : "rgba(140,132,118,.85)";
        ctx.lineWidth = 1;
        if (typeof ctx.roundRect === "function") {
          ctx.beginPath(); ctx.roundRect(tx, ty, boxW, boxH, 6); ctx.fill(); ctx.stroke();
        } else {
          ctx.fillRect(tx, ty, boxW, boxH); ctx.strokeRect(tx, ty, boxW, boxH);
        }
        ctx.fillStyle = isDark() ? "rgba(235,230,220,.95)" : "rgba(34,32,28,.93)";
        ctx.font = "12px Bahnschrift, 'Segoe UI', 'Microsoft YaHei', sans-serif";
        ctx.textBaseline = "top";
        for (let k = 0; k < lines.length; k++) {
          let text = lines[k];
          while (text.length > 1 && ctx.measureText(text).width > boxW - pad * 2) text = text.slice(0, -1);
          ctx.fillText(text, tx + pad, ty + pad + k * lineH);
        }
        ctx.restore();
      }
    }
    pushHistory(s);
    if (frameCount % 3 === 0) drawSignal();
  }
  pushHistory(state.snapshot || {}); drawSignal();
  requestAnimationFrame(draw);
})();
