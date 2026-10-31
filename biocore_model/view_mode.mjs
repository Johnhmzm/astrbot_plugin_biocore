/** Settings view mode: memory-first, storage best-effort. */
export function normalizeView(value) {
  return String(value || '').toLowerCase() === 'advanced' ? 'advanced' : 'simple'
}
export function resolveView(mem, stored) {
  if (mem === 'simple' || mem === 'advanced') return mem
  return normalizeView(stored)
}
