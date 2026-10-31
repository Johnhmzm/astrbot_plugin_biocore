/* UI-KIT 页面 · 记录（pages/dashboard/records.js）
 * 数据：GET page/status（宿主页面桥）→ autonomy.last_reason / autonomy.state.limit / loop.last_attempt
 * 结构：顶部一句话 → 2 张卡 → 1 个折叠「详细数据」；缺字段用 Empty。
 * 轮询：5 秒；首次建骨架，之后只改文本/隐藏态，不重建 DOM。
 * 组件：Panel / Row / Stat / Badge / Empty（ui_kit.js）。
 */
(function () {
  'use strict'
  if (window.__ui3RecInstalled) return
  window.__ui3RecInstalled = true

  var K = window.UIKit
  if (!K) { try { console.error('[records] ui_kit.js 未加载') } catch (e) {} return }

  var API = { status: 'page/status' }
  var POLL_MS = 5000
  var CODE_ZH = {
    lonely: '寂寞', social_gap: '社交缺口', open_loops: '未了话题', nostalgia: '怀旧',
    joy: '愉悦', boredom: '无聊', anxiety_fear: '焦虑', stress_load: '压力',
    attachment: '依恋', rumination: '反刍'
  }

  var state = { data: null, preview: false, ready: false, error: '' }
  var refs = null
  var inflight = false

  function $(id) { return document.getElementById(id) }
  function text(node, value) { if (node) node.textContent = value == null ? '' : String(value) }
  function show(node, on) { if (node) node.hidden = !on }
  function num(v) { var n = Number(v); return (v === null || v === undefined || v === '') ? null : (isFinite(n) ? n : null) }
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
    try { return new Date(n * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) } catch (e) { return null }
  }

  function map(d) {
    var autoAll = obj(d.autonomy) || {}
    var auto = obj(autoAll.state) || obj(d.autonomy_state) || {}
    var lastReason = obj(autoAll.last_reason) || obj(auto.last_reason)
    var loop = obj(auto.loop)
    var attempt = null
    if (loop && obj(loop.last_attempt) && num(loop.last_attempt.ts) != null) attempt = loop.last_attempt
    if (!attempt && obj(auto.last_attempt) && num(auto.last_attempt.ts) != null) attempt = auto.last_attempt
    var limit = obj(auto.limit)
    return {
      preview: state.preview,
      reasonText: lastReason && lastReason.text ? String(lastReason.text) : null,
      reasonTs: lastReason ? when(lastReason.ts) : null,
      reasonCode: lastReason && lastReason.code ? (CODE_ZH[String(lastReason.code)] || String(lastReason.code)) : null,
      attemptTs: attempt ? when(attempt.ts) : null,
      attemptCode: attempt && attempt.code ? (CODE_ZH[String(attempt.code)] || String(attempt.code)) : null,
      loopSent: loop && num(loop.sent) != null ? num(loop.sent) : null,
      limit: limit ? {
        totalBlocked: num(limit.total_blocked), hourSent: num(limit.hour_sent), hourlyCap: num(limit.hourly_cap),
        dailyCap: num(limit.daily_cap), frustration: num(limit.frustration), resetIn: num(limit.window_reset_in),
        driveMult: num(limit.drive_mult)
      } : null,
      hasLimit: !!limit && num(limit.total_blocked) != null
    }
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
    var r = { rowsA: [], statsB: [], detail: [] }
    r.error = K.el('p', 'notice')
    r.error.hidden = true
    root.appendChild(r.error)

    var hero = K.el('div', 'kit-hero')
    var line = K.el('p', 'kit-hero-line')
    r.heroPrefix = document.createTextNode('')
    line.appendChild(r.heroPrefix)
    r.heroValue = K.el('b', null, '')
    line.appendChild(r.heroValue)
    r.heroNote = K.el('small', 'kit-hero-note', '')
    line.appendChild(r.heroNote)
    hero.appendChild(line)
    root.appendChild(hero)

    var cards = K.el('div', 'kit-cards kit-cards-2')

    var h1 = K.el('div')
    r.rowsA = pad(r.rowsA, 4, function () { return rowSlot(h1) })
    r.badgeA = K.Badge({ text: '', tone: 'muted' })
    h1.appendChild(r.badgeA)
    r.emptyA = K.Empty({ text: '后端未提供 last_reason（autonomy.last_reason）' })
    h1.appendChild(r.emptyA)
    cards.appendChild(K.Panel({ title: '她主动发过', hint: 'last_reason / last_attempt', children: h1 }))

    var h2 = K.el('div')
    r.blockedStat = statCell(h2)
    var srow = K.el('div', 'kit-stat-row')
    h2.appendChild(srow)
    r.statsB.push(statCell(srow), statCell(srow), statCell(srow), statCell(srow))
    r.noteB = K.el('p', 'kit-note', '')
    h2.appendChild(r.noteB)
    r.emptyB = K.Empty({ text: '后端未提供 limit.total_blocked（autonomy.state.limit）' })
    h2.appendChild(r.emptyB)
    cards.appendChild(K.Panel({ title: '被限制次数', hint: 'limit', children: h2 }))
    root.appendChild(cards)

    var hd = K.el('div')
    ;['来源', 'last_reason', 'limit', 'loop.sent', 'window_reset_in']
      .forEach(function (label) { r.detail.push(rowSlot(hd)) })
    root.appendChild(K.Panel({ fold: true, title: '详细数据', hint: '原始字段', children: hd }))
    return r
  }

  function apply(r, vm) {
    var lm = vm.limit
    if (vm.reasonText) {
      r.heroPrefix.nodeValue = '她主动说：'
      text(r.heroValue, vm.reasonText.length > 30 ? vm.reasonText.slice(0, 30) + '…' : vm.reasonText)
      text(r.heroNote, vm.reasonTs || '')
    } else if (vm.hasLimit) {
      r.heroPrefix.nodeValue = '累计被限制 '
      text(r.heroValue, vm.limit.totalBlocked + ' 次')
      text(r.heroNote, '')
    } else if (vm.attemptTs) {
      r.heroPrefix.nodeValue = '最近一次主动尝试：'
      text(r.heroValue, vm.attemptCode || '（未提供原因码）')
      text(r.heroNote, vm.attemptTs)
    } else {
      r.heroPrefix.nodeValue = ''
      text(r.heroValue, '暂无主动记录')
      text(r.heroNote, '')
    }
    show(r.heroValue, true)

    // 卡 1
    var rowsA = []
    if (vm.reasonText) rowsA.push(['原因', vm.reasonText])
    if (vm.reasonTs) rowsA.push(['时间', vm.reasonTs])
    if (vm.reasonCode) rowsA.push(['原因码', vm.reasonCode])
    if (vm.attemptTs) rowsA.push(['最近尝试', vm.attemptTs + (vm.attemptCode ? ' · ' + vm.attemptCode : '')])
    r.rowsA.forEach(function (slot, i) {
      var item = rowsA[i]
      show(slot.row, !!item)
      text(slot.label, item ? item[0] : '')
      text(slot.value, item ? item[1] : '')
    })
    var hasA = rowsA.length > 0
    show(r.badgeA, vm.loopSent != null)
    if (vm.loopSent != null) {
      r.badgeA.className = 'kit-badge tone-muted'
      text(r.badgeA, '累计主动 ' + vm.loopSent + ' 次')
    }
    show(r.emptyA, !hasA)

    // 卡 2
    var bKnown = vm.hasLimit
    show(r.blockedStat.cell, bKnown)
    text(r.blockedStat.label, '累计被限制')
    text(r.blockedStat.value, bKnown ? String(vm.limit.totalBlocked) : '')
    var bStats = []
    if (lm) {
      if (lm.hourSent != null || lm.hourlyCap != null) bStats.push(['本小时已发', (lm.hourSent == null ? '未提供' : lm.hourSent) + ' / ' + (lm.hourlyCap == null ? '未提供' : lm.hourlyCap)])
      if (lm.dailyCap != null) bStats.push(['每日上限', String(lm.dailyCap)])
      if (lm.frustration != null) bStats.push(['挫折累积', String(lm.frustration)])
      if (lm.driveMult != null) bStats.push(['增益 ×', String(lm.driveMult)])
    }
    r.statsB.forEach(function (cell, i) {
      var item = bStats[i]
      show(cell.cell, !!item)
      text(cell.label, item ? item[0] : '')
      text(cell.value, item ? item[1] : '')
    })
    var noteBits = []
    if (lm && lm.resetIn != null) noteBits.push('本小时窗口 ' + Math.round(lm.resetIn / 60) + ' 分钟后重置')
    noteBits.push('限制只记录、不发送。')
    text(r.noteB, bKnown ? noteBits.join(' ') : '')
    show(r.noteB, bKnown)
    show(r.emptyB, !bKnown)

    // 详细
    var detail = [
      ['来源', vm.preview ? '预览示例（页面桥未连接）' : 'GET page/status · autonomy'],
      ['last_reason', vm.reasonText ? (vm.reasonText + (vm.reasonCode ? ' · ' + vm.reasonCode : '')) : null],
      ['limit', bKnown ? ('total_blocked=' + vm.limit.totalBlocked + ' · hour_sent=' + (lm.hourSent == null ? '未提供' : lm.hourSent) + ' · frustration=' + (lm.frustration == null ? '未提供' : lm.frustration)) : null],
      ['loop.sent', vm.loopSent == null ? null : String(vm.loopSent)],
      ['window_reset_in', lm && lm.resetIn != null ? (Math.round(lm.resetIn) + ' s') : null]
    ]
    r.detail.forEach(function (slot, i) {
      var pair = detail[i]
      show(slot.row, !!(pair && pair[1] != null))
      text(slot.label, pair ? pair[0] : '')
      text(slot.value, pair && pair[1] != null ? pair[1] : '')
    })

    var hint = $('recHint')
    if (hint) {
      hint.classList.toggle('is-error', !!state.error)
      hint.textContent = state.error ? '读取失败' : (vm.preview ? '预览（未连接后端）· 结构示例' : 'page/status · 只读')
    }
  }

  function render() {
    var root = $('recRoot')
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
    var view = $('view-records')
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
    if (!$('recRoot')) return
    refresh()
    setInterval(refresh, POLL_MS)
    window.addEventListener('page:show', function (e) { if (e && e.detail && e.detail.id === 'records') refresh() })
    document.addEventListener('visibilitychange', function () { if (!document.hidden) refresh() })
    window.__biocoreRec = { refresh: refresh, state: state }
  }
  if (window.__Registry) {
    window.__Registry.registerPage({ id: 'records', label: '记录', group: 'main', order: 28, icon: 'records', data: ['status'], render: function () { return document.getElementById('view-records') } })
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot)
  else boot()
})()
