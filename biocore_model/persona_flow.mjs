/** Persona selection + compile flow (pure state machine, testable). */
export function buildOptions(personas) {
  const list = Array.isArray(personas) ? personas.filter((p) => p && p.id) : []
  return list.map((p) => ({ id: String(p.id), label: p.name && String(p.name) !== String(p.id) ? p.name + '（' + p.id + '）' : String(p.name || p.id) }))
}
export function initialTarget(personas, personaId) {
  const list = Array.isArray(personas) ? personas.filter((p) => p && p.id) : []
  if (personaId && list.some((p) => String(p.id) === String(personaId))) return String(personaId)
  const fallback = list.find((p) => String(p.id) === 'default') || list[0]
  return fallback ? String(fallback.id) : ''
}
export function compileStep(state, event) {
  const current = ['idle', 'confirm', 'running', 'done'].includes(state) ? state : 'idle'
  if (event === 'click' && current === 'idle') return 'confirm'
  if (event === 'confirm' && current === 'confirm') return 'running'
  if (event === 'result' && current === 'running') return 'done'
  return current
}
export function createSaveOnce(post, state = { saved: 0 }) {
  return async function save(payload) {
    if (state.saved > 0 && state.last === JSON.stringify(payload)) return null
    state.saved += 1; state.last = JSON.stringify(payload)
    return post(payload)
  }
}
