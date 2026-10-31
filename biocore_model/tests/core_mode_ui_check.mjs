import assert from 'node:assert'
import { CORE_MODES, coreModeButtons, describeBridgeError, coreModeConfirmText, coreModeSuccessText, coreBridgeLabel, createCoreModeFlow } from '../core_mode_ui.mjs'
assert.deepEqual(CORE_MODES, ['off', 'shadow', 'primary'])
assert.deepEqual(coreModeButtons('off'), { shadow: { disabled: false }, primary: { disabled: false }, rollback: { disabled: true } })
assert.deepEqual(coreModeButtons('shadow'), { shadow: { disabled: true }, primary: { disabled: false }, rollback: { disabled: false } })
assert.deepEqual(coreModeButtons('primary'), { shadow: { disabled: false }, primary: { disabled: true }, rollback: { disabled: false } })
assert.equal(coreModeButtons('bogus').rollback.disabled, false)  // unknown mode -> all switches enabled
assert.equal(coreModeButtons(undefined).shadow.disabled, false)
assert.equal(coreModeButtons('primary').rollback.disabled, false)
assert.equal(describeBridgeError({ status: 403, message: 'forbidden' }), 'HTTP 403：forbidden')
assert.equal(describeBridgeError({ statusCode: 400, code: 'invalid_params', message: 'invalid mode' }), 'HTTP 400 invalid_params：invalid mode')
assert.equal(describeBridgeError(new Error('boom')), 'boom')
assert.equal(describeBridgeError({ payload: { code: 'integrity_refused', message: 'refused' } }), 'integrity_refused：refused')
assert.equal(coreModeConfirmText('shadow'), '确认切到影子模式？')
assert.equal(coreModeConfirmText('off'), '确认回退到旧版引擎？')
assert.ok(coreModeConfirmText('primary').includes('核心为主'))
assert.equal(coreModeSuccessText('shadow'), '已切到影子模式')
assert.equal(coreModeSuccessText('off'), '已回退旧版引擎')
assert.equal(coreModeSuccessText('primary', true), '已切到核心模式（重启后生效）')
assert.equal(coreBridgeLabel(true), '桥接：已连接')
assert.equal(coreBridgeLabel(false), '桥接：未连接（静态预览）')
// DOM stub: inline confirm flow (no window.confirm anywhere)
function makeView({ bridge = true, post = async () => ({ ok: true, mode: 'shadow' }) } = {}) {
  const state = { confirm: null, toast: null, error: null, posts: 0 }
  return {
    state,
    setConfirm(value) { state.confirm = value },
    setToast(value) { state.toast = value },
    setError(value) { state.error = value },
    bridgeAvailable() { return bridge },
    buttons() { return { shadow: { disabled: false }, primary: { disabled: false }, off: { disabled: true } } },
    post(mode) { state.posts += 1; return post(mode) }
  }
}
const view = makeView()
const flow = createCoreModeFlow({ post: (mode) => view.post(mode), view })
const clicked = flow.click('shadow')
assert.equal(clicked.showConfirm, true)
assert.equal(view.state.confirm, '确认切到影子模式？')
assert.equal(flow.click('off').disabled, true)  // off button disabled -> no confirm
flow.cancel()
assert.equal(view.state.confirm, null)
assert.equal(flow.calls, 0)
flow.click('shadow')
const okRun = await flow.confirm()
assert.equal(okRun.called, true)
assert.equal(flow.calls, 1)
assert.equal(view.state.posts, 1)
assert.equal(view.state.toast, '已切到影子模式')
const errView = makeView({ post: async () => { const e = new Error('forbidden'); e.status = 403; throw e } })
const errFlow = createCoreModeFlow({ post: (mode) => errView.post(mode), view: errView })
errFlow.click('primary')
await errFlow.confirm()
assert.ok(errView.state.toast.includes('HTTP 403'), errView.state.toast)
assert.ok(errView.state.error.includes('403'))
const offView = makeView({ bridge: false })
const offFlow = createCoreModeFlow({ post: (mode) => offView.post(mode), view: offView })
offFlow.click('shadow')
const offRun = await offFlow.confirm()
assert.equal(offRun.called, false)
assert.ok(offView.state.toast.includes('未连接'), offView.state.toast)
assert.equal(offView.state.posts, 0)
console.log('CORE MODE UI OK (23 checks)')
