import { readFileSync } from 'node:fs'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
const here = dirname(fileURLToPath(import.meta.url))
const base = join(here, '..', '..')
const app = readFileSync(join(base, 'pages', 'dashboard', 'app.js'), 'utf8')
const orb = readFileSync(join(base, 'pages', 'dashboard', 'orb.js'), 'utf8')
const html = readFileSync(join(base, 'pages', 'dashboard', 'index.html'), 'utf8')
const markup = html.replace(/<script[\s\S]*?<\/script>/g, '').replace(/<style[\s\S]*?<\/style>/g, '')
const htmlIds = new Set([...markup.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]))
const referenced = new Set()
for (const src of [app, orb]) {
  for (const m of src.matchAll(/\$\((['"])([A-Za-z0-9_]+)\1\)/g)) referenced.add(m[2])
}
const missing = [...referenced].filter((id) => !htmlIds.has(id)).sort()
console.log(JSON.stringify({ referenced: referenced.size, missing }))
