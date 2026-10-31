#!/usr/bin/env node
/** Fake-bridge assertion for the dashboard 核心服务 card (no browser).
 * Extracts the marked pure mapping function from app.js and checks off/shadow/primary copy.
 */
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('../../pages/dashboard/app.js', import.meta.url), 'utf8')
const start = source.indexOf('// [CORE-STATUS-MAP]')
const end = source.indexOf('// [/CORE-STATUS-MAP]')
if (start < 0 || end < 0) { console.log('core status FAILED: markers missing'); process.exit(1) }
const block = source.slice(start, end)
const factory = new Function(block + '\nreturn coreStatusView')
const coreStatusView = factory()

const cases = [
  { name: 'off', core: { enabled: false, mode: 'off', circuit_open: false, fail_count: 0, store: '/x' }, expect: ['核心服务：未启用（off）', 'off'] },
  { name: 'primary', core: { enabled: true, mode: 'primary', circuit_open: false, fail_count: 2, store: '/store' }, expect: ['核心服务：primary', '记忆写入走核心', '正常', '2', '/store'] },
  { name: 'shadow', core: { enabled: true, mode: 'shadow', circuit_open: true, fail_count: 1, store: '/s' }, expect: ['核心服务：shadow', '只读影子', '熔断中'] }
]
let ok = true
for (const item of cases) {
  const view = coreStatusView(item.core)
  const flat = JSON.stringify(view)
  const missing = item.expect.filter((needle) => !flat.includes(needle))
  console.log(item.name + ': ' + flat)
  if (missing.length) { console.log('  MISSING ' + JSON.stringify(missing)); ok = false }
}
console.log(ok ? 'core status OK' : 'core status FAILED')
process.exitCode = ok ? 0 : 1
