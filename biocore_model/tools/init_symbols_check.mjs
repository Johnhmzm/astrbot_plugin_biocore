import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const here = dirname(fileURLToPath(import.meta.url))
const app = readFileSync(join(here, '..', '..', 'pages', 'dashboard', 'app.js'), 'utf8')
const calls = [...app.matchAll(/_initStep\(\s*['"]([^'"]+)['"]\s*,\s*([A-Za-z_$][\w$]*)\s*\)/g)].map((m) => ({ step: m[1], fn: m[2] }))
assert.ok(calls.length >= 6, 'expected several _initStep calls, got ' + calls.length)
const missing = calls.filter(({ fn }) => !new RegExp('function\\s+' + fn + '\\s*\\(').test(app) && !new RegExp('(?:const|let|var)\\s+' + fn + '\\s*=').test(app))
assert.deepEqual(missing, [], 'undefined init functions: ' + JSON.stringify(missing))
console.log('INIT SYMBOLS OK: ' + calls.length + ' steps, all defined')
