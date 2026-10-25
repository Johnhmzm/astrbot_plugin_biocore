/* Pure orbit math for the dashboard memory-ball / centre-orbit layout.
 *
 * Loaded by orb.js in the browser (window.BioOrbMath) and by
 * scripts/eval_orbit_layout.py through node's require(), so the formulas and
 * the sampled ring geometry are testable without a DOM or canvas.
 *
 * task-42 (kept): 8 centre channels share one distance law, identity offset and
 * volatility-driven speed. task-44 fix: all geometry below is in WORLD units
 * (1 unit = R px) and projectPoint() applies R exactly once, so a channel is a
 * closed 3D ellipse again instead of a huge off-canvas arc / radial line.
 */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.BioOrbMath = api;
})(typeof window !== "undefined" ? window : null, function () {
  "use strict";

  const clamp01 = (value) => {
    const n = Number(value);
    return Number.isFinite(n) ? Math.max(0, Math.min(1, n)) : 0;
  };

  // Centre orbit count: 8 emotional channels and no per-channel radius.
  const ORBIT_COUNT = 8;

  // Channel identity table (colour + plane tilt + fixed speed sign). The
  // distance is NOT stored per channel: every channel uses orbitRadius().
  const ORBIT_CHANNELS = [
    { key: "echo", tilt: .35, speed: .55, color: "255,107,0" },
    { key: "rippleU", tilt: -.36, speed: -.40, color: "48,48,46" },
    { key: "noise", tilt: .82, speed: .62, color: "142,132,120" },
    { key: "rippleL", tilt: -1.18, speed: .90, color: "255,138,40" },
    { key: "spike", tilt: .62, speed: -.28, color: "96,96,96" },
    { key: "trust", tilt: 1.12, speed: 1.10, color: "196,148,82" },
    { key: "dominance", tilt: -.70, speed: .34, color: "96,140,255" },
    { key: "social", tilt: 1.34, speed: -.46, color: "64,196,168" }
  ];

  // Fixed identity offset per channel: +/-0.03R, distributed evenly so
  // channels with equal metric never sit exactly on each other.
  const identityOffset = (index, count) => {
    const n = Math.max(2, Number(count) || ORBIT_COUNT);
    const i = Math.max(0, Math.min(n - 1, Number(index) || 0));
    return (i / (n - 1) - 0.5) * 0.06;   // -0.03 .. +0.03
  };

  // Build the 8 runtime channels (orb.js uses exactly this table).
  const buildOrbits = () => ORBIT_CHANNELS.map((c, i) => ({
    key: c.key, tilt: c.tilt, speed: c.speed, color: c.color, angle: 0,
    ident: identityOffset(i, ORBIT_CHANNELS.length),
    tiltOff: identityOffset(i, ORBIT_CHANNELS.length) * 1.5
  }));

  // Unified distance law in WORLD units. projectPoint() multiplies by R, so
  // the on-screen radius is R * (0.9 + 0.7 * metric) = 0.9R .. 1.6R.
  const orbitRadius = (metric) => 0.9 + 0.7 * clamp01(metric);

  const ORBIT_VOLATILITY_EMA = 0.15;

  // volatility_t = EMA( |metric_t - metric_{t-1}| / dt ). No history (first
  // sample, invalid metric or dt) uses the documented neutral 0.5.
  const orbitVolatility = (prevMetric, metric, dt, prevEma, alpha) => {
    const a = (alpha == null || !Number.isFinite(Number(alpha)))
      ? ORBIT_VOLATILITY_EMA
      : Math.max(0, Math.min(1, Number(alpha)));
    if (prevMetric == null || !Number.isFinite(Number(prevMetric)) ||
        !Number.isFinite(Number(metric))) {
      return 0.5;
    }
    const secs = Number(dt);
    if (!Number.isFinite(secs) || secs <= 0) return 0.5;
    const raw = clamp01(Math.abs(Number(metric) - Number(prevMetric)) / secs);
    const base = (prevEma == null || !Number.isFinite(Number(prevEma)))
      ? 0.5
      : clamp01(prevEma);
    return clamp01(a * raw + (1 - a) * base);
  };

  // speed = base_speed * (0.4 + 1.8 * clamp(volatility)); the sign of
  // base_speed keeps the channel's fixed direction.
  const orbitSpeed = (baseSpeed, volatility) =>
    Number(baseSpeed || 0) * (0.4 + 1.8 * clamp01(volatility));

  // 3D camera projection shared by every orb layer. Input is WORLD units;
  // output is canvas-relative px (caller adds CX/CY). R is applied ONCE.
  const projectPoint = (x, y, z, ry, rx, R) => {
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

  const ORBIT_SAMPLES = 160;   // 161 inclusive points => closed ring

  // Sample one channel ring: 3D circle in its tilted plane, rotated by the
  // channel's own phase angle, then projected. 160 segments. Returns
  // canvas-relative projected points with z kept for front/back sorting.
  const orbitRingPoints = (orbit, metric, angle, ry, rx, R, samples) => {
    const n = Math.max(8, Math.floor(Number(samples) || ORBIT_SAMPLES));
    const rBase = orbitRadius(metric);
    const tilt = Number(orbit && orbit.tilt || 0) + Number(orbit && orbit.tiltOff || 0);
    const idShift = Number(orbit && orbit.ident || 0);   // world units, +-0.03
    const ay = Number(angle) || 0;
    const cA = Math.cos(ay), sA = Math.sin(ay);
    const sT = Math.sin(tilt), cT = Math.cos(tilt);
    const pts = [];
    for (let i = 0; i <= n; i++) {
      const a = i / n * Math.PI * 2;
      const x = Math.cos(a) * rBase + idShift;
      const y = Math.sin(a) * rBase * sT + idShift * .5;
      const z = Math.sin(a) * rBase * cT;
      const x1 = x * cA - z * sA;
      const z1 = x * sA + z * cA;
      pts.push(projectPoint(x1, y, z1, ry, rx, R));
    }
    return pts;
  };

  return { clamp01, ORBIT_COUNT, ORBIT_CHANNELS, ORBIT_SAMPLES,
           orbitRadius, identityOffset, buildOrbits,
           orbitVolatility, orbitSpeed,
           projectPoint, orbitRingPoints };
});
