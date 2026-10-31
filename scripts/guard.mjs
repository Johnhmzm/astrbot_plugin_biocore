#!/usr/bin/env node
/** Build guard: fails the build when the dashboard structure/contract is broken. */
import { readFileSync, writeFileSync } from 'node:fs'
import { createHash } from 'node:crypto'
import { execFileSync } from 'node:child_process'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const base = join(root, 'pages', 'dashboard')
const read = (name) => readFileSync(join(base, name), 'utf8')
const errors = []
const fail = (message) => errors.push(message)

const tpl = read('index.src.html')
const app = read('app.js')
const orb = read('orb.js')
const markup = tpl.replace(/<script[\s\S]*?<\/script>/g, '').replace(/<style[\s\S]*?<\/style>/g, '')

// 1) panels inside the settings section
const settingsStart = tpl.indexOf('id="view-settings"')
const settingsOpen = tpl.lastIndexOf('<section', settingsStart)
let depth = 0, i = settingsOpen, settingsEnd = -1
while (i < tpl.length) {
  const open = tpl.indexOf('<section', i), close = tpl.indexOf('</section>', i)
  if (close < 0) break
  if (open >= 0 && open < close) { depth += 1; i = open + 8 } else { depth -= 1; i = close + 10; if (depth === 0) { settingsEnd = close; break } }
}
for (const m of markup.matchAll(/<div[^>]*class="[^"]*settings-panel[^"]*"[^>]*id="([^"]+)"/g)) {
  const at = tpl.indexOf('id="' + m[1] + '"')
  if (settingsEnd < 0 || at < settingsOpen || at > settingsEnd) fail('panel outside #view-settings: ' + m[1])
}
// 2) tabs <-> panels
const tabIds = [...markup.matchAll(/data-settings-target="([^"]+)"/g)].map((m) => m[1]).filter((id) => /^settings[A-Z]/.test(id))
const panelIds = [...markup.matchAll(/class="[^"]*settings-panel[^"]*"[^>]*id="([^"]+)"/g)].map((m) => m[1])
for (const id of tabIds) if (!panelIds.includes(id)) fail('tab without panel: ' + id)
for (const id of panelIds) if (!tabIds.includes(id)) fail('panel without tab: ' + id)
if (tabIds.length !== panelIds.length) fail('tabs=' + tabIds.length + ' panels=' + panelIds.length)
// 3) document skeleton
if ((tpl.match(/<!DOCTYPE/gi) || []).length !== 1) fail('DOCTYPE count wrong')
if ((tpl.match(/<\/body>/gi) || []).length !== 1) fail('</body> count wrong')
if ((tpl.match(/<\/html>/gi) || []).length !== 1) fail('</html> count wrong')
if (tpl.length - tpl.toLowerCase().lastIndexOf('</html>') > 200) fail('</html> not near EOF')
// 4) unique ids
const ids = [...markup.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1])
const dupes = [...new Set(ids.filter((id, k) => ids.indexOf(id) !== k))]
if (dupes.length) fail('duplicate ids: ' + dupes.join(','))
// 5) init symbols + window assignments
for (const m of app.matchAll(/_initStep\(\s*['"]([^'"]+)['"]\s*,\s*([A-Za-z_$][\w$]*)\s*\)/g)) {
  if (!new RegExp('function\\s+' + m[2] + '\\s*\\(').test(app) && !new RegExp('(?:const|let|var)\\s+' + m[2] + '\\s*=').test(app)) fail('undefined init fn: ' + m[2])
}
for (const m of app.matchAll(/\bwindow\.([A-Z][A-Z0-9_]{2,})\s*=\s*\[/g)) {
  const name = m[1]
  const bare = new RegExp('(?<!window\\.)\\b' + name + '\\b(?!\\s*=)')
  if (bare.test(app)) fail('bare reference to window.' + name)
}
// 6) dangerous assignments
for (const m of app.matchAll(/\$\((['"])([^'"]+)\1\)\.(checked|value|textContent)\s*=/g)) {
  const at = m.index || 0
  const prefix = app.slice(Math.max(0, at - 160), at)
  const guarded = prefix.includes('if ($("' + m[2] + '"))') || prefix.includes('if($("' + m[2] + '"))')
  if (!guarded) fail('direct DOM assignment ($(...).' + m[3] + '=), use setChecked/setText/setVal')
}
// 7) inline idempotency (runs the real build twice)
const target = join(base, 'index.html')
const before = readFileSync(target, 'utf8')
const hash = () => createHash('sha1').update(readFileSync(target)).digest('hex')
try {
  execFileSync(process.execPath, [join(root, 'scripts', 'inline-assets.mjs')], { stdio: 'ignore' })
  const h1 = hash()
  execFileSync(process.execPath, [join(root, 'scripts', 'inline-assets.mjs')], { stdio: 'ignore' })
  const h2 = hash()
  if (h1 !== h2) fail('inline build is not idempotent')
} catch (error) { fail('inline build failed: ' + error.message) } finally { writeFileSync(target, before, 'utf8') }

if (errors.length) {
  console.error('GUARD FAILED:')
  for (const message of errors) console.error(' - ' + message)
  process.exit(1)
}
console.log('GUARD OK: panels in section, tabs=' + tabIds.length + ' panels=' + panelIds.length + ', ids unique, init symbols ok, no dangerous assignments, inline idempotent')
