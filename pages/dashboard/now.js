/* UI-KIT 页面 · 她现在（pages/dashboard/now.js）
 * 数据：GET page/status（宿主页面桥）→ autonomy.state（V / theta / silence / motive / sleep / mood / labels / self_esteem）
 * 结构：顶部一句话 + V 进度条 → 3 张卡 → 1 个折叠「详细数据」；缺字段用 Empty，不显示占位破折号。
 * 轮询：5 秒；首次建骨架，之后只改文本/隐藏态，不重建 DOM。
 * 组件：Panel / Row / Bar / Stat / Empty（ui_kit.js）。
 */
(function () {
  'use strict'
  if (window.__ui3NowInstalled) return
  window.__ui3NowInstalled = true

  var K = window.UIKit
  if (!K) { try { console.error('[now] ui_kit.js 未加载') } catch (e) {} return }

  var API = { status: 'page/status' }
  var POLL_MS = 5000
  var PART_ZH = {
    social_gap: '社交缺口', lonely: '寂寞', anxiety_fear: '焦虑', sadness: '悲伤',
    distress: '难受', joy: '愉悦', anger_conflict: '愤怒', boredom: '无聊',
    activity: '勤快', stress_load: '压力', drive_dev: '需求缺口', open_loops: '未了话题',
    nostalgia: '怀旧', rumination: '反刍', attachment: '依恋', fatigue: '疲惫'
  }
  var EMO_ZH = {
    neutral: '平静', joy: '开心', sadness: '难过', fear: '害怕', anger: '生气',
    surprise: '惊讶', trust: '信任', loneliness: '孤独', lonely: '孤独',
    anticipation: '期待', disgust: '厌恶', shyness: '害羞'
  }
  var PHASE_ZH = { expect: '期待', protest: '有点急', loss: '失落', withdraw: '抽离' }
  var GATE_ZH = {
    ready: '可发送', not_ready: '未达阈值', cooldown: '冷却中', daily_cap: '今日已达上限',
    quiet_hours: '静默时段', no_session: '无可用会话', not_private: '非私聊会话',
    send_disabled: '发送已关闭', fired: '刚发出'
  }

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
    try { return new Date(n * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) } catch (e) { return null }
  }

  /* ---------- 纯映射：page/status → 视图模型（缺字段一律 null） ---------- */
  function map(d) {
    var autoAll = obj(d.autonomy) || {}
    var auto = obj(autoAll.state) || obj(d.autonomy_state) || {}
    var core = (d.cores && d.cores[0] && obj(d.cores[0].snapshot)) || {}
    var sleep = obj(auto.sleep) || {}
    var silence = obj(auto.silence)
    var motive = obj(auto.motive)
    var parts = obj(auto.parts)
    var mood = obj(auto.mood)
    var labels = obj(auto.labels)
    var esteem = obj(auto.self_esteem)
    var vm = {
      preview: state.preview,
      V: num(auto.V), theta: num(auto.theta),
      gate: auto.block_reason ? (GATE_ZH[String(auto.block_reason)] || String(auto.block_reason)) : null,
      sendEnabled: typeof autoAll.enabled === 'boolean' ? autoAll.enabled : null,
      waitHours: silence && num(silence.hours) != null ? num(silence.hours) : null,
      waitPhase: silence && silence.phase ? (PHASE_ZH[String(silence.phase)] || String(silence.phase)) : null,
      waitSource: silence && num(silence.hours) != null ? '沉默曲线' : null,
      parts: [], motiveRows: [],
      energy: num(sleep.energy) != null ? num(sleep.energy) : num(auto.energy),
      sleepDebt: num(sleep.sleep_debt) != null ? num(sleep.sleep_debt) : num(auto.sleep_debt),
      circadian: num(sleep.circadian) != null ? num(sleep.circadian) : (num(auto.circadian) != null ? num(auto.circadian) : num(d.circadian_alertness)),
      sleeping: typeof sleep.sleeping === 'boolean' ? sleep.sleeping : null,
      fatigue: num(sleep.fatigue) != null ? num(sleep.fatigue) : num(core.fatigue),
      moodLabel: null, valence: null, esteem: null,
      stress: num(core.stress),
      social: num(core.social),
      detail: { lastSeen: null, allostatic: num(d.allostatic_load), Lint: null }
    }
    if (parts) {
      Object.keys(parts).filter(function (k) { return num(parts[k]) != null && num(parts[k]) > 0 })
        .sort(function (a, b) { return num(parts[b]) - num(parts[a]) })
        .slice(0, 4)
        .forEach(function (k) { vm.parts.push({ label: PART_ZH[k] || String(k), value: f2(parts[k]) }) })
    }
    if (motive) {
      if (num(motive.hours) != null) vm.motiveRows.push({ label: '等你的时长', value: f2(motive.hours) + ' h' })
      if (num(motive.self_blame) != null) vm.motiveRows.push({ label: '自责', value: f2(motive.self_blame) })
      if (num(motive.confidence) != null) vm.motiveRows.push({ label: '表达自信', value: f2(motive.confidence) })
      if (num(motive.frust_mult) != null) vm.motiveRows.push({ label: '挫折增益', value: '×' + f2(motive.frust_mult) })
    }
    var labelKey = (mood && mood.label) || (labels && labels.top) || (labels && labels.dominant) || null
    if (!labelKey && labels) {
      var best = null
      Object.keys(labels).forEach(function (k) {
        var n = num(labels[k])
        if (n == null) return
        if (!best || n > best.n) best = { k: k, n: n }
      })
      if (best) labelKey = best.k
    }
    vm.moodLabel = labelKey ? (EMO_ZH[String(labelKey)] || String(labelKey)) : null
    vm.valence = mood && num(mood.valence) != null ? num(mood.valence) : num(core.v)
    vm.esteem = esteem && num(esteem.value) != null ? num(esteem.value) : null
    var rel = (d.relationships && obj(d.relationships[0])) || null
    vm.detail.lastSeen = rel && num(rel.last_seen) != null ? when(rel.last_seen) : null
    var homeo = obj(d.homeostasis) || {}
    if (num(homeo.L_int) != null) vm.detail.Lint = f2(homeo.L_int)
    return vm
  }

  /* ---------- 建骨架（只跑一次） ---------- */
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
    var r = { parts: [], motiveRows: [], stats: {}, rows: {}, detail: [] }
    r.error = K.el('p', 'notice')
    r.error.hidden = true
    root.appendChild(r.error)

    var hero = K.el('div', 'kit-hero')
    var line = K.el('p', 'kit-hero-line')
    r.waitPrefix = K.el('span', null, '她等了你 ')
    line.appendChild(r.waitPrefix)
    r.waitValue = K.el('b', null, '')
    line.appendChild(r.waitValue)
    r.waitNote = K.el('small', 'kit-hero-note', '')
    line.appendChild(r.waitNote)
    hero.appendChild(line)
    var bar = K.el('div', 'kit-bar')
    var track = K.el('div', 'kit-bar-track')
    r.barFill = K.el('i')
    track.appendChild(r.barFill)
    bar.appendChild(track)
    r.barLabel = K.el('small', 'kit-bar-label', '')
    bar.appendChild(r.barLabel)
    r.bar = bar
    hero.appendChild(bar)
    root.appendChild(hero)

    var cards = K.el('div', 'kit-cards')

    // 卡 1：想你的理由
    var reasonHost = K.el('div')
    r.parts = pad(r.parts, 4, function () { return rowSlot(reasonHost) })
    r.motiveRows = pad(r.motiveRows, 4, function () { return rowSlot(reasonHost) })
    r.reasonEmpty = K.Empty({ text: '后端未提供动机分解（autonomy.state.motive / parts）' })
    reasonHost.appendChild(r.reasonEmpty)
    cards.appendChild(K.Panel({ title: '想你的理由', hint: 'motive / parts', children: reasonHost }))

    // 卡 2：她的身体
    var bodyHost = K.el('div')
    var bodyRow = K.el('div', 'kit-stat-row')
    bodyHost.appendChild(bodyRow)
    r.stats.energy = statCell(bodyRow)
    r.stats.sleepDebt = statCell(bodyRow)
    r.stats.circadian = statCell(bodyRow)
    r.stats.fatigue = statCell(bodyRow)
    r.sleepRow = rowSlot(bodyHost)
    r.bodyEmpty = K.Empty({ text: '后端未提供身体信号（energy / sleep_debt / circadian）' })
    bodyHost.appendChild(r.bodyEmpty)
    cards.appendChild(K.Panel({ title: '她的身体', hint: '精力 / 睡眠债 / 节律', children: bodyHost }))

    // 卡 3：她的心情
    var moodHost = K.el('div')
    var moodRow = K.el('div', 'kit-stat-row')
    moodHost.appendChild(moodRow)
    r.stats.mood = statCell(moodRow)
    r.stats.valence = statCell(moodRow)
    r.stats.stress = statCell(moodRow)
    r.stats.esteem = statCell(moodRow)
    r.moodEmpty = K.Empty({ text: '后端未提供心情数据（labels / mood / self_esteem）' })
    moodHost.appendChild(r.moodEmpty)
    cards.appendChild(K.Panel({ title: '她的心情', hint: '心情 / 效价 / 自尊', children: moodHost }))
    root.appendChild(cards)

    // 折叠：详细数据
    var detailHost = K.el('div')
    ;['V / 阈值', 'gate', '发送开关', '沉默小时', '表达自信', '上次说话', 'core.stress', 'core.social', 'allostatic', 'homeostasis.L_int', '数据来源']
      .forEach(function (label) { r.detail.push(rowSlot(detailHost)) })
    root.appendChild(K.Panel({ fold: true, title: '详细数据', hint: '原始字段', children: detailHost }))
    return r
  }

  /* ---------- 只改文本 ---------- */
  function apply(r, vm) {
    var waitKnown = vm.waitHours != null
    show(r.waitPrefix, waitKnown)
    show(r.waitValue, waitKnown)
    text(r.waitValue, waitKnown ? (vm.waitHours >= 24 ? (vm.waitHours / 24).toFixed(1) + ' 天' : vm.waitHours.toFixed(1) + ' 小时') : '')
    var waitBits = []
    if (waitKnown) { waitBits.push(vm.waitSource || ''); if (vm.waitPhase) waitBits.push(vm.waitPhase) }
    text(r.waitNote, waitKnown ? waitBits.filter(Boolean).join(' · ') : '后端未提供 silence.hours')
    if (!waitKnown) r.waitNote.textContent = '后端未提供 silence.hours（不估算）'

    var hasV = vm.V != null
    show(r.bar, hasV)
    if (hasV) {
      var theta = vm.theta != null && vm.theta > 0 ? vm.theta : (vm.V > 0 ? vm.V : 1)
      var pct = Math.max(0, Math.min(100, Math.round((vm.V / theta) * 100)))
      r.barFill.style.width = pct + '%'
      text(r.barLabel, 'V 冲动 ' + f2(vm.V) + ' / ' + (vm.theta == null ? '阈值未提供' : f2(vm.theta)) + (vm.gate ? ' · ' + vm.gate : (vm.V >= theta ? ' · 可发送' : ' · 未达阈值')))
    }

    // 理由
    var reasonCount = 0
    r.parts.forEach(function (slot, i) {
      var item = vm.parts[i]
      show(slot.row, !!item)
      if (item) { text(slot.label, item.label); text(slot.value, item.value); reasonCount += 1 }
    })
    r.motiveRows.forEach(function (slot, i) {
      var item = vm.motiveRows[i]
      show(slot.row, !!item)
      if (item) { text(slot.label, item.label); text(slot.value, item.value); reasonCount += 1 }
    })
    show(r.reasonEmpty, reasonCount === 0)

    // 身体
    var bodyKnown = vm.energy != null || vm.sleepDebt != null || vm.circadian != null || vm.sleeping != null
    show(r.stats.energy.cell, vm.energy != null); text(r.stats.energy.value, f2(vm.energy))
    show(r.stats.sleepDebt.cell, vm.sleepDebt != null); text(r.stats.sleepDebt.value, f2(vm.sleepDebt))
    show(r.stats.circadian.cell, vm.circadian != null); text(r.stats.circadian.value, f2(vm.circadian))
    show(r.stats.fatigue.cell, vm.fatigue != null); text(r.stats.fatigue.value, f2(vm.fatigue))
    show(r.sleepRow.row, vm.sleeping != null)
    text(r.sleepRow.label, '状态')
    text(r.sleepRow.value, vm.sleeping == null ? '' : (vm.sleeping ? '睡着' : '醒着'))
    show(r.bodyEmpty, !bodyKnown)

    // 心情
    var moodKnown = vm.moodLabel != null || vm.valence != null || vm.esteem != null || vm.stress != null
    show(r.stats.mood.cell, vm.moodLabel != null); text(r.stats.mood.value, vm.moodLabel)
    show(r.stats.valence.cell, vm.valence != null); text(r.stats.valence.value, f2(vm.valence))
    show(r.stats.stress.cell, vm.stress != null); text(r.stats.stress.value, f2(vm.stress))
    show(r.stats.esteem.cell, vm.esteem != null); text(r.stats.esteem.value, f2(vm.esteem))
    show(r.moodEmpty, !moodKnown)

    // 详细
    var detail = [
      ['V / 阈值', vm.V == null ? null : (f2(vm.V) + ' / ' + (vm.theta == null ? '阈值未提供' : f2(vm.theta)))],
      ['gate', vm.gate],
      ['发送开关', vm.sendEnabled == null ? null : (vm.sendEnabled ? '开启' : '关闭')],
      ['沉默小时', vm.waitHours == null ? null : (vm.waitHours.toFixed(2) + ' h')],
      ['表达自信', null],
      ['上次说话', vm.detail.lastSeen],
      ['core.stress', vm.stress == null ? null : f2(vm.stress)],
      ['core.social', vm.social == null ? null : f2(vm.social)],
      ['allostatic', vm.detail.allostatic == null ? null : f2(vm.detail.allostatic)],
      ['homeostasis.L_int', vm.detail.Lint],
      ['数据来源', vm.preview ? '预览示例（页面桥未连接）' : 'GET page/status · autonomy.state']
    ]
    var conf = null
    if (vm.motiveRows.length) { for (var i = 0; i < vm.motiveRows.length; i += 1) if (vm.motiveRows[i].label === '表达自信') conf = vm.motiveRows[i].value }
    detail[4][1] = conf
    r.detail.forEach(function (slot, i) {
      var pair = detail[i]
      show(slot.row, pair && pair[1] != null)
      text(slot.label, pair ? pair[0] : '')
      text(slot.value, pair && pair[1] != null ? pair[1] : '')
    })

    var hint = $('nowHint')
    if (hint) {
      hint.classList.toggle('is-error', !!state.error)
      hint.textContent = state.error ? '读取失败' : (vm.preview ? '预览（未连接后端）· 结构示例' : 'page/status · 只读')
    }
  }

  function render() {
    var root = $('nowRoot')
    if (!root) return
    if (!refs) refs = build(root)
    var vm = map(state.data || {})
    show(refs.error, !!state.error)
    text(refs.error, state.error ? ('读取失败：' + state.error) : '')
    apply(refs, vm)
  }

  function refresh() {
    if (inflight) { return }
    if (document.hidden) return
    var view = $('view-now')
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
    if (!$('nowRoot')) return
    refresh()
    setInterval(refresh, POLL_MS)
    window.addEventListener('page:show', function (e) { if (e && e.detail && e.detail.id === 'now') refresh() })
    document.addEventListener('visibilitychange', function () { if (!document.hidden) refresh() })
    window.__biocoreNow = { refresh: refresh, state: state }
  }
  if (window.__Registry) {
    window.__Registry.registerPage({ id: 'now', label: '她现在', group: 'main', order: 20, icon: 'now', data: ['status'], render: function () { return document.getElementById('view-now') } })
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot)
  else boot()
})()
