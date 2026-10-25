/* Pure orbit math for the dashboard memory-ball / centre-orbit layout.
 *
 * Loaded by orb.js in the browser (window.BioOrbMath) and by
 * scripts/eval_orbit_layout.py through node's require(), so the formulas are
 * testable without a DOM or canvas.
 *
 * task-42:
 * - 8 centre orbits share ONE distance law: rBase = R * (0.9 + 0.7 * metric);
 * - channel identity = colour + a small fixed +/-0.03R angle/tilt offset;
 * - orbit speed follows the EMA of the metric change rate and keeps the
 *   channel's fixed direction sign.
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

  // Centre orbit count: 8 emotional channels (echo/rippleU/noise/rippleL/
  // spike/trust/dominance/social) and no per-channel radius.
  const ORBIT_COUNT = 8;

  // Unified distance law. metric is the channel value in [0, 1].
  const orbitRadius = (metric, R) => Number(R) * (0.9 + 0.7 * clamp01(metric));

  // Fixed identity offset per channel: +/-0.03R in orbit units, distributed
  // evenly so channels with equal metric never sit exactly on each other.
  const identityOffset = (index, count) => {
    const n = Math.max(2, Number(count) || ORBIT_COUNT);
    const i = Math.max(0, Math.min(n - 1, Number(index) || 0));
    return (i / (n - 1) - 0.5) * 0.06;   // -0.03 .. +0.03
  };

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

  return { clamp01, ORBIT_COUNT, ORBIT_VOLATILITY_EMA,
           orbitRadius, identityOffset, orbitVolatility, orbitSpeed };
});
