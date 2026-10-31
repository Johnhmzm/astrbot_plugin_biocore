/** Tab persistence helpers (pure; local-storage key contract for the dashboard). */
export const TAB_STORAGE_KEYS = {
  settings: 'biocore_settings_tab',
  persona: 'biocore_persona_tab',
  session: 'biocore_session_tab',
  intent: 'biocore_intent_tab'
}

export function tabStorageKey(kind) {
  return TAB_STORAGE_KEYS[kind] || ''
}

export function resolveTab(stored, validTabs, fallback) {
  const valid = Array.isArray(validTabs) ? validTabs : []
  return valid.includes(stored) ? stored : fallback
}

export function defaultTab(validTabs, fallback) {
  return resolveTab('', Array.isArray(validTabs) ? validTabs : [], fallback)
}

/** In-memory value wins over storage; storage failure never forces the default. */
export function resolveActiveTab({ mem = null, stored = '', valid = [], fallback = null } = {}) {
  const list = Array.isArray(valid) ? valid : []
  if (mem && list.includes(mem)) return mem
  if (stored && list.includes(stored)) return stored
  return fallback
}

export function safeRead(storage, key) {
  try { return (storage && storage.getItem && storage.getItem(key)) || '' } catch (e) { return '' }
}

export function safeWrite(storage, key, value) {
  try { if (storage && storage.setItem) { storage.setItem(key, value); return true } } catch (e) { return false }
  return false
}
