/** Render guards: one failing panel must never break the whole dashboard. */
export function safeRender(name, fn, warn = console.warn) {
  try { return fn() } catch (error) {
    try { warn('[biocore] render failed:', name, error) } catch (e) {}
    return null
  }
}

export function personaView(data) {
  const d = data && typeof data === 'object' ? data : {}
  const profile = d.persona_profile && typeof d.persona_profile === 'object' ? d.persona_profile : {}
  const cfg = d.config && typeof d.config === 'object' ? d.config : {}
  const big5 = profile.big5 && typeof profile.big5 === 'object' ? profile.big5 : (profile || {})
  const pick = (...values) => values.find((v) => typeof v === 'string' && v.trim()) || ''
  const name = pick(d.persona_name, profile.name, cfg.persona_name, d.persona_id) || '—'
  const traits = ['O', 'C', 'E', 'A', 'N'].map((k) => {
    const key = Object.keys(big5).find((key) => String(key).toLowerCase().startsWith(k.toLowerCase()))
    const value = key != null ? Number(big5[key]) : NaN
    return k + ' ' + (Number.isFinite(value) ? value.toFixed(2) : '—')
  }).join(' · ')
  const compiled = String(pick(d.persona_compiled_hash, d.persona_version)) || ''
  const text = String(pick(d.persona_text, d.persona) || '')
  return {
    name: '当前人设：' + name,
    source: name === '—' ? 'AstrBot 当前人设' : 'AstrBot 当前人设（' + name + '）',
    version: compiled ? ('已编译 v' + compiled.slice(0, 8)) : '未编译（点右侧按钮）',
    traits,
    summary: text ? (text.slice(0, 60) + (text.length > 60 ? '…' : '')) : '—'
  }
}

export function setCheckedSafe(el, val) { if (el) el.checked = !!val }
export function setTextSafe(el, val) { if (el) el.textContent = String(val) }
export function setValSafe(el, val) { if (el) el.value = String(val) }
