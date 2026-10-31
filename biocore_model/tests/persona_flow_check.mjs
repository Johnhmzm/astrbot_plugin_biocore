import assert from 'node:assert'
import { buildOptions, initialTarget, compileStep, createSaveOnce } from '../persona_flow.mjs'
assert.deepEqual(buildOptions([{id:'default',name:'默认'},{id:'x',name:'X'}]), [{id:'default',label:'默认（default）'},{id:'x',label:'X（x）'}])
assert.equal(initialTarget([{id:'default'},{id:'x'}], 'x'), 'x')
assert.equal(initialTarget([{id:'default'},{id:'x'}], ''), 'default')
assert.equal(initialTarget([], ''), '')
// compile flow: click -> confirm -> running -> done (no extra step)
let s = 'idle'
assert.equal(compileStep(s,'click'), 'confirm')
s = 'confirm'; assert.equal(compileStep(s,'confirm'), 'running')
s = 'running'; assert.equal(compileStep(s,'result'), 'done')
assert.equal(compileStep('idle','confirm'), 'idle')  // no accidental compile without click
const calls = []
const save = createSaveOnce(async (p) => { calls.push(p); return { ok: true } })
await save({ persona_id: 'x' }); await save({ persona_id: 'x' })
assert.equal(calls.length, 1)  // change -> exactly one save
console.log('PERSONA FLOW OK (9 checks)')
