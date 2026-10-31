import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
const here = dirname(fileURLToPath(import.meta.url))
const app = readFileSync(join(here, '..', '..', 'pages', 'dashboard', 'app.js'), 'utf8')
let body = app.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/[^\n]*/g, '')
body = body.replace(/'(?:\\.|[^'\\])*'/g, "''").replace(/"(?:\\.|[^"\\])*"/g, '""').replace(/`(?:\\.|[^`\\])*`/g, '``')
body = body.replace(/\/(?:\\.|\[(?:\\.|[^\]\\])*\]|[^\/\\\n])+\/[gimsuy]*/g, 'RE')
const declared = new Set()
for (const m of body.matchAll(/\b(?:const|let|var|function|class)\s+([A-Z][A-Z0-9_]{2,}|[A-Za-z_$][\w$]*)\s*(?:\(|:|=)/g)) declared.add(m[1])
for (const m of body.matchAll(/\b([A-Za-z_$][\w$]*)\s*=(?![=>])/g)) declared.add(m[1])
for (const m of body.matchAll(/\bfunction\s+([A-Za-z_$][\w$]*)/g)) declared.add(m[1])
for (const m of body.matchAll(/\b(?:const|let|var)\s*\{([^}]*)\}/g)) for (const part of m[1].split(',')) { const name = part.split(':').pop().trim(); if (name) declared.add(name) }
for (const m of body.matchAll(/\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)/g)) declared.add(m[1])
for (const m of body.matchAll(/\b([A-Z][A-Z0-9_]{2,})\s*:/g)) declared.add(m[1])
for (const m of body.matchAll(/\.\s*([A-Z][A-Z0-9_]{2,})\b/g)) declared.add(m[1])
const builtins = new Set(['JSON','Math','Date','Object','Array','String','Number','Boolean','Promise','Set','Map','Error','TypeError','Infinity','NaN','URLSearchParams','Intl','RegExp','TextDecoder','TextEncoder','console','window','document','localStorage','fetch','requestAnimationFrame','setTimeout','clearTimeout','setInterval','clearInterval','CustomEvent','Event','MutationObserver','Image','Audio','Blob','FileReader','Uint8Array','Float32Array','AbortController','HTMLElement','HTMLCanvasElement','Node','Element','RE'])
const used = new Set([...body.matchAll(/\b([A-Z][A-Z0-9_]{2,})\b/g)].map((m) => m[1]))
const allow = new Set(['API','ASTRBOT','COLD','CORE','FIELD','GITEE_KEY','HOLD','HOT','LLM','NOMINAL','OFFLINE','TTL','WARM'])
const undefinedCaps = [...used].filter((id) => !declared.has(id) && !builtins.has(id) && !allow.has(id)).sort()
console.log(JSON.stringify({ declared: declared.size, undefined: undefinedCaps }))
if (undefinedCaps.length) { console.error('UNDEFINED CAPS: ' + undefinedCaps.join(',')); process.exit(1) }
console.log('no undefined caps ids')
