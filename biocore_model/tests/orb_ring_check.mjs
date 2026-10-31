import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
const here = dirname(fileURLToPath(import.meta.url))
const orb = readFileSync(join(here, '..', '..', 'pages', 'dashboard', 'orb.js'), 'utf8')
const html = readFileSync(join(here, '..', '..', 'pages', 'dashboard', 'index.html'), 'utf8')
// ring(): width/alpha come from that ring's own dimension value (mv), not a global _mi
const ringBody = orb.slice(orb.indexOf('const mv = orbitMetric'), orb.indexOf('const mv = orbitMetric') + 800)
assert.ok(!/_mi/.test(ringBody), 'ring() must not use global _mi')
assert.ok(/baseAlpha = 0\.18 \+ 0\.70 \* mv/.test(orb), 'per-ring alpha mapping missing')
assert.ok(/baseWidth = 0\.35 \+ 1\.45 \* mv/.test(orb), 'per-ring width mapping missing')
// monotonic in mv
const alpha = (mv) => 0.18 + 0.70 * mv
const width = (mv) => 0.35 + 1.45 * mv
assert.ok(alpha(0) < alpha(0.5) && alpha(0.5) < alpha(1))
assert.ok(width(0) < width(0.5) && width(0.5) < width(1))
assert.ok(/每个情绪色环的粗细\/亮度 = 该维度的当前强度/.test(html), 'missing per-dimension copy')
assert.ok(/emotionRings === true/.test(orb), 'outer rings default off')
console.log('ORB RING OK (7 checks)')
