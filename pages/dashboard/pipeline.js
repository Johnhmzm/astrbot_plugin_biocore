/* UI-KIT 用例 · 流水线页（pages/dashboard/pipeline.js）
 * 只读渲染 + 阶段开关 + 试运行。数据走宿主页面桥：
 *   GET  page/pipeline / POST page/pipeline_toggle / POST page/pipeline_dryrun
 * DOM 全部由 ui_kit.js 组件组合（Panel/Row/Switch/Bar/Stat/Badge），页面内不再拼重复结构。
 * 5 秒轮询；只改文本/状态，不重建行，避免闪烁。
 */
(function () {
  'use strict'
  if (window.__biocorePipelineInstalled) return
  window.__biocorePipelineInstalled = true

  var K = window.UIKit
  if (!K) { try { console.error('[pipeline] ui_kit.js 未加载') } catch (e) {} return }

  var API = { status: 'page/pipeline', toggle: 'page/pipeline_toggle', dryrun: 'page/pipeline_dryrun' }
  var POLL_MS = 5000

  var STAGE_META = {
    perceive:    { zh: '感知',   tag: 'L2',  group: 'interaction', io: '读 event/text · 写 meta' },
    memory:      { zh: '取记忆', tag: 'L1',  group: 'memory', io: '读 store · 写 memory' },
    bio:         { zh: '情绪更新', tag: 'L0', group: 'bio', io: '读 snapshot · 写 meta.bio' },
    decide:      { zh: '决定',   tag: 'L4',  group: 'interaction', io: '读 bio/memory · 写 decision' },
    expr_state:  { zh: '状态表达', tag: 'L3', group: 'expression', io: '读 snapshot · 写 expr_state' },
    expr_tone:   { zh: '语气',   tag: 'L3',  group: 'expression', io: '读 decision · 写 tone' },
    expr_intent: { zh: '意图',   tag: 'L3',  group: 'expression', io: '读 snapshot · 写 intent' },
    think:       { zh: '思考',   tag: 'LLM', group: 'interaction', io: '读 prompt · 写 llm_raw' },
    parse:       { zh: '解析',   tag: 'L2',  group: 'interaction', io: '读 llm_raw · 写 parsed' },
    feedback:    { zh: '反馈',   tag: 'FB',  group: 'feedback', io: '读 parsed · 写 deltas（影子不落库）' },
    present:     { zh: '呈现',   tag: 'L4',  group: 'interaction', io: '读 reply · 写 reply' }
  }
  var GROUP_ORDER = ['bio', 'memory', 'interaction', 'expression', 'feedback']
  var MODULE_LABEL = { bio: '生物', memory: '记忆', interaction: '交互', expression: '表达', feedback: '反馈' }
  var STATUS_ZH = { ok: 'ok', skipped: '跳过', failed: '失败', timeout: '超时', idle: '待运行', '': '待运行' }
  var STATUS_TONE = { ok: 'green', skipped: 'muted', failed: 'red', timeout: 'red', idle: '', '': '' }

  var PREVIEW_STAGES = [
    { name: 'perceive', required: true, enabled: true, last_status: 'ok', last_ms: 12.4 },
    { name: 'memory', required: false, enabled: true, last_status: 'ok', last_ms: 3.1 },
    { name: 'bio', required: false, enabled: true, last_status: 'ok', last_ms: 1.8 },
    { name: 'decide', required: true, enabled: true, last_status: 'ok', last_ms: 0.9 },
    { name: 'expr_state', required: false, enabled: true, last_status: 'ok', last_ms: 2.2 },
    { name: 'expr_tone', required: false, enabled: true, last_status: 'ok', last_ms: 1.4 },
    { name: 'expr_intent', required: false, enabled: true, last_status: 'ok', last_ms: 1.1 },
    { name: 'think', required: false, enabled: true, last_status: 'ok', last_ms: 1840.0 },
    { name: 'parse', required: false, enabled: true, last_status: 'ok', last_ms: 9.6 },
    { name: 'feedback', required: false, enabled: false, last_status: 'skipped', last_ms: 0 },
    { name: 'present', required: true, enabled: true, last_status: 'ok', last_ms: 4.3 }
  ]

  var state = { ready: false, preview: false, mode: '', stages: [], trace: {}, signature: '', selected: '', autoPicked: false }
  var inflight = false
  var pending = {}
  var detailNode = null
  var detailRefs = null

  function $(id) { return document.getElementById(id) }
  function nf(value, fallback) { var n = Number(value); return isFinite(n) ? n : fallback }
  function text(node, value) { if (node) node.textContent = String(value) }
  function meta(name) { return STAGE_META[name] || { zh: name, tag: '—', group: '其他', io: '—' } }
  function isPreview() { return state.preview }
  function pageBridge() {
    var bridge = window.AstrBotPluginView || window.AstrBotPluginPage || window.astrbotPluginView || null
    if (!bridge) { try { if (window.parent && window.parent !== window) bridge = window.parent.AstrBotPluginView || window.parent.AstrBotPluginPage || null } catch (e) { bridge = null } }
    return bridge
  }
  function adminToken() { try { return localStorage.getItem('biocore_admin_token') || '' } catch (e) { return '' } }
  function unwrap(raw) {
    if (!raw || typeof raw !== 'object') return {}
    var payload = raw.data && typeof raw.data === 'object' ? raw.data : raw
    if (raw.status === 'error' || payload.ok === false) {
      payload = payload && typeof payload === 'object' ? payload : {}
      if (!payload.ok) payload.ok = false
      if (!payload.message && raw.message) payload.message = raw.message
    }
    return payload || {}
  }
  function setConn(kind, message) {
    text($('pipeConn'), kind === 'ok' ? '已连接' : kind === 'loading' ? '读取中…' : kind === 'preview' ? '预览（未连接后端）' : '读取失败')
    var dot = $('pipeDot')
    if (dot) dot.className = 'dot ' + (kind === 'ok' ? 'is-ok' : kind === 'error' ? 'is-fail' : 'is-idle')
    text($('pipeMode'), 'mode ' + (state.mode || '—'))
    var hint = $('pipeHint')
    if (hint) {
      hint.textContent = kind === 'error' ? ('读取失败：' + String(message || '')) : kind === 'preview'
        ? '预览模式：本机直开没有 AstrBot 页面桥，下面展示结构示例；真实数据需在插件视图内打开。' : ''
    }
  }

  function refresh() {
    if (inflight) return
    if (document.hidden) return
    var view = $('view-pipeline')
    if (state.ready && view && !view.classList.contains('active')) return
    var bridge = pageBridge()
    if (!bridge) {
      state.preview = true
      state.mode = 'shadow (preview)'
      state.stages = PREVIEW_STAGES.slice()
      state.trace = {}
      state.ready = true
      setConn('preview')
      render()
      return
    }
    inflight = true
    setConn(state.ready ? 'ok' : 'loading')
    Promise.resolve(bridge.apiGet(API.status, {})).then(function (raw) {
      var payload = unwrap(raw)
      state.preview = false
      state.mode = String(payload.mode || '')
      state.stages = Array.isArray(payload.stages) ? payload.stages : []
      state.trace = payload.last_trace && typeof payload.last_trace === 'object' ? payload.last_trace : {}
      state.ready = true
      setConn('ok')
      render()
    }).catch(function (error) {
      setConn('error', String((error && error.message) || error))
    }).then(function () { inflight = false })
  }

  function statusZh(status) { return STATUS_ZH[String(status || '')] || String(status || '—') }
  function msText(ms) { var n = nf(ms, 0); return n >= 1000 ? (n / 1000).toFixed(2) + 's' : (n > 0 ? n.toFixed(n < 10 ? 1 : 0) + 'ms' : '—') }
  function signature() { return state.stages.map(function (s) { return String(s.name) + ':' + (s.required ? 1 : 0) + ':' + (s.enabled !== false ? 1 : 0) }).join('|') }
  function traceOf(name) {
    var rows = state.trace && Array.isArray(state.trace.stages) ? state.trace.stages : []
    for (var i = 0; i < rows.length; i += 1) if (rows[i] && rows[i].name === name) return rows[i]
    return null
  }
  function findStage(name) { for (var i = 0; i < state.stages.length; i += 1) if (state.stages[i].name === name) return state.stages[i]; return null }
  function setBadge(node, tone, label) {
    if (!node) return
    node.className = 'kit-badge' + (tone ? ' tone-' + tone : '') + ' pipe-st'
    node.textContent = String(label)
  }

  function render() {
    if (!state.selected && !state.autoPicked && state.stages.length) { state.selected = state.stages[0].name; state.autoPicked = true }
    renderBus()
    renderList()
    renderDetail()
    text($('pipeMode'), 'mode ' + (state.mode || '—'))
    if (isPreview() || !pageBridge()) {
      var switches = document.querySelectorAll('#pipeList .kit-switch input')
      for (var i = 0; i < switches.length; i += 1) switches[i].disabled = true
      var addBtn = $('pipeAddBtn'); if (addBtn) addBtn.disabled = true
      var dryBtn = $('pipeDryBtn'); if (dryBtn) dryBtn.disabled = true
    }
  }

  function busValue(snap, keys) {
    if (!snap || typeof snap !== 'object') return null
    for (var i = 0; i < keys.length; i += 1) {
      var v = snap[keys[i]]
      if (v !== undefined && v !== null && v !== '') return nf(v, null)
    }
    return null
  }
  function fmt(v) { return v === null ? '—' : Number(v).toFixed(2) }
  function renderBus() {
    var host = $('pipeStatusBus')
    if (!host || !K) return
    var snap = (window.__biocoreState && window.__biocoreState.snapshot) || null
    var v = busValue(snap, ['v', 'valence'])
    var threshold = busValue(snap, ['v_threshold', 'threshold'])
    var stress = busValue(snap, ['stress'])
    var lonely = busValue(snap, ['loneliness', 'lonely'])
    var energy = busValue(snap, ['energy'])
    var esteem = busValue(snap, ['self_esteem', 'esteem'])
    var rows = [
      ['V/阈值', fmt(v) + ' / ' + fmt(threshold)], ['效价', fmt(v)], ['压力', fmt(stress)],
      ['寂寞', fmt(lonely)], ['精力', fmt(energy)], ['自尊', fmt(esteem)]
    ]
    host.innerHTML = ''
    rows.forEach(function (row) {
      host.appendChild(K.Stat({ label: row[0], value: row[1], className: 'pipe-bus-item' }))
    })
  }

  var detailHost = null
  function ensureDetail() { if (!detailNode) detailNode = $('pipeDetail'); return detailNode }
  function isWide() { try { return window.matchMedia('(min-width:1100px)').matches } catch (e) { return false } }
  function placeDetail() {
    var host = ensureDetail()
    var section = $('view-pipeline')
    if (!host || !section) return
    if (isWide()) { if (host.parentNode !== section) section.appendChild(host); return }
    var row = state.selected ? document.querySelector('#pipeList [data-row="' + state.selected + '"]') : null
    if (row && row.parentNode) row.insertAdjacentElement('afterend', host)
    else if (host.parentNode !== section) section.appendChild(host)
  }
  function groupedStages() {
    var buckets = {}
    GROUP_ORDER.forEach(function (name) { buckets[name] = [] })
    state.stages.forEach(function (stage, index) {
      var g = meta(stage.name).group
      if (!buckets[g]) buckets[g] = []
      buckets[g].push({ stage: stage, index: index })
    })
    var groups = GROUP_ORDER.slice()
    Object.keys(buckets).forEach(function (name) { if (groups.indexOf(name) < 0) groups.push(name) })
    return groups.filter(function (name) { return buckets[name] && buckets[name].length }).map(function (name) {
      return { group: name, rows: buckets[name] }
    })
  }

  function renderList() {
    var host = $('pipeList')
    if (!host || !K) return
    var sig = signature()
    if (sig !== state.signature) {
      host.innerHTML = ''
      groupedStages().forEach(function (group) {
        var head = document.createElement('div')
        head.className = 'pipe-group'
        head.innerHTML = '<span>' + (MODULE_LABEL[group.group] || group.group) + '</span><em>' + group.rows.length + ' 个环节</em>'
        host.appendChild(head)
        group.rows.forEach(function (item) { host.appendChild(buildRow(item.stage, item.index)) })
      })
      state.signature = sig
      if (state.selected && !findStage(state.selected)) state.selected = ''
    }
    state.stages.forEach(function (stage) {
      var row = host.querySelector('[data-row="' + stage.name + '"]')
      if (!row) return
      text(row.querySelector('.pipe-ms'), msText(stage.last_ms))
      setBadge(row.querySelector('.pipe-st'), STATUS_TONE[String(stage.last_status || '')] || '', statusZh(stage.last_status))
      var sw = row.querySelector('.kit-switch input')
      if (sw && !pending[stage.name]) sw.checked = stage.enabled !== false
      row.classList.toggle('is-off', stage.enabled === false)
      row.classList.toggle('is-selected', state.selected === stage.name)
      var trace = traceOf(stage.name)
      row.title = trace && trace.note ? trace.note : ''
    })
    placeDetail()
  }

  function buildRow(stage, index) {
    var m = meta(stage.name)
    var row = document.createElement('div')
    row.className = 'pipe-row'
    row.setAttribute('data-row', stage.name)
    row.setAttribute('role', 'button')
    row.setAttribute('tabindex', '0')
    row.appendChild(K.el('span', 'pipe-no', String(index + 1).padStart(2, '0')))
    var name = K.el('span', 'pipe-name')
    name.appendChild(K.el('b', null, m.zh))
    name.appendChild(K.el('small', null, stage.name))
    row.appendChild(name)
    row.appendChild(K.el('span', 'pipe-tag', m.tag))
    row.appendChild(K.el('span', 'pipe-ms', '—'))
    row.appendChild(K.Badge({ text: statusZh(stage.last_status), className: 'pipe-st' }))
    row.appendChild(stage.required
      ? K.Badge({ text: '必需', tone: 'accent', className: 'pipe-req' })
      : K.Switch({ checked: stage.enabled !== false, className: 'pipe-sw', inputAttrs: { 'data-stage': stage.name }, onChange: function (checked) { toggleStage(stage.name, checked) } }))
    row.addEventListener('click', function (event) {
      var target = event.target
      if (target && target.tagName && (target.tagName === 'INPUT' || target.closest && target.closest('label'))) return
      selectStage(stage.name)
    })
    row.addEventListener('keydown', function (event) {
      if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectStage(stage.name) }
    })
    return row
  }

  function selectStage(name) {
    state.selected = state.selected === name ? '' : name
    renderList()
    renderDetail()
  }

  function toggleStage(name, enabled) {
    if (isPreview() || !pageBridge()) return
    pending[name] = true
    setHint('')
    var body = { name: name, enabled: !!enabled }
    var token = adminToken()
    if (token) body.admin_token = token
    Promise.resolve(pageBridge().apiPost(API.toggle, body)).then(function (raw) {
      var payload = unwrap(raw)
      if (payload.ok === false) throw new Error(payload.message || '切换失败')
      state.stages = Array.isArray(payload.stages) ? payload.stages : state.stages
      state.signature = ''
      render()
    }).catch(function (error) {
      var stage = findStage(name)
      if (stage) stage.enabled = !enabled
      var input = document.querySelector('#pipeList [data-row="' + name + '"] .kit-switch input')
      if (input) input.checked = !enabled
      setHint('切换失败：' + String((error && error.message) || error))
    }).then(function () { delete pending[name] })
  }
  function setHint(message) {
    var hint = $('pipeHint')
    if (!hint) return
    if (message) { hint.textContent = message; hint.classList.add('is-error') }
    else if (!isPreview()) { hint.textContent = ''; hint.classList.remove('is-error') }
  }

  function renderDetail() {
    var host = ensureDetail()
    if (!host || !K) return
    var stage = state.selected ? findStage(state.selected) : null
    if (!stage) {
      if (isWide()) {
        host.hidden = false
        if (host.dataset.built !== 'empty') {
          host.dataset.built = 'empty'
          host.innerHTML = ''
          host.appendChild(K.Panel({ title: '环节详情', children: [K.el('p', 'pipe-detail-empty', '点击左侧步骤查看详情')] }))
        }
      } else { host.hidden = true }
      return
    }
    host.hidden = false
    var m = meta(stage.name)
    if (host.dataset.built !== stage.name) {
      host.dataset.built = stage.name
      host.innerHTML = ''
      detailRefs = {}
      var rows = []
      function field(key, label, note) {
        var value = K.el('span', 'kit-row-value', '—')
        detailRefs[key] = value
        rows.push(K.Row({ label: label, note: note || '', value: value }))
        return value
      }
      field('name', '模块名')
      field('layer', '所属层')
      field('ms', '上次耗时')
      field('st', '状态')
      if (stage.required) {
        rows.push(K.Row({ label: '启用', value: K.Badge({ text: '必需 · 不可关闭', tone: 'accent' }) }))
      } else {
        var sw = K.Switch({ checked: stage.enabled !== false, inputAttrs: { 'data-detail-stage': stage.name }, onChange: function (checked) { toggleStage(stage.name, checked) } })
        rows.push(K.Row({ label: '启用', value: sw }))
        detailRefs.sw = sw.querySelector('input')
      }
      var note = K.el('p', 'pipe-detail-note', '—')
      detailRefs.note = note
      var panel = K.Panel({
        title: m.zh + ' · ' + stage.name,
        hint: m.group,
        className: 'pipe-detail',
        onClose: function () { state.selected = ''; renderList(); renderDetail() },
        children: rows.concat([note])
      })
      detailRefs.panelTitle = panel.querySelector('.kit-panel-title b')
      detailRefs.panelHint = panel.querySelector('.kit-panel-title small')
      host.appendChild(panel)
    }
    var index = -1
    for (var i = 0; i < state.stages.length; i += 1) if (state.stages[i].name === stage.name) index = i
    var trace = traceOf(stage.name)
    if (detailRefs) {
      text(detailRefs.name, m.zh + '（' + stage.name + '）')
      text(detailRefs.layer, String(m.tag || '') + ' · ' + (MODULE_LABEL[m.group] || m.group))
      text(detailRefs.ms, msText(stage.last_ms))
      text(detailRefs.st, statusZh(stage.last_status))
      if (detailRefs.sw) detailRefs.sw.checked = stage.enabled !== false
      text(detailRefs.note, (stage.required ? '必需环节，不可关闭；' : '') + (trace && trace.note ? trace.note : '影子运行，不写核心。'))
      text(detailRefs.panelTitle, m.zh + ' · ' + stage.name)
      text(detailRefs.panelHint, MODULE_LABEL[m.group] || m.group)
    }
  }

  function dryrun() {
    if (isPreview() || !pageBridge()) return
    var input = $('pipeDryText')
    var value = input && input.value ? String(input.value).trim() : ''
    if (!value) { text($('pipeDryState'), '先输入一句测试文本。'); return }
    var btn = $('pipeDryBtn')
    if (btn) btn.disabled = true
    text($('pipeDryState'), '运行中…')
    var body = { text: value, sample_text: value }
    var token = adminToken()
    if (token) body.admin_token = token
    Promise.resolve(pageBridge().apiPost(API.dryrun, body)).then(function (raw) {
      var payload = unwrap(raw)
      var trace = payload.trace && typeof payload.trace === 'object' ? payload.trace : { stages: [] }
      var rows = Array.isArray(trace.stages) ? trace.stages : []
      renderTrace(rows, payload.out_preview, payload.error)
      text($('pipeDryState'), rows.length ? ('trace ' + rows.length + ' 段 · 影子运行，未发送') : 'trace 为空：阶段可能全部跳过。')
      return refresh()
    }).catch(function (error) {
      text($('pipeDryState'), '试运行失败：' + String((error && error.message) || error))
    }).then(function () { if (btn) btn.disabled = false })
  }
  function renderTrace(rows, preview, error) {
    var host = $('pipeDryTrace')
    if (!host || !K) return
    host.innerHTML = ''
    if (!rows.length) return
    var line = K.el('div', 'pipe-trace-line')
    rows.forEach(function (row) {
      var m = meta(row && row.name)
      line.appendChild(K.Badge({
        text: m.zh + ' ' + Math.round(nf(row && row.ms, 0)) + 'ms ' + statusZh(row && row.status),
        tone: STATUS_TONE[String((row && row.status) || '')] || '',
        className: 'pipe-trace-chip'
      }))
    })
    host.appendChild(line)
    var ok = rows.filter(function (row) { return String(row && row.status) === 'ok' }).length
    host.appendChild(K.Bar({ value: ok, max: rows.length, tone: ok === rows.length ? 'normal' : 'warn', className: 'pipe-trace-bar', label: 'ok ' + ok + ' / ' + rows.length }))
    var out = K.el('div', 'pipe-trace-out')
    out.textContent = '输出预览：' + (preview ? String(preview).slice(0, 200) : '—') + (error ? ' · 错误：' + String(error) : '')
    host.appendChild(out)
  }

  function boot() {
    var list = $('pipeList')
    if (!list) return
    detailNode = $('pipeDetail')
    window.addEventListener('resize', function () { placeDetail(); renderDetail() })
    var addBtn = $('pipeAddBtn')
    if (addBtn) {
      addBtn.disabled = true
      addBtn.addEventListener('click', function () { text($('pipeDryState'), '占位：本期不写入新阶段，请先在 biocore_model/pipeline.py 注册。') })
    }
    var dryBtn = $('pipeDryBtn')
    if (dryBtn) dryBtn.addEventListener('click', dryrun)
    var nav = document.querySelector('.nav-item[data-view="pipeline"]')
    if (nav) nav.addEventListener('click', function () { setTimeout(refresh, 30) })
    try { var qp = new URLSearchParams(location.search); var deep = qp.get('pipe'); if (deep) state.selected = deep } catch (e) {}
    refresh()
    setTimeout(renderBus, 1200)
    setInterval(refresh, POLL_MS)
    window.__biocorePipeline = { state: state, refresh: refresh, dryrun: dryrun, kit: K }
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot)
  else boot()
})()
