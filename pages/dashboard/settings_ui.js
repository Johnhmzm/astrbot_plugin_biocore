/* UI-KIT · 设置收拢（pages/dashboard/settings_ui.js）
 * 目标：把「表达意图 → 自主行为」现有的 8 个设置项收成 5 个常用项，其余进「高级」折叠。
 * 做法：不改 app.js（模板与保存逻辑都在 app.js），在面板注入后对其 DOM 重排：
 *   - 常用 5 项：启用 / 黏人三档 / 敏感度三档 / 每日上限 / 阈值
 *   - 高级：允许真正发送 / 依恋风格 / 最大字数（三层映射说明）
 * 旧控件保留在 DOM（隐藏或移入高级），保存按钮仍按原 id 读取，行为不变。
 */
(function () {
  'use strict'
  if (window.__SettingsUiInstalled) return
  window.__SettingsUiInstalled = true
  var K = window.UIKit
  if (!K) return

  var RT = 2000
  var installed = false
  var refs = {}
  var FLAG_LEVELS = [
    { value: 'off', text: '不黏' },
    { value: 'on', text: '默认' },
    { value: 'anxious', text: '黏人（焦虑依恋）' }
  ]
  var RS_LEVELS = [
    { value: '0.2', text: '低（0.2）' },
    { value: '0.4', text: '中（0.4）' },
    { value: '0.7', text: '高（0.7）' }
  ]

  function $(id) { return document.getElementById(id) }
  function rowOf(el) { var n = el; while (n && !(n.classList && n.classList.contains('setting-row'))) n = n.parentNode; return n }
  function select(options) {
    var el = document.createElement('select')
    el.className = 'kit-select'
    options.forEach(function (opt) { var o = document.createElement('option'); o.value = opt.value; o.textContent = opt.text; el.appendChild(o) })
    return el
  }
  function numberInput(step, min, max) {
    var el = document.createElement('input')
    el.type = 'number'; el.className = 'kit-input'; el.step = String(step || 1)
    if (min != null) el.min = String(min); if (max != null) el.max = String(max)
    return el
  }

  function install() {
    var host = $('intentAutonomyHost')
    if (!host || installed) return
    var container = host.querySelector('.panel.settings')
    if (!container) return
    var els = {
      enabled: $('autonomyEnabled'), send: $('autonomySend'), clingy: $('autonomyClingy'),
      attach: $('autonomyAttachment'), rs: $('autonomyRS'), thr: $('autonomyThresholdInput'), chars: $('autonomyMaxCharsInput')
    }
    if (!els.enabled || !els.thr) return
    installed = true
    var rows = {}
    Object.keys(els).forEach(function (key) { if (els[key]) rows[key] = rowOf(els[key]) })

    // 1) 常用 5 项（新增的每日上限 + 两个三档控件）
    var capInput = numberInput(1, 1, 20); capInput.id = 'autonomyDailyCap'
    var flagSel = select(FLAG_LEVELS)
    var rsSel = select(RS_LEVELS)
    var thrInput = numberInput(0.05, 0, 1)
    var enabledRow = K.Row({
      label: '启用自主主动发消息', note: '总开关；关闭时不做任何主动行为',
      control: K.Switch({ checked: !!els.enabled.checked, onChange: function (on) { els.enabled.checked = !!on } })
    })
    var flagRow = K.Row({ label: '黏人三档', note: '不黏 / 默认 / 黏人（焦虑依恋）', control: flagSel })
    var rsRow = K.Row({ label: '敏感度三档', note: '拒绝敏感性；越高越容易自责', control: rsSel })
    var capRow = K.Row({ label: '每日上限', note: '1–20 次（每小时额度按上限/3 向上取整）', control: capInput })
    var thrRow = K.Row({ label: '阈值', note: '0–1；越高越难触发', control: thrInput })
    var basic = K.Panel({ title: '自主行为 · 常用', hint: '5 项；其余在「高级」', children: [enabledRow, flagRow, rsRow, capRow, thrRow] })
    container.parentNode.insertBefore(basic, container)

    // 2) 高级：发送 / 依恋 / 字数 + 三层映射说明
    var advChildren = []
    ;['send', 'attach', 'chars'].forEach(function (key) {
      if (rows[key]) advChildren.push(rows[key])
    })
    advChildren.push(K.el('p', 'kit-note', '阈值三档/黏人三档是本地映射：后端只有 clingy 布尔与拒绝敏感性数值；「黏人」档同时把依恋设为焦虑型。'))
    var advanced = K.Panel({ fold: true, title: '高级', hint: '发送 / 依恋 / 字数', children: advChildren })
    host.insertBefore(advanced, container.nextSibling)

    // 3) 隐藏被替换掉的 4 个旧行（启用/黏人/敏感度/阈值）
    ;['enabled', 'clingy', 'rs', 'thr'].forEach(function (key) {
      if (rows[key]) rows[key].style.display = 'none'
    })

    // 4) 双向同步（旧 id 仍供 app.js 保存按钮读取）
    function syncFromLegacy() {
      thrInput.value = els.thr.value || ''
      if (els.rs) {
        var rv = Number(els.rs.value)
        rsSel.value = rv <= 0.3 ? '0.2' : (rv >= 0.6 ? '0.7' : '0.4')
      }
      if (els.clingy) flagSel.value = !els.clingy.checked ? 'off' : ((els.attach && els.attach.value === 'anxious') ? 'anxious' : 'on')
      if (capInput.value === '') capInput.value = '5'
    }
    flagSel.addEventListener('change', function () {
      var level = flagSel.value
      if (els.clingy) els.clingy.checked = level !== 'off'
      if (level === 'anxious' && els.attach) els.attach.value = 'anxious'
    })
    rsSel.addEventListener('change', function () { if (els.rs) els.rs.value = rsSel.value })
    capInput.addEventListener('change', function () {
      var n = Math.max(1, Math.min(20, parseInt(capInput.value, 10) || 5))
      capInput.value = String(n)
      if (!$( 'autonomyDailyCap')) capInput.id = 'autonomyDailyCap'
    })
    thrInput.addEventListener('change', function () {
      var n = Math.max(0, Math.min(1, Number(thrInput.value) || 0.55))
      thrInput.value = String(n)
      els.thr.value = String(n)
    })
    syncFromLegacy()
    refs = { flagSel: flagSel, rsSel: rsSel, capInput: capInput, thrInput: thrInput, els: els }
    setInterval(syncFromLegacy, RT)
  }

  function boot() {
    var host = $('intentAutonomyHost')
    if (!host) return
    var observer = new MutationObserver(function () { install() })
    observer.observe(host, { childList: true, subtree: true })
    install()
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot)
  else boot()
})()
