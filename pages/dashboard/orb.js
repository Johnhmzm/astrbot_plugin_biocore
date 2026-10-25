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
  const isDark = () => document.documentElement.dataset.theme === "dark";
  window.addEventListener("biocore:state", (e) => { if (e.detail) state = Object.assign({}, state, e.detail); });

  const orbits = [
    { key: "echo", angle: 0, rx: 1.24, tilt: .35, speed: .55, phase: 0.0, color: "255,107,0", width: 1.15 },
    { key: "rippleU", angle: 0, rx: 1.42, tilt: -.36, speed: -.40, phase: 1.4, color: "48,48,46", width: .95 },
    { key: "noise", angle: 0, rx: 1.58, tilt: .82, speed: .62, phase: 3.0, color: "142,132,120", width: .65 },
    { key: "rippleL", angle: 0, rx: 1.32, tilt: -1.18, speed: .90, phase: 4.5, color: "255,138,40", width: .70 },
    { key: "spike", angle: 0, rx: 1.72, tilt: .62, speed: -.28, phase: 5.2, color: "96,96,96", width: .55 },
    { key: "trust", angle: 0, rx: 1.12, tilt: 1.12, speed: 1.10, phase: 2.0, color: "196,148,82", width: .60 },
    { key: "dominance", angle: 0, rx: 1.86, tilt: -.70, speed: .34, phase: 2.8, color: "96,140,255", width: .55 },
    { key: "social", angle: 0, rx: 1.98, tilt: 1.34, speed: -.46, phase: 4.1, color: "64,196,168", width: .50 }
  ];
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
  const _tipEsc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function hideOrbTip() {
    if (!orbTip) return;
    orbTip.classList.remove("show");
    orbTip.hidden = true;
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
      ((Number(ev.merge_count) || 0) > 0 ? " · 合并 " + Number(ev.merge_count) : "");
    const _secKey = String(ev.emotion_secondary || "").trim();
    const _status = String((ev.source_check && ev.source_check.status) || "ok");
    const _emoLine = "情绪：" + _emotionZh(ev.emotion) +
      (_secKey ? " / " + _emotionZh(_secKey) : " / 同主色") +
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

  const _EMO_ZH = {
    admiration:"钦佩", adoration:"爱慕", aesthetic:"审美欣赏", amusement:"好笑", anger:"生气",
    anxiety:"焦虑", awe:"敬畏", awkwardness:"尴尬", boredom:"无聊", calmness:"平静",
    confusion:"困惑", contempt:"轻蔑", contentment:"满足", desire:"欲望", disappointment:"失望",
    disgust:"厌恶", empathic_pain:"共情痛苦", entrancement:"入迷", envy:"嫉妒", excitement:"兴奋",
    fear:"害怕", guilt:"内疚", horror:"恐惧", interest:"兴趣", joy:"快乐",
    loneliness:"孤独", nostalgia:"怀念", pride:"自豪", neutral:"平静", trust:"信任"
  };
  const _SECONDARY_FAMILY = {
    admiration:"joy", adoration:"joy", aesthetic:"joy", amusement:"joy", awe:"joy",
    contentment:"joy", desire:"joy", excitement:"joy", interest:"joy", joy:"joy", pride:"joy",
    nostalgia:"sadness", sadness:"sadness", disappointment:"sadness", empathic_pain:"sadness", guilt:"sadness",
    anger:"anger", contempt:"anger", disgust:"anger", envy:"anger",
    fear:"fear", anxiety:"fear", horror:"fear",
    loneliness:"loneliness", boredom:"neutral", confusion:"neutral", calmness:"trust"
  };
  function _emotionZh(key){
    const k=String(key||"");
    return _EMO_ZH[k] || k || "未知";
  }

  function palette() {
    const it = state.intent || {}, s = state.snapshot || {};
    const e = String(it.emotion || "neutral");
    let hue = { joy: 42, trust: 168, sadness: 214, fear: 260, anger: 12, surprise: 286, loneliness: 232, neutral: 196 }[e] || 196;
    hue = hue + (12 - hue) * clamp(s.stress) * .22;
    return { hue, sat: 26 + clamp(s.energy) * 18, stress: clamp(s.stress) };
  }
  function project(x, y, z, ry, rx) {
    const cy = Math.cos(ry), sy = Math.sin(ry), cx = Math.cos(rx), sx = Math.sin(rx);
    let x1 = x * cy - z * sy;
    let z1 = x * sy + z * cy;
    let y1 = y * cx - z1 * sx;
    z1 = y * sx + z1 * cx;
    const p = 1 + z1 * .16;
    return { x: CX + x1 * R * p, y: CY + y1 * R * p, z: z1 };
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
    const pts = [];
    const mv = orbitMetric(orbit, state.snapshot || {});
    const rBase = orbit.rx * (0.78 + mv * 0.55);
    const dy = (typeof centerY === "number" ? centerY : CY) - CY;
    for (let i = 0; i <= 160; i++) {
      const a = i / 160 * Math.PI * 2;
      let x = Math.cos(a) * rBase;
      let y = Math.sin(a) * rBase * Math.sin(orbit.tilt);
      let z = Math.sin(a) * rBase * Math.cos(orbit.tilt);
      const ay = orbit.angle;
      const x1 = x * Math.cos(ay) - z * Math.sin(ay);
      const z1 = x * Math.sin(ay) + z * Math.cos(ay);
      const q = project(x1, y, z1, ry, rx);
      q.y += dy;
      pts.push(q);
    }
    ctx.beginPath();
    for (let i = 0; i < pts.length - 1; i++) {
      const a = pts[i], b = pts[i + 1];
      if ((a.z >= 0) !== front) continue;
      ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y);
    }
    let _c = orbit.color;
    if (isDark()) {
      if (/36,36,36|96,96,96/.test(_c)) _c = "228,224,214";
      else if (/142,132,120|196,148,82/.test(_c)) _c = "188,168,138";
    }
    // front = visible half; back half is dimmed for depth but keeps the ring
    // hue instead of fading into a grey smear on the light background.
    ctx.strokeStyle = "rgba(" + _c + "," + (front ? .82 : .55) + ")";
    ctx.lineWidth = front ? orbit.width : orbit.width * .85;
    ctx.stroke();
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
    if (window.__biocoreState) state = window.__biocoreState;
    const p = palette(), s = state.snapshot || {};
    const energy = clamp(s.energy), stress = p.stress, arousal = clamp(s.a);
    phase += .0025 + energy * .004 + arousal * .003;
    const breathe = 1 + Math.sin(phase * 1.5) * .018;
    const bob = Math.sin(phase * 1.15) * 5;
    const ry = phase * .42, rx = -.12 + Math.sin(phase * .3) * .08;
    ctx.clearRect(0, 0, W, H);
    _memHit.length = 0;
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
    orbits.forEach(o => {
      const mv = orbitMetric(o, s);
      o.angle += o.speed * (0.35 + mv * 1.9) * 0.045;
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
        { k: "neutral",    x: .05, y: .05, z: .50, c: "124,154,146" }
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
      const _ec = { joy: "242,193,78", sadness: "91,141,239", anger: "229,83,61", fear: "139,92,246", loneliness: "79,93,170", neutral: "124,154,146", trust: "84,181,139" };
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
        const merge = Math.max(0, Number(ev.merge_count || 0));
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
        return { ev, imp, cent, recall, merge, tsS, ageDays, ageNorm, mass,
                 x: q.x, y: q.y + (cy - CY), z: q.z,
                 front: q.z >= 0, size: 0 };
      });
      _balls.sort((p, q) => p.z - q.z);   // back to front
      _balls.forEach((b) => {
        const ev = b.ev;
        let col = _ec[String(ev.emotion || "neutral")] || _ec.neutral;
        if (ev._kind === "memory" && !ev.emotion_known) col = "142,148,158";
        const bodyHsl = _vividHsl(col, b.imp);   // saturated, slightly deep
        const primaryRingHsl = { h: bodyHsl.h, s: bodyHsl.s, l: Math.min(60, bodyHsl.l + 7) };
        const _secKey = String(ev.emotion_secondary || "").trim();
        const _secRgb = _secKey ? (_ec[_SECONDARY_FAMILY[_secKey] || _secKey] || "") : "";
        const _secHsl = _secRgb ? _vividHsl(_secRgb, b.imp) : null;
        const ringHsl = _secHsl
          ? { h: _secHsl.h, s: _secHsl.s, l: Math.min(60, _secHsl.l + 7) }
          : primaryRingHsl;   // old data/no secondary: primary lightened one step
        const bodyFill = "hsl(" + bodyHsl.h.toFixed(0) + "," + bodyHsl.s.toFixed(0) + "%," + bodyHsl.l.toFixed(0) + "%)";
        const ringFill = "hsl(" + ringHsl.h.toFixed(0) + "," + ringHsl.s.toFixed(0) + "%," + ringHsl.l.toFixed(0) + "%)";
        const front = b.front ? 1 : .72;
        const ageAlpha = .16 + .70 * (1 - b.ageNorm);
        const forgotten = ev.peripheral_forgotten === true;
        const status = String((ev.source_check && ev.source_check.status) || "ok").toLowerCase();
        const recallN = Math.min(1, b.recall / 5);
        const sinceRecall = Math.max(0, _nowS - Number(ev.last_recall || b.tsS));
        const recallFresh = Math.exp(-sinceRecall / 86400);
        const haloPulse = .85 + .15 * Math.sin(phase * (.55 + .45 * recallN) + b.ageDays);
        // Ball size is dominated by memory/event importance (not recall count).
        const size = (1.6 + 8.0 * Math.pow(b.imp, 0.75) + 0.6 * Math.min(1, b.recall / 5)) * front;
        b.size = size;
        const fillAlpha = (.14 + .52 * b.imp) * ageAlpha * (.55 + .45 * b.cent) * front;
        const haloAlpha = (.06 + .12 * recallN + .05 * recallFresh) * ageAlpha *
          haloPulse * (forgotten ? .35 : 1);
        const suspect = status === "suspect";
        // [BC] memory ball: size=importance, orbit=time; only one secondary ring.
        ctx.save();
        // halo: brightness + pulse rate follow recall_count / last_recall
        ctx.globalAlpha = haloAlpha;
        ctx.beginPath(); ctx.arc(b.x, b.y, size * (2.1 + .35 * recallN), 0, Math.PI * 2);
        ctx.strokeStyle = "hsla(" + primaryRingHsl.h.toFixed(0) + "," + primaryRingHsl.s.toFixed(0) + "%," + primaryRingHsl.l.toFixed(0) + "%,.42)";
        ctx.lineWidth = .7; ctx.stroke();
        // body: centrality controls solidity; forgotten becomes a hollow ring
        const bodyAlpha = Math.min(1, (.58 + .40 * b.imp) * (.86 + .14 * (1 - b.ageNorm)) * front);
        if (forgotten) {
          ctx.globalAlpha = Math.max(.18, bodyAlpha * .50);
          ctx.beginPath(); ctx.arc(b.x, b.y, size, 0, Math.PI * 2);
          ctx.strokeStyle = bodyFill; ctx.lineWidth = 1; ctx.stroke();
        } else {
          ctx.globalAlpha = bodyAlpha;
          ctx.beginPath(); ctx.arc(b.x, b.y, size, 0, Math.PI * 2);
          ctx.fillStyle = bodyFill; ctx.fill();
        }
        // one importance ring: secondary emotion colour. The secondary ring is
        // a dashed arc slowly rotating around the ball centre (task-41); old
        // data without emotion_secondary keeps a static primary lightened ring.
        // The central mood ball is drawn separately, so it never spins here.
        const ringBase = size + 4.2;
        const ringAlpha = Math.max(0, (.28 + .40 * b.imp)) * front;
        ctx.save();
        ctx.globalAlpha = ringAlpha;
        if (_secHsl) {
          const spin = phase * 1.15;              // slow: about one turn per 15s
          ctx.setLineDash([3.2, 4.8]);
          ctx.lineDashOffset = -phase * 6.0;
          ctx.beginPath();
          ctx.arc(b.x, b.y, ringBase, spin, spin + Math.PI * 1.86);
          ctx.strokeStyle = ringFill;
          ctx.lineWidth = .7 + .35 * b.imp;
          ctx.stroke();
          ctx.setLineDash([]);
        } else {
          ctx.beginPath(); ctx.arc(b.x, b.y, ringBase, 0, Math.PI * 2);
          ctx.strokeStyle = "hsla(" + primaryRingHsl.h.toFixed(0) + "," +
            primaryRingHsl.s.toFixed(0) + "%," +
            Math.min(72, primaryRingHsl.l + 12).toFixed(0) + "%,.55)";
          ctx.lineWidth = .7 + .25 * b.imp;
          ctx.stroke();
        }
        ctx.restore();
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
        ctx.restore();
        _memHit.push({ x: b.x, y: b.y, r: ringBase + (suspect ? 5 : 2), ev, imp: b.imp,
                       tsS: b.tsS, ageDays: b.ageDays, front: b.front });
      });
    }

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
    const _ma = Number(s.a == null ? 0.4 : s.a);
    const _ms = Number(s.stress || 0);
    // a = baseline activation, |v| = emotional charge, stress = extra tint.
    // Keep a visible color at ordinary arousal; only very calm states go white.
    const _mi = clamp(0.55 * _ma + 0.35 * _mv + 0.10 * _ms);
    const _mSat = 16 + 72 * _mi;
    const _mLight = 91 - 34 * _mi;
    const moodColor = "hsl(" + _moodHue + " " + _mSat.toFixed(1) + "% " + _mLight.toFixed(1) + "%)";
    // The core is always glassy: even the strongest emotion stays translucent.
    ctx.save();
    ctx.globalAlpha = Math.min(0.78, Math.max(0.30, 0.30 + 0.42 * _mi));
    ctx.beginPath(); ctx.arc(CX, cy, sr, 0, Math.PI * 2);
    ctx.fillStyle = moodColor; ctx.fill();
    ctx.strokeStyle = "rgba(20,20,20,.28)"; ctx.lineWidth = 1; ctx.stroke();
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
      let hit = null, best = Infinity;
      for (let k = 0; k < _memHit.length; k++) {
        const hb = _memHit[k];
        const dist = Math.hypot(hb.x - _mouse.x, hb.y - _mouse.y);
        const reach = Math.max(18, hb.r + 10);   // generous hover target, scales with ball/rings
        if (dist <= reach && dist < best) { hit = hb; best = dist; }
      }
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
          ((Number(ev.merge_count) || 0) > 0 ? " · 合并 " + Number(ev.merge_count) : "");
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
