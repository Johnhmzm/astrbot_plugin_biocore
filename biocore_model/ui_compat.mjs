/** UI compatibility: localStorage schema migration + merged switch mapping. */
export const UI_SCHEMA = 2
export const UI_SCHEMA_KEY = 'biocore_ui_schema'
export const OLD_SWITCH_MAP = {
  swShowNodes: 'feat_visual_nodes',
  swShowMemoryNodes: 'feat_visual_nodes',
  swShowLinks: 'feat_visual_links',
  swShowNodeLinks: 'feat_visual_links',
  swShowEmotionRings: 'feat_visual_rings',
  swShowRipple: 'feat_visual_rings',
  fn_empathy_hint_enabled: 'feat_expression_rules',
  fn_pragmatics_hint_enabled: 'feat_expression_rules',
  fn_tom_probe_enabled: 'feat_expression_rules',
  fn_humor_hint_enabled: 'feat_expression_rules',
  swCompress: 'feat_memory_compress',
  swHybridRetrieval: 'feat_memory_retrieval',
  swSafetyEnabled: 'feat_safety'
}
export const OLD_STORAGE_KEYS = {
  'biocore_settings_tab': 'biocore_settings_tab',
  'biocore_settings_view': 'biocore_settings_view',
  'biocore_orb_quality': 'biocore_orb_quality'
}
export function migrateStorage(read, write, schemaKey = UI_SCHEMA_KEY) {
  const changes = []
  const schema = Number(read(schemaKey) || 0)
  if (schema >= UI_SCHEMA) return { migrated: false, schema, changes }
  for (const [oldKey, newKey] of Object.entries(OLD_STORAGE_KEYS)) {
    const value = read(oldKey)
    if (value != null && value !== '' && (read(newKey) == null || read(newKey) === '')) {
      write(newKey, value); changes.push(oldKey + '->' + newKey)
    }
  }
  for (const oldId of Object.keys(OLD_SWITCH_MAP)) {
    if (read('bio_feat_' + oldId) === '1' && read('bio_feat_' + OLD_SWITCH_MAP[oldId]) !== '1') {
      write('bio_feat_' + OLD_SWITCH_MAP[oldId], '1'); changes.push('bio_feat_' + oldId + '->' + OLD_SWITCH_MAP[oldId])
    }
  }
  write(schemaKey, String(UI_SCHEMA))
  return { migrated: true, schema: UI_SCHEMA, changes }
}
export function resolvePersonaId(personas, personaId, filename) {
  const list = Array.isArray(personas) ? personas.filter((p) => p && p.id) : []
  if (personaId && list.some((p) => String(p.id) === String(personaId))) return String(personaId)
  const firstReal = list.find((p) => String(p.id) !== 'default')
  if (firstReal) return String(firstReal.id)
  return filename ? String(filename) : ''
}
