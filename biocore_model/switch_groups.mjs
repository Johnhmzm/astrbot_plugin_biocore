/** Pure switch grouping for the dashboard (6 aggregate groups over 31 switches).
 * UI-only: no new config keys, no backend semantics. app.js mirrors this table.
 */
export const SWITCH_GROUPS = {
  memory: {
    label: '记忆', hint: '压缩/总结/洞察/关系印象',
    ids: ['swCompress', 'swHybridRetrieval', 'fn_event_summary_enabled', 'fn_event_ranking_enabled',
          'fn_insight_enabled', 'swInsightAuto', 'fn_memory_summary_enabled', 'fn_image_caption_enabled',
          'fn_relationship_impression_enabled', 'fn_repair_hint_enabled', 'fn_diary_enabled',
          'fn_relationship_narrative_enabled']
  },
  expression: {
    label: '表达', hint: '共情/语用/心智理论/幽默/人格编译',
    ids: ['fn_empathy_hint_enabled', 'fn_pragmatics_hint_enabled',
          'fn_tom_probe_enabled', 'fn_humor_hint_enabled']
  },
  llm: {
    label: 'LLM 路由', hint: 'LLM 候选开关（人格编译已改为动作按钮）',
    ids: ['swLlmCandidates']
  },
  safety: { label: '安全', hint: '敏感信息掩码与投毒过滤', ids: ['swSafetyEnabled'] },
  visual: {
    label: '视觉', hint: '球体/引力/连线/图层',
    ids: ['swMemoryBallGravity', 'swShowNoise', 'swShowLinks', 'swShowMemoryNodes',
          'swMemoryBallsImportant', 'swShowEmotionRings', 'swShowEcho', 'swShowDominance', 'swShowSocial']
  },
  system: { label: '系统', hint: '版本/备份为操作按钮，无个体开关', ids: [] }
}

export const GROUP_ORDER = ['memory', 'expression', 'llm', 'safety', 'visual', 'system']

export function groupIds() { return GROUP_ORDER.slice() }
export function switchIds() { return GROUP_ORDER.flatMap((group) => SWITCH_GROUPS[group].ids) }
export function advancedCount() { return switchIds().length }
export function classifySwitch(id) {
  for (const group of GROUP_ORDER) {
    if (SWITCH_GROUPS[group].ids.includes(id)) return group
  }
  return ''
}
export function hasChildren(group) { return (SWITCH_GROUPS[group] || { ids: [] }).ids.length > 0 }

/** 'on' (all true) | 'off' (all false) | 'mixed' (some true); empty groups -> 'off'. */
export function groupState(group, values = {}) {
  const ids = (SWITCH_GROUPS[group] || { ids: [] }).ids
  if (!ids.length) return 'off'
  const on = ids.filter((id) => values[id] === true).length
  if (on === 0) return 'off'
  if (on === ids.length) return 'on'
  return 'mixed'
}

/** Updates to apply when a group switch is toggled: every child -> value. */
export function expandGroup(group, value) {
  const ids = (SWITCH_GROUPS[group] || { ids: [] }).ids
  const target = value === true
  const updates = {}
  for (const id of ids) updates[id] = target
  return updates
}

/** Group row text: label + hint + child count. */
export function groupRowText(group) {
  const meta = SWITCH_GROUPS[group] || { label: group, hint: '', ids: [] }
  return meta.label + (meta.ids.length ? '（' + meta.ids.length + ' 项）' : '') + ' · ' + meta.hint
}

/** Two-tier settings view: simple = groups + core card; advanced = groups + all switches + diagnostics. */
export const VIEW_MODES = ['simple', 'advanced']
export const VIEW_STORAGE_KEY = 'biocore_settings_view'

export function normalizeViewMode(value) {
  return VIEW_MODES.includes(String(value || '').toLowerCase()) ? String(value).toLowerCase() : 'simple'
}

/** Tabs: every switch belongs to exactly one settings tab; the four core/llm tabs
 * carry status / mode buttons / switches, not group toggles for core status/mode. */
export const TAB_GROUPS = {
  api: [],
  coreStatus: [],
  safety: ['safety'],
  llm: ['llm'],
  memory: ['memory'],
  expression: ['expression'],
  visual: ['visual'],
  version: [],
  backup: [],
  persona: []
}
export const TAB_ORDER = ['api', 'coreStatus', 'safety', 'llm', 'expression', 'memory', 'visual', 'version', 'backup', 'persona']

export function tabOfSwitch(id) {
  for (const tab of TAB_ORDER) {
    for (const group of TAB_GROUPS[tab]) {
      if (SWITCH_GROUPS[group].ids.includes(id)) return tab
    }
  }
  return ''
}

/** Required content units per tab (acceptance: the four new tabs are non-empty). */
export const TAB_CONTENT = {
  api: ['apiGrid'],
  coreStatus: ['statusCard', 'storePath', 'bridgeDiag', 'indexCounts', 'modeButtons', 'inlineConfirm', 'inlineToast', 'riskNote'],
  safety: ['safetySwitch', 'gatingNote'],
  llm: ['llmCandidateSwitch', 'routeSelects', 'budget'],
  memory: ['memorySwitches'],
  expression: ['expressionSwitches'],
  visual: ['visualSwitches'],
  version: ['versionPanel'],
  backup: ['backupPanel'],
  persona: ['personaCompileBtn', 'personaCompileConfirmRow']
}
export function tabContentCount(tab) { return (TAB_CONTENT[tab] || []).length }

/** Interactive element counts per view mode (pure acceptance helper). */
export function visibleInteractive(mode) {
  const view = normalizeViewMode(mode)
  const groupSwitches = GROUP_ORDER.length
  const viewButtons = 2
  const modeButtons = 3
  const individual = view === 'advanced' ? advancedCount() : 0
  return { mode: view, groups: groupSwitches, viewButtons, modeButtons, individual, total: groupSwitches + viewButtons + modeButtons + individual }
}

/** Visible element counts for a mode (pure; DOM-free acceptance helper). */
export function visibleElements(mode) {
  const view = normalizeViewMode(mode)
  const groups = GROUP_ORDER.length
  const switches = advancedCount()
  const coreCard = 1
  const diagnostics = view === 'advanced' ? 1 : 0
  return {
    mode: view,
    groups,
    switches: view === 'advanced' ? switches : 0,
    coreCard,
    diagnostics,
    total: groups + coreCard + (view === 'advanced' ? switches + 1 : 1)  // + diagnostics or + view toggle
  }
}

/** Merged visual switches write BOTH legacy local keys (compatibility). */
export const VISUAL_MERGED_KEYS = {
  swShowMemoryNodes: ['bio_show_memory_nodes', 'bio_show_nodes'],
  swShowLinks: ['bio_show_links', 'bio_show_node_links'],
  swShowEcho: ['bio_show_echo', 'bio_show_ripple']
}
export function visualWrites(id, value) {
  const out = {}
  for (const key of VISUAL_MERGED_KEYS[id] || []) out[key] = value === true ? '1' : '0'
  return out
}
export function visualReads(id, stored = {}) {
  const keys = VISUAL_MERGED_KEYS[id] || []
  if (!keys.length) return undefined
  return keys.some((key) => (stored[key] === undefined ? true : stored[key] !== '0'))
}

/** Function-domain switches (simple view): each writes back several legacy keys. */
export const FEATURE_SWITCHES = {
  feat_memory_compress: { label: '记忆压缩', llm: false, ids: ['swCompress'] },
  feat_memory_retrieval: { label: '混合检索', llm: false, ids: ['swHybridRetrieval'] },
  feat_memory_insight: { label: '事件与洞察', llm: false, ids: ['fn_event_summary_enabled','fn_event_ranking_enabled','fn_insight_enabled','swInsightAuto','fn_memory_summary_enabled'] },
  feat_memory_relation: { label: '关系与日记', llm: false, ids: ['fn_relationship_impression_enabled','fn_repair_hint_enabled','fn_diary_enabled','fn_relationship_narrative_enabled'] },
  feat_expression_rules: { label: '情绪表达调节', llm: false, local: true, defaultOn: true, ids: ['fn_empathy_hint_enabled'] },
  feat_visual_nodes: { label: '节点显示', llm: false, ids: ['swShowMemoryNodes'] },
  feat_visual_links: { label: '连线显示', llm: false, ids: ['swShowLinks'] },
  feat_visual_rings: { label: '光环强度', llm: false, ids: ['swShowEcho','swShowDominance','swShowSocial'] },
  feat_safety: { label: '敏感掩码与投毒过滤', llm: false, ids: ['swSafetyEnabled'] },
  feat_llm_image: { label: '图片描述', llm: true, ids: ['fn_image_caption_enabled'] },
  feat_archive_batch: { label: '归档批量', llm: true, local: true, defaultOn: true, ids: [] }
}
export const FEATURE_ORDER = ['feat_memory_compress','feat_memory_retrieval','feat_memory_insight','feat_memory_relation','feat_expression_rules','feat_visual_nodes','feat_visual_links','feat_visual_rings','feat_safety','feat_llm_image','feat_archive_batch']
export const LLM_SIMPLE_CONTROLS = ['feat_llm_image','feat_archive_batch']

export function featureIds() { return FEATURE_ORDER.slice() }
export function featureAbsorbed(id) { return (FEATURE_SWITCHES[id] || { ids: [] }).ids.slice() }
export function featureAbsorbedAll() { return FEATURE_ORDER.flatMap((id) => featureAbsorbed(id)) }
export function featureState(id, values = {}) {
  const ids = featureAbsorbed(id)
  if (!ids.length) return 'off'
  const on = ids.filter((key) => values[key] === true).length
  return on === 0 ? 'off' : (on === ids.length ? 'on' : 'mixed')
}
export function featureWrites(id, value) {
  const target = value === true
  const updates = {}
  for (const key of featureAbsorbed(id)) updates[key] = target
  return updates
}
export function featureLabel(id) {
  const meta = FEATURE_SWITCHES[id] || { label: id, llm: false }
  const tag = meta.llm ? '[LLM] ' : (meta.local ? '[本地] ' : '')
  return tag + meta.label
}

/** Empathy is rendered by the interpretation layer (affect -> text), never an LLM call. */
export function compatEmpathy(oldValue) {
  return { localOn: oldValue === true, llmContentEnhance: oldValue === true, llmCallsByDefault: 0 }
}
