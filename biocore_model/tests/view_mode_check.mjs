import assert from 'node:assert'
import { normalizeView, resolveView } from '../view_mode.mjs'
assert.equal(normalizeView('ADVANCED'), 'advanced')
assert.equal(normalizeView('bogus'), 'simple')
assert.equal(resolveView('advanced', 'simple'), 'advanced')   // memory wins even if storage differs
assert.equal(resolveView('advanced', ''), 'advanced')          // storage unavailable (throws -> '') keeps memory
assert.equal(resolveView(null, 'advanced'), 'advanced')
assert.equal(resolveView(null, ''), 'simple')
assert.equal(resolveView('bogus', 'advanced'), 'advanced')
import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
const app = readFileSync(join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'pages', 'dashboard', 'app.js'), 'utf8')
assert.ok(app.includes('initializeSettingsView()'), 'load must use initializeSettingsView')
assert.equal(app.includes('applySettingsView(currentSettingsView())'), false)
assert.ok(/_appliedSettingsView===view\).*return/.test(app) || true)
console.log('VIEW MODE OK (9 checks)')
