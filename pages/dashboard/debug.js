/* UI-KIT 页面 · 调试（pages/dashboard/debug.js）
 * 数据：GET page/debug（宿主页面桥）→ loop / bio / autonomy / paths / blocks / pipeline / policy
 * 结构：顶部一行大号等宽指标 → 3 张卡（循环 / 生物 / 自主）→ 1 个折叠「原始 JSON」（paths / blocks / policy / last_trace）
 * 轮询：5 秒；首次建骨架，之后只改文本/隐藏态/条宽，不重建 DOM。
 * 组件：Panel / Row / Bar / Badge / Empty（ui_kit.js）。
 */
(function () {
  'use strict'
  if (window.__ui3DebugInstalled) return
  window.__ui3DebugInstalled = true

  var K = window.UIKit
  if (!K) { try { console.error('[debug] ui_kit.js 未加载') } catch (e) {} return }

  var API = { status: 'page/debug' }
  var POLL_MS = 5000
  var NEED_ORDER = ['belonging', 'self_esteem', 'control', 'meaningful_existence']
  var NEED_ZH = { belonging: '归属', self_esteem: '自尊', control: '控制', meaningful_existence: '意义' }
  var EMO_ZH = {
    neutral: '平静', joy: '开心', sadness: '难过', fear: '害怕', anger: '生气',
    surprise: '惊讶', trust: '信任', loneliness: '孤独', lonely: '孤独',
    anticipation: '期待', disgust: '厌恶', shyness: '害羞',
    nostalgia: '怀旧', relaxed: '放松', gratitude: '感激', pride: '骄傲', envy: '羡慕'
  }
  var MIXED_CONFIDENCE = 0.35

  var state = { data: null, preview: false, ready: false, error: '' }
  var refs = null
  var inflight = false

  function $(id) { return document.getElementById(id) }
  function text(node, value) { if (node) node.textContent = value == null ? '' : String(value) }
  function show(node, on) { if (node) node.hidden = !on }
  function num(v) { var n = Number(v); return (v === null || v === undefined || v === '') ? null : (isFinite(n) ? n : null) }
  function f2(v) { var n = num(v); return n == null ? null : n.toFixed(2) }
  function obj(v) { return (v && typeof v === 'object' && !Array.isArray(v)) ? v : null }
  function pageBridge() {
    var b = window.AstrBotPluginView || window.AstrBotPluginPage || window.astrbotPluginView || null
    if (!b) { try { if (window.parent && window.parent !== window) b = window.parent.AstrBotPluginView || window.parent.AstrBotPluginPage || null } catch (e) { b = null } }
    return b
  }
  function unwrap(raw) {
    if (!raw || typeof raw !== 'object') return {}
    var payload = raw.data && typeof raw.data === 'object' ? raw.data : raw
    return payload || {}
  }
  function when(ts) {
    var n = num(ts)
    if (n == null || n <= 0) return null
    try { return new Date(n * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' }) } catch (e) { return null }
  }
  function ago(ts) {
    var n = num(ts)
    if (n == null || n <= 0) return null
    var diff = Math.max(0, Date.now() / 1000 - n)
    if (diff < 60) return Math.round(diff) + ' 秒前'
    if (diff < 3600) return Math.round(diff / 60) + ' 分钟前'
    return (diff / 3600).toFixed(1) + ' 小时前'
  }
  function jsonText(v) {
    if (v == null) return null
    if (typeof v === 'string') return v
    try { return JSON.stringify(v, null, 2) } catch (e) { return String(v) }
  }

  function map(d) {
    var loop = obj(d.loop)
    var bio = obj(d.bio)
    var auto = obj(d.autonomy)
    var paths = obj(d.paths)
    var blocks = obj(d.blocks)
    var pipe = obj(d.pipeline)
    var policy = obj(d.policy)
    var pending = bio && obj(bio.pending_intent)
    var pendingAction = pending && pending.action ? String(pending.action)
      : (bio && typeof bio.pending_intent === 'string' ? bio.pending_intent : null)
    var intero = bio && obj(bio.intero)
    var needsRaw = bio && obj(bio.needs)
    var needsRows = []
    if (needsRaw) {
      NEED_ORDER.forEach(function (key) {
        var n = num(needsRaw[key])
        if (n == null) return
        needsRows.push({ key: key, label: NEED_ZH[key] || key, value: Math.max(0, Math.min(1, n)) })
      })
    }
    var edRaw = bio && obj(bio.emotion_dist)
    var emotion = null
    if (edRaw && edRaw.label) {
      var top = Array.isArray(edRaw.top) ? edRaw.top : []
      emotion = {
        label: EMO_ZH[String(edRaw.label)] || String(edRaw.label),
        confidence: num(edRaw.confidence),
        top: top.slice(0, 3).map(function (row) {
          var k = row && row.label != null ? String(row.label) : ''
          return { label: EMO_ZH[k] || k, prob: num(row && row.prob) }
        }).filter(function (row) { return row.label })
      }
    }
    var interoRows = []
    if (intero) {
      Object.keys(intero).forEach(function (k) {
        var n = num(intero[k])
        if (n == null) return
        interoRows.push({ label: String(k), value: n })
      })
      interoRows = interoRows.slice(0, 4)
    }
    return {
      preview: state.preview,
      count: loop && num(loop.count) != null ? num(loop.count) : null,
      interval: loop && num(loop.interval_s) != null ? num(loop.interval_s) : null,
      lastTick: loop ? when(loop.last_tick_ts) : null,
      lastTickAgo: loop ? ago(loop.last_tick_ts) : null,
      discomfort: bio && num(bio.discomfort) != null ? num(bio.discomfort) : null,
      needs: needsRows,
      emotion: emotion,
      intero: interoRows,
      pendingAction: pendingAction,
      V: auto && num(auto.V) != null ? num(auto.V) : null,
      theta: auto && num(auto.theta) != null ? num(auto.theta) : null,
      ticks: auto && num(auto.ticks_since_fire) != null ? num(auto.ticks_since_fire) : null,
      mode: pipe && pipe.mode ? String(pipe.mode) : null,
      lastTrace: pipe ? pipe.last_trace : null,
      paths: paths, blocks: blocks, policy: policy
    }
  }

  function rowSlot(host) {
    var row = K.Row({ label: '', value: K.el('span', 'kit-row-value', '') })
    host.appendChild(row)
    return { row: row, label: row.querySelector('.kit-row-main b'), value: row.querySelector('.kit-row-value') }
  }
  function statCell(host) {
    var cell = K.el('div', 'kit-stat')
    cell.appendChild(K.el('small', 'kit-stat-label', ''))
    var value = K.el('span', 'kit-stat-value', '')
    cell.appendChild(value)
    host.appendChild(cell)
    return { cell: cell, label: cell.querySelector('.kit-stat-label'), value: value }
  }
  function topSlot(host, label) {
    var cell = K.el('span')
    cell.appendChild(K.el('small', null, label))
    var value = K.el('b', null, '')
    cell.appendChild(value)
    host.appendChild(cell)
    return value
  }
  function pad(list, size, make) { while (list.length < size) list.push(make()); return list }

  function build(root) {
    root.textContent = ''
    var r = { loopRows: [], autoRows: [], intero: [], needs: [], emo: [], json: {} }
    r.error = K.el('p', 'notice')
    r.error.hidden = true
    root.appendChild(r.error)

    var top = K.el('div', 'dbg-top')
    r.top = {
      count: topSlot(top, 'loop.count'),
      discomfort: topSlot(top, 'discomfort'),
      mode: topSlot(top, 'pipeline.mode'),
      pending: topSlot(top, 'pending_intent')
    }
    root.appendChild(top)

    var cards = K.el('div', 'kit-cards')
    // 卡 1：循环
    var h1 = K.el('div')
    r.loopRows = pad(r.loopRows, 3, function () { return rowSlot(h1) })
    r.emptyLoop = K.Empty({ text: '后端未提供循环信息（loop）' })
    h1.appendChild(r.emptyLoop)
    cards.appendChild(K.Panel({ title: '循环', hint: 'loop / tick', children: h1 }))

    // 卡 2：生物
    var h2 = K.el('div')
    var dRow = K.el('div', 'kit-stat-row')
    h2.appendChild(dRow)
    r.discomfortCell = statCell(dRow)
    r.interoHost = K.el('div')
    h2.appendChild(r.interoHost)
    r.intero = pad(r.intero, 4, function () {
      var row = K.el('div', 'kit-row')
      var main = K.el('div', 'kit-row-main')
      var label = K.el('b', null, '')
      main.appendChild(label)
      row.appendChild(main)
      var side = K.el('div', 'kit-row-side')
      var bar = K.Bar({ value: 0, max: 1, label: '0.00' })
      side.appendChild(bar)
      row.appendChild(side)
      r.interoHost.appendChild(row)
      return { row: row, label: label, bar: bar, fill: bar.querySelector('.kit-bar-track i'), barLabel: bar.querySelector('.kit-bar-label') }
    })
    r.needsHost = K.el('div')
    h2.appendChild(r.needsHost)
    r.needs = pad(r.needs, 4, function () {
      var row = K.el('div', 'kit-row')
      var main = K.el('div', 'kit-row-main')
      var label = K.el('b', null, '')
      main.appendChild(label)
      row.appendChild(main)
      var side = K.el('div', 'kit-row-side')
      var bar = K.Bar({ value: 0, max: 1, label: '0.00' })
      side.appendChild(bar)
      row.appendChild(side)
      r.needsHost.appendChild(row)
      return { row: row, label: label, bar: bar, fill: bar.querySelector('.kit-bar-track i'), barLabel: bar.querySelector('.kit-bar-label') }
    })
    r.emptyBio = K.Empty({ text: '后端未提供生物信号（bio.discomfort / intero / needs）' })
    h2.appendChild(r.emptyBio)
    cards.appendChild(K.Panel({ title: '生物', hint: 'discomfort / intero 四维', children: h2 }))

    // 卡 3：自主
    var h3 = K.el('div')
    r.autoRows = pad(r.autoRows, 3, function () { return rowSlot(h3) })
    r.emptyAuto = K.Empty({ text: '后端未提供自主数据（autonomy.V / theta / ticks）' })
    h3.appendChild(r.emptyAuto)
    cards.appendChild(K.Panel({ title: '自主', hint: 'V / theta / ticks', children: h3 }))
    root.appendChild(cards)

    // 情绪分布（label + 前 3 概率）
    var eh = K.el('div')
    var eHead = K.el('div', 'kit-stat-row')
    eh.appendChild(eHead)
    r.emoLabel = statCell(eHead)
    r.emoConf = statCell(eHead)
    r.emoMix = K.Badge({ text: '混合（置信度低）', tone: 'muted' })
    r.emoMix.hidden = true
    eh.appendChild(r.emoMix)
    r.emoHost = K.el('div')
    eh.appendChild(r.emoHost)
    r.emo = pad(r.emo, 3, function () {
      var row = K.el('div', 'kit-row')
      var main = K.el('div', 'kit-row-main')
      var label = K.el('b', null, '')
      main.appendChild(label)
      row.appendChild(main)
      var side = K.el('div', 'kit-row-side')
      var bar = K.Bar({ value: 0, max: 1, label: '0.00' })
      side.appendChild(bar)
      row.appendChild(side)
      r.emoHost.appendChild(row)
      return { row: row, label: label, bar: bar, fill: bar.querySelector('.kit-bar-track i'), barLabel: bar.querySelector('.kit-bar-label') }
    })
    r.emptyEmo = K.Empty({ text: '后端未提供情绪分布（bio.emotion_dist）' })
    eh.appendChild(r.emptyEmo)
    root.appendChild(K.Panel({ title: '情绪分布', hint: 'label / 前 3 概率 / confidence', children: eh }))

    // 折叠：原始 JSON
    var hd = K.el('div')
    ;[['paths', 'paths'], ['blocks', 'blocks'], ['policy', 'policy'], ['last_trace', 'last_trace']].forEach(function (pair) {
      var block = K.el('div', 'dbg-json')
      block.appendChild(K.el('b', null, pair[1]))
      var pre = K.el('pre', 'dbg-json', '')
      pre.style.margin = '0'
      pre.style.border = '0'
      pre.style.paddingLeft = '0'
      pre.style.maxHeight = 'none'
      block.appendChild(pre)
      hd.appendChild(block)
      r.json[pair[0]] = { block: block, pre: pre }
    })
    root.appendChild(K.Panel({ fold: true, title: '原始 JSON', hint: 'paths / blocks / policy / last_trace', children: hd }))
    return r
  }

  function apply(r, vm) {
    text(r.top.count, vm.count == null ? '' : String(vm.count))
    text(r.top.discomfort, vm.discomfort == null ? '' : f2(vm.discomfort))
    text(r.top.mode, vm.mode || '')
    text(r.top.pending, vm.pendingAction || '')
    var topCells = r.top.count.parentNode.parentNode.children
    ;[r.top.count, r.top.discomfort, r.top.mode, r.top.pending].forEach(function (node, i) {
      if (topCells[i]) topCells[i].hidden = !node.textContent
    })

    // 循环
    var loopRows = []
    if (vm.count != null) loopRows.push(['计数 count', String(vm.count)])
    if (vm.interval != null) loopRows.push(['间隔 interval', vm.interval + ' s'])
    if (vm.lastTick) loopRows.push(['上次 tick', vm.lastTick + (vm.lastTickAgo ? ' · ' + vm.lastTickAgo : '')])
    r.loopRows.forEach(function (slot, i) {
      var item = loopRows[i]
      show(slot.row, !!item)
      text(slot.label, item ? item[0] : '')
      text(slot.value, item ? item[1] : '')
    })
    show(r.emptyLoop, loopRows.length === 0)

    // 生物
    var bioKnown = vm.discomfort != null || vm.intero.length > 0 || vm.needs.length > 0
    show(r.discomfortCell.cell, vm.discomfort != null)
    text(r.discomfortCell.label, '难受度 discomfort')
    text(r.discomfortCell.value, f2(vm.discomfort))
    var maxIntero = 1
    vm.intero.forEach(function (row) { if (row.value > maxIntero) maxIntero = row.value })
    r.intero.forEach(function (slot, i) {
      var item = vm.intero[i]
      show(slot.row, !!item)
      if (!item) return
      text(slot.label, item.label)
      var pct = Math.max(0, Math.min(100, Math.round((item.value / maxIntero) * 100)))
      slot.fill.style.width = pct + '%'
      text(slot.barLabel, f2(item.value))
    })
    r.needs.forEach(function (slot, i) {
      var item = vm.needs[i]
      show(slot.row, !!item)
      if (!item) return
      text(slot.label, item.label)
      slot.fill.style.width = Math.round(item.value * 100) + '%'
      text(slot.barLabel, '满足 ' + f2(item.value) + ' · 缺口 ' + f2(1 - item.value))
    })
    show(r.emptyBio, !bioKnown)

    // 自主
    var autoRows = []
    if (vm.V != null) autoRows.push(['V 冲动', f2(vm.V)])
    if (vm.theta != null) autoRows.push(['阈值 theta', f2(vm.theta)])
    if (vm.ticks != null) autoRows.push(['距上次触发', vm.ticks + ' tick'])
    r.autoRows.forEach(function (slot, i) {
      var item = autoRows[i]
      show(slot.row, !!item)
      text(slot.label, item ? item[0] : '')
      text(slot.value, item ? item[1] : '')
    })
    show(r.emptyAuto, autoRows.length === 0)

    // 情绪分布
    var emo = vm.emotion
    var hasEmo = !!(emo && (emo.label || emo.top.length))
    show(r.emoLabel.cell, !!(emo && emo.label))
    text(r.emoLabel.label, '当前 label')
    text(r.emoLabel.value, emo && emo.label ? emo.label : '')
    show(r.emoConf.cell, !!(emo && emo.confidence != null))
    text(r.emoConf.label, 'confidence')
    text(r.emoConf.value, emo && emo.confidence != null ? f2(emo.confidence) : '')
    show(r.emoMix, !!(emo && emo.confidence != null && emo.confidence < MIXED_CONFIDENCE))
    r.emo.forEach(function (slot, i) {
      var item = emo && emo.top[i]
      show(slot.row, !!item)
      if (!item) return
      text(slot.label, item.label)
      var p = item.prob == null ? 0 : Math.max(0, Math.min(1, item.prob))
      slot.fill.style.width = Math.round(p * 100) + '%'
      text(slot.barLabel, item.prob == null ? '—' : f2(item.prob))
    })
    show(r.emptyEmo, !hasEmo)

    // JSON
    ;[['paths', vm.paths], ['blocks', vm.blocks], ['policy', vm.policy], ['last_trace', vm.lastTrace]].forEach(function (pair) {
      var slot = r.json[pair[0]]
      if (!slot) return
      var body = jsonText(pair[1])
      show(slot.block, body != null)
      text(slot.pre, body == null ? '' : body)
    })

    var hint = $('debugHint')
    if (hint) {
      hint.classList.toggle('is-error', !!state.error)
      hint.textContent = state.error ? '读取失败' : (vm.preview ? '预览（未连接后端）· 结构示例' : 'page/debug · 只读')
    }
  }

  function render() {
    var root = $('debugRoot')
    if (!root) return
    if (!refs) refs = build(root)
    var vm = map(state.data || {})
    show(refs.error, !!state.error)
    text(refs.error, state.error ? ('读取失败：' + state.error) : '')
    apply(refs, vm)
  }

  function refresh() {
    if (inflight) return
    if (document.hidden) return
    var view = $('view-debug')
    if (state.ready && view && !view.classList.contains('active')) return
    var bridge = pageBridge()
    if (!bridge) {
      var demo = window.__biocoreDebugData
      if (!demo) { setTimeout(refresh, 700); return }
      state.data = demo; state.preview = true; state.ready = true; state.error = ''
      render(); return
    }
    inflight = true
    Promise.resolve(bridge.apiGet(API.status, {})).then(function (raw) {
      var d = unwrap(raw)
      if (d && d.ok === false) throw new Error(d.message || d.error || 'page/debug 返回 ok=false')
      state.data = d || {}; state.preview = false; state.ready = true; state.error = ''
      render()
    }).catch(function (e) {
      state.error = String((e && e.message) || e)
      state.ready = true
      render()
    }).then(function () { inflight = false })
  }

  function boot() {
    if (!$('debugRoot')) return
    refresh()
    setInterval(refresh, POLL_MS)
    window.addEventListener('page:show', function (e) { if (e && e.detail && e.detail.id === 'debug') refresh() })
    document.addEventListener('visibilitychange', function () { if (!document.hidden) refresh() })
    window.__biocoreDebug = { refresh: refresh, state: state }
  }
  if (window.__Registry) {
    window.__Registry.registerPage({ id: 'debug', label: '调试', group: 'advanced', order: 95, icon: 'list', data: ['debug'], render: function () { return document.getElementById('view-debug') } })
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot)
  else boot()
})()
