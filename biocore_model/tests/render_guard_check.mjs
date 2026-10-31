import assert from 'node:assert'
import { safeRender, personaView } from '../render_guard.mjs'

const empty = personaView({})
assert.equal(empty.name, '当前人设：—')
assert.equal(empty.traits, 'O — · C — · E — · A — · N —')
assert.equal(empty.summary, '—')
assert.ok(empty.version.includes('未编译'))
assert.equal(personaView(null).name, '当前人设：—')  // no payload -> no throw
assert.equal(personaView({ persona_profile: { name: 'A' } }).name, '当前人设：A')
const full = personaView({ persona_profile: { big5: { O: 0.82, C: 0.38, E: 0.93, A: 0.7, N: 0.52 } }, config: { persona_name: 'X' }, persona_text: 'hello world' })
assert.ok(full.traits.includes('O 0.82'))
// safeRender isolation: a throwing render must not stop the next one
const order = []
safeRender('bad', () => { order.push('bad'); throw new Error('boom') }, () => {})
safeRender('good', () => { order.push('good') }, () => {})
assert.deepEqual(order, ['bad', 'good'])
assert.equal(safeRender('bad2', () => { throw new Error('x') }, () => {}), null)
console.log('RENDER GUARD OK (11 checks)')
