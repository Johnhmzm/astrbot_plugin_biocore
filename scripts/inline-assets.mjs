#!/usr/bin/env node
/** Idempotent build: always start from index.src.html, inline js/css, write index.html. */
import { readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const dir = dirname(fileURLToPath(import.meta.url))
const base = join(dir, '..', 'pages', 'dashboard')
const read = (name) => readFileSync(join(base, name), 'utf8')
let html = readFileSync(join(base, 'index.src.html'), 'utf8')
for (const name of ['orb_math.js', 'orb.js', 'app.js', 'ui_kit.js', 'registry.js', 'pipeline.js', 'now.js', 'relationship.js', 'records.js', 'debug.js', 'settings_ui.js', 'nav_boot.js']) {
  const pattern = new RegExp('<script[^>]*src="(?:\.\/)?' + name.replace(/[.]/g, '\\.') + '[^"]*"[^>]*><\\/script>')
  html = html.replace(pattern, '<script>\n' + read(name) + '\n</script>')
}
html = html.replace(/<link[^>]*href="(?:\.\/)?styles\.css[^"]*"[^>]*>/, '<style>\n' + read('styles.css') + '\n</style>')
writeFileSync(join(base, 'index.html'), html, 'utf8')
console.log('INLINE OK: size=' + html.length)
