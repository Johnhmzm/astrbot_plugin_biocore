import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setCheckedSafe, setTextSafe, setValSafe } from '../render_guard.mjs'
const here = dirname(fileURLToPath(import.meta.url))
const base = join(here, '..', '..')
const app = readFileSync(join(base, 'pages', 'dashboard', 'app.js'), 'utf8')
const html = readFileSync(join(base, 'pages', 'dashboard', 'index.html'), 'utf8')
const markup = html.replace(/<script[\s\S]*?<\/script>/g, '').replace(/<style[\s\S]*?<\/style>/g, '')
const htmlIds = new Set([...markup.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]))
const referenced = new Set([...app.matchAll(/\$\((['"])([A-Za-z0-9_]+)\1\)/g)].map((m) => m[2]))
const dynamic = new Set(['apiSaveState','btnAdvancedView','btnSimpleView','iAttention','iExpected','iMeta','iOpponent','iUrgency','llmRouteNoteRow','settingsBackup','settingsVersion','settingsViewToggle','swLlmOnlyReplySummary'])
const missing = [...referenced].filter((id) => !htmlIds.has(id) && !dynamic.has(id))
// element-missing stub: these must never throw
for (const fn of [setCheckedSafe, setTextSafe, setValSafe]) { assert.doesNotThrow(() => fn(null, true)); assert.doesNotThrow(() => fn(undefined, 'x')) }
assert.doesNotThrow(() => setCheckedSafe({}, true))
assert.doesNotThrow(() => setTextSafe({}, 3))
assert.equal(missing.join(','), '')  // all missing references are dynamic/legacy handled
assert.ok(app.includes('function setChecked(') && app.includes('function setText(') && app.includes('function setVal('))
assert.ok(!/\$\((['"])[^'"]+\1\)\.checked\s*=/.test(app), 'unsafe checked assignment left')
console.log('DOM SAFE OK (12 checks)')
