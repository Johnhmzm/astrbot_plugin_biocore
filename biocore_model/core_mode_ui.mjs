/** Pure core-mode button state (mirror in pages/dashboard/app.js). */
export const CORE_MODES = ['off', 'shadow', 'primary']

/** Human-readable error for a failed apiPost: always includes HTTP status + message. */
export function describeBridgeError(error) {
  const err = error && typeof error === 'object' ? error : {}
  const status = err.status || err.statusCode || err.httpStatus || (err.response && err.response.status) || ''
  const code = err.code || (err.payload && err.payload.code) || ''
  const message = err.message || (err.payload && err.payload.message) || (typeof error === 'string' ? error : '') || '未知错误'
  const head = status ? ('HTTP ' + status + (code ? ' ' + String(code) : '')) : (code ? String(code) : '')
  return head ? (head + '：' + message) : String(message)
}

export function coreModeButtons(mode) {
  const value = String(mode || 'off').toLowerCase()
  return {
    shadow: { disabled: value === 'shadow' },
    primary: { disabled: value === 'primary' },
    rollback: { disabled: value === 'off' }
  }
}

/** Chinese labels for the three modes (buttons/confirm/toast are all Chinese). */
export const CORE_MODE_LABELS = { off: '旧版', shadow: '影子模式', primary: '核心模式' }

/** Inline confirmation text (no window.confirm: iframes may block modals). */
export function coreModeConfirmText(mode) {
  const value = String(mode || 'off').toLowerCase()
  if (value === 'primary') return '确认切到核心模式？（核心为主，失败自动回退旧引擎）'
  if (value === 'shadow') return '确认切到影子模式？'
  return '确认回退到旧版引擎？'
}

/** Success toast text. */
export function coreModeSuccessText(mode, pendingRestart = false) {
  const value = String(mode || 'off').toLowerCase()
  const base = value === 'off' ? '已回退旧版引擎' : '已切到' + CORE_MODE_LABELS[value]
  return base + (pendingRestart ? '（重启后生效）' : '')
}

/** Bridge diagnostics label. */
export function coreBridgeLabel(connected) {
  return connected === true ? '桥接：已连接' : '桥接：未连接（静态预览）'
}

/** Inline toast text for a failure (always carries HTTP status/code when present). */
export function coreModeToastText(error, action = '切换') {
  return action + '失败：' + describeBridgeError(error)
}

/**
 * Pure inline-confirm state machine over a DOM stub.
 * stub: { setConfirm(text|null), setToast(text|null), setError(text|null) }
 * deps: { post(mode) -> Promise<{ok,mode,pending_restart}>, bridgeAvailable:()=>bool }
 */
export function createCoreModeFlow({ post, view }) {
  let pending = null
  let calls = 0
  const api = {
    click(mode) {
      const state = view.buttons()
      if (state[String(mode)] && state[String(mode)].disabled) {
        return { showConfirm: false, disabled: true }
      }
      pending = String(mode)
      view.setConfirm(coreModeConfirmText(pending))
      return { showConfirm: true, prompt: coreModeConfirmText(pending) }
    },
    cancel() {
      pending = null
      view.setConfirm(null)
      return { cancelled: true }
    },
    async confirm() {
      if (!pending) return { called: false }
      const mode = pending
      pending = null
      view.setConfirm(null)
      if (view.bridgeAvailable() !== true) {
        view.setToast(coreBridgeLabel(false) + '，无法切换')
        return { called: false, reason: 'no_bridge' }
      }
      calls += 1
      try {
        const payload = await post(mode)
        if (!payload || payload.ok === false) {
          const message = payload && payload.message
          view.setError(String(message || '服务端拒绝'))
          view.setToast(coreModeToastText(payload || '服务端拒绝'))
          return { called: true, ok: false }
        }
        view.setToast(coreModeSuccessText(mode, payload.pending_restart === true))
        return { called: true, ok: true, payload }
      } catch (error) {
        view.setError(describeBridgeError(error))
        view.setToast(coreModeToastText(error))
        return { called: true, ok: false, error }
      }
    },
    get calls() { return calls },
    get pending() { return pending }
  }
  return api
}
