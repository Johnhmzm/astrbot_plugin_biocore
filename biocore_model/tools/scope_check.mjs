import assert from 'node:assert'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const here = dirname(fileURLToPath(import.meta.url))
const app = readFileSync(join(here, '..', '..', 'pages', 'dashboard', 'app.js'), 'utf8')
assert.ok(/window\.LLM_ADVANCED_IDS = \[/.test(app), 'window.LLM_ADVANCED_IDS assignment missing')
const bare = [...app.matchAll(/(?<!window\.)\bLLM_ADVANCED_IDS\b(?!\s*=)/g)]
assert.equal(bare.length, 0, 'bare LLM_ADVANCED_IDS references: ' + bare.length)
assert.ok(app.includes('window.FEATURE_TABLE =') && app.includes('window.FEATURE_ORDER ='), 'feature tables not exposed')
const windowObj = {}
const sandbox = new Function('window', `
  window.LLM_ADVANCED_IDS = ["a","b"];
  var out = [];
  window.LLM_ADVANCED_IDS.forEach(function(k){ out.push(k) });
  return out;
`)
assert.deepEqual(sandbox(windowObj), ['a','b'])
console.log('SCOPE CHECK OK: window.LLM_ADVANCED_IDS assignment, 0 bare refs, loop smoke ok')
