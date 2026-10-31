/* UI-KIT 页面 · 关系（pages/dashboard/relationship.js）
 * 数据：GET page/status（宿主页面桥）→ autonomy.state.relationship / trust / loop
 * 结构：顶部一句话 + 被回率条 → 3 张卡 → 1 个折叠「详细数据」；缺字段用 Empty。
 * 轮询：5 秒；首次建骨架，之后只改文本/隐藏态，不重建 DOM。
 * 组件：Panel / Row / Stat / Bar / Empty（ui_kit.js）。
 */
(function () {
  'use strict'
  if (window.__ui3RelInstalled) return
  window.__ui3RelInstalled = true

  var K = window.UIKit
  if (!K) { try { console.error('[relationship] ui_kit.js 未加载') } catch (e) {} return }

  var API = { status: 'page/status' }
  var POLL_MS = 5000
  var STAGE_ZH = { stranger: '陌生人', acquaintance: '熟人', friend: '朋友', close: '亲密', intimate: '亲密' }

  var state = { data: null, preview: false, ready: false, error: '' }
  var refs = null
  var inflight = false

  function $(id) { return document.getElementById(id) }
  function text(node, value) { if (node) node.textContent = value == null ? '' : String(value) }
  function show(node, on) { if (node) node.hidden = !on }
  function num(v) { var n = Number(v); return (v === null || v === undefined || v === '') ? null : (isFinite(n) ? n : null) }
  function f2(v) { var n = num(v); return n == null ? null : n.toFixed(2) }
  function pct(v) { var n = num(v); return n == null ? null : Math.round(Math.max(0, Math.min(1, n)) * 100) + '%' }
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
  function hoursText(hours) {
    if (hours == null) return null
    return hours >= 24 ? (hours / 24).toFixed(1) + ' 天（' + hours.toFixed(1) + ' h）' : hours.toFixed(1) + ' 小时'
  }

  function map(d) {
    var auto = obj(obj(d.autonomy) && d.autonomy.state) || obj(d.autonomy_state) || {}
    var rel = obj(auto.relationship)
    var trust = obj(auto.trust)
    var loop = obj(auto.loop)
    var bid = obj(auto.bid)
    var vm = {
      preview: state.preview,
      stage: rel && rel.stage ? (STAGE_ZH[String(rel.stage)] || String(rel.stage)) : null,
      hours: rel && num(rel.hours_total) != null ? num(rel.hours_total) : null,
      trust: trust ? { predictability: num(trust.predictability), dependability: num(trust.dependability), faith: num(trust.faith) } : null,
      loop: loop ? {
        sent: num(loop.sent), responded: num(loop.responded), ignored: num(loop.ignored),
        rate: num(loop.response_rate), latency: num(loop.avg_latency_s)
      } : null,
      bid: bid ? { sent: num(bid.sent), toward: num(bid.toward), away: num(bid.away), frequency: num(bid.frequency) } : null,
      attempts: loop ? loop.last_attempt && num(loop.last_attempt.ts) != null ? loop.last_attempt : null : null
    }
    return vm
  }

  function statCell(host) {
    var cell = K.el('div', 'kit-stat')
    cell.appendChild(K.el('small', 'kit-stat-label', ''))
    var value = K.el('span', 'kit-stat-value', '')
    cell.appendChild(value)
    host.appendChild(cell)
    return { cell: cell, label: cell.querySelector('.kit-stat-label'), value: value }
  }
  function rowSlot(host) {
    var row = K.Row({ label: '', value: K.el('span', 'kit-row-value', '') })
    host.appendChild(row)
    return { row: row, label: row.querySelector('.kit-row-main b'), value: row.querySelector('.kit-row-value') }
  }
  function pad(list, size, make) { while (list.length < size) list.push(make()); return list }

  function build(root) {
    root.textContent = ''
    var r = { rowsA: [], trustStats: {}, statsB: [], rowsB: [], detail: [] }
    r.error = K.el('p', 'notice')
    r.error.hidden = true
    root.appendChild(r.error)

    var hero = K.el('div', 'kit-hero')
    var line = K.el('p', 'kit-hero-line')
    line.appendChild(document.createTextNode('关系：'))
    r.stageValue = K.el('b', null, '')
    line.appendChild(r.stageValue)
    r.stageNote = K.el('small', 'kit-hero-note', '')
    line.appendChild(r.stageNote)
    hero.appendChild(line)
    r.heroBar = K.el('div', 'kit-bar')
    var track = K.el('div', 'kit-bar-track')
    r.heroFill = K.el('i')
    track.appendChild(r.heroFill)
    r.heroBar.appendChild(track)
    r.heroLabel = K.el('small', 'kit-bar-label', '')
    r.heroBar.appendChild(r.heroLabel)
    hero.appendChild(r.heroBar)
    root.appendChild(hero)

    var cards = K.el('div', 'kit-cards')

    // 卡 1：阶段与累计时长
    var h1 = K.el('div')
    r.rowsA = pad(r.rowsA, 4, function () { return rowSlot(h1) })
    r.emptyA = K.Empty({ text: '后端未提供关系记录（autonomy.state.relationship）' })
    h1.appendChild(r.emptyA)
    cards.appendChild(K.Panel({ title: '阶段与累计时长', hint: 'relationship', children: h1 }))

    // 卡 2：信任三层
    var h2 = K.el('div')
    var srow = K.el('div', 'kit-stat-row')
    h2.appendChild(srow)
    r.trustStats.p = statCell(srow)
    r.trustStats.d = statCell(srow)
    r.trustStats.f = statCell(srow)
    r.trustBar = K.el('div', 'kit-bar')
    var t2 = K.el('div', 'kit-bar-track')
    r.trustFill = K.el('i')
    t2.appendChild(r.trustFill)
    r.trustBar.appendChild(t2)
    r.trustLabel = K.el('small', 'kit-bar-label', '')
    r.trustBar.appendChild(r.trustLabel)
    h2.appendChild(r.trustBar)
    r.emptyB = K.Empty({ text: '后端未提供信任三层（predictability / dependability / faith）' })
    h2.appendChild(r.emptyB)
    cards.appendChild(K.Panel({ title: '信任三层', hint: 'predictability / dependability / faith', children: h2 }))

    // 卡 3：bid 统计
    var h3 = K.el('div')
    var brow = K.el('div', 'kit-stat-row')
    h3.appendChild(brow)
    r.statsB.push(statCell(brow), statCell(brow), statCell(brow), statCell(brow))
    r.rowsB = pad(r.rowsB, 3, function () { return rowSlot(h3) })
    r.bidBar = K.el('div', 'kit-bar')
    var t3 = K.el('div', 'kit-bar-track')
    r.bidFill = K.el('i')
    t3.appendChild(r.bidFill)
    r.bidBar.appendChild(t3)
    r.bidLabel = K.el('small', 'kit-bar-label', '')
    r.bidBar.appendChild(r.bidLabel)
    h3.appendChild(r.bidBar)
    r.emptyC = K.Empty({ text: '后端未提供 loop / bid 统计（autonomy.state.loop）' })
    h3.appendChild(r.emptyC)
    cards.appendChild(K.Panel({ title: '最近 7 天 bid 统计', hint: 'loop / bid', children: h3 }))
    root.appendChild(cards)

    var hd = K.el('div')
    ;['来源', 'relationship', 'trust', 'loop', 'bid', 'last_attempt']
      .forEach(function (label) { r.detail.push(rowSlot(hd)) })
    root.appendChild(K.Panel({ fold: true, title: '详细数据', hint: '原始字段', children: hd }))
    return r
  }

  function apply(r, vm) {
    var hasRel = vm.stage != null || vm.hours != null
    show(r.stageValue, vm.stage != null)
    text(r.stageValue, vm.stage || '')
    if (vm.stage == null) r.stageNote.textContent = hasRel ? '阶段未提供' : '后端未提供 relationship.stage'
    else text(r.stageNote, vm.hours == null ? '累计时长未提供' : ('累计 ' + hoursText(vm.hours)))
    if (vm.stage == null && vm.hours != null) text(r.stageNote, '累计 ' + hoursText(vm.hours) + ' · 阶段未提供')

    var hasRate = vm.loop && vm.loop.rate != null
    show(r.heroBar, !!hasRate)
    if (hasRate) {
      r.heroFill.style.width = Math.round(Math.max(0, Math.min(1, vm.loop.rate)) * 100) + '%'
      text(r.heroLabel, '被回率 ' + pct(vm.loop.rate))
    }

    // 卡 1
    var aRows = []
    if (vm.stage != null) aRows.push(['阶段', vm.stage])
    if (vm.hours != null) aRows.push(['累计时长', hoursText(vm.hours)])
    if (vm.loop && vm.loop.sent != null) aRows.push(['她主动', vm.loop.sent + ' 次'])
    if (vm.attempts) aRows.push(['最近尝试', (vm.attempts.code || '—') + ' · ' + new Date(num(vm.attempts.ts) * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })])
    r.rowsA.forEach(function (slot, i) {
      var item = aRows[i]
      show(slot.row, !!item)
      text(slot.label, item ? item[0] : '')
      text(slot.value, item ? item[1] : '')
    })
    show(r.emptyA, aRows.length === 0)

    // 卡 2
    var t = vm.trust
    var trustKnown = !!(t && (t.predictability != null || t.dependability != null || t.faith != null))
    ;[['p', t && t.predictability, '可预测'], ['d', t && t.dependability, '可靠'], ['f', t && t.faith, '信念']].forEach(function (row) {
      var cell = r.trustStats[row[0]]
      show(cell.cell, row[1] != null)
      text(cell.label, row[2])
      text(cell.value, f2(row[1]))
    })
    show(r.trustBar, trustKnown && t.predictability != null)
    if (trustKnown && t.predictability != null) {
      r.trustFill.style.width = Math.round(Math.max(0, Math.min(1, t.predictability)) * 100) + '%'
      text(r.trustLabel, '可预测 ' + pct(t.predictability))
    }
    show(r.emptyB, !trustKnown)

    // 卡 3
    var l = vm.loop
    var bidKnown = !!(l) || !!(vm.bid)
    var bStats = []
    if (l) {
      if (l.sent != null) bStats.push(['主动', String(l.sent)])
      if (l.responded != null) bStats.push(['被回', String(l.responded)])
      if (l.rate != null) bStats.push(['被回率', pct(l.rate)])
      if (l.latency != null) bStats.push(['平均回应', Math.round(l.latency / 60) + ' 分'])
    }
    r.statsB.forEach(function (cell, i) {
      var item = bStats[i]
      show(cell.cell, !!item)
      text(cell.label, item ? item[0] : '')
      text(cell.value, item ? item[1] : '')
    })
    var bRows = []
    if (l && l.ignored != null) bRows.push(['未回', l.ignored + ' 次'])
    if (vm.bid) {
      if (vm.bid.sent != null) bRows.push(['连接邀请', vm.bid.sent + ' 次'])
      if (vm.bid.toward != null || vm.bid.away != null) bRows.push(['接住 / 落空', (vm.bid.toward == null ? '未提供' : vm.bid.toward) + ' / ' + (vm.bid.away == null ? '未提供' : vm.bid.away)])
      if (vm.bid.frequency != null) bRows.push(['频率 ×', f2(vm.bid.frequency)])
    }
    r.rowsB.forEach(function (slot, i) {
      var item = bRows[i]
      show(slot.row, !!item)
      text(slot.label, item ? item[0] : '')
      text(slot.value, item ? item[1] : '')
    })
    show(r.bidBar, !!(l && l.rate != null))
    if (l && l.rate != null) {
      r.bidFill.style.width = Math.round(Math.max(0, Math.min(1, l.rate)) * 100) + '%'
      text(r.bidLabel, 'response_rate ' + pct(l.rate))
    }
    show(r.emptyC, !bidKnown)

    // 详细
    var detail = [
      ['来源', vm.preview ? '预览示例（页面桥未连接）' : 'GET page/status · autonomy.state'],
      ['relationship', vm.stage == null && vm.hours == null ? null : ('stage=' + (vm.stage == null ? '未提供' : vm.stage) + ' · hours_total=' + (vm.hours == null ? '未提供' : vm.hours))],
      ['trust', t ? ('可预测 ' + (f2(t.predictability) || '未提供') + ' · 可靠 ' + (f2(t.dependability) || '未提供') + ' · 信念 ' + (f2(t.faith) || '未提供')) : null],
      ['loop', l ? ('sent=' + (l.sent == null ? '未提供' : l.sent) + ' · responded=' + (l.responded == null ? '未提供' : l.responded) + ' · rate=' + (l.rate == null ? '未提供' : f2(l.rate))) : null],
      ['bid', vm.bid ? ('sent=' + (vm.bid.sent == null ? '未提供' : vm.bid.sent) + ' · toward=' + (vm.bid.toward == null ? '未提供' : vm.bid.toward) + ' · away=' + (vm.bid.away == null ? '未提供' : vm.bid.away)) : null],
      ['last_attempt', vm.attempts ? ((vm.attempts.code || '—') + ' @ ' + num(vm.attempts.ts)) : null]
    ]
    r.detail.forEach(function (slot, i) {
      var pair = detail[i]
      show(slot.row, !!(pair && pair[1] != null))
      text(slot.label, pair ? pair[0] : '')
      text(slot.value, pair && pair[1] != null ? pair[1] : '')
    })

    var hint = $('relHint')
    if (hint) {
      hint.classList.toggle('is-error', !!state.error)
      hint.textContent = state.error ? '读取失败' : (vm.preview ? '预览（未连接后端）· 结构示例' : 'page/status · 只读')
    }
  }

  function render() {
    var root = $('relRoot')
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
    var view = $('view-relationship')
    if (state.ready && view && !view.classList.contains('active')) return
    var bridge = pageBridge()
    if (!bridge) {
      var demo = window.__biocoreData
      if (!demo) { setTimeout(refresh, 700); return }
      state.data = demo; state.preview = true; state.ready = true; state.error = ''
      render(); return
    }
    inflight = true
    Promise.resolve(bridge.apiGet(API.status, {})).then(function (raw) {
      var d = unwrap(raw)
      if (d && d.ok === false) throw new Error(d.message || d.error || 'page/status 返回 ok=false')
      state.data = d || {}; state.preview = false; state.ready = true; state.error = ''
      render()
    }).catch(function (e) {
      state.error = String((e && e.message) || e)
      state.ready = true
      render()
    }).then(function () { inflight = false })
  }

  function boot() {
    if (!$('relRoot')) return
    refresh()
    setInterval(refresh, POLL_MS)
    window.addEventListener('page:show', function (e) { if (e && e.detail && e.detail.id === 'relationship') refresh() })
    document.addEventListener('visibilitychange', function () { if (!document.hidden) refresh() })
    window.__biocoreRel = { refresh: refresh, state: state }
  }
  if (window.__Registry) {
    window.__Registry.registerPage({ id: 'relationship', label: '关系', group: 'main', order: 25, icon: 'relation', data: ['status'], render: function () { return document.getElementById('view-relationship') } })
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot)
  else boot()
})()
