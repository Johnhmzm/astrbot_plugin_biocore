/* UI-KIT · 组件层（pages/dashboard/ui_kit.js）
 * 设计令牌见 docs/UI-KIT.md；所有页面共用这一份组件，页面只组合、不重复写 DOM/样式。
 * 组件：Panel / Row / Switch / Bar / Stat / Badge
 * 约定：返回原生 DOM；className 可追加布局钩子；不 fetch、不读全局状态。
 */
(function () {
  'use strict'
  if (window.UIKit) return
  var K = {}

  function el(tag, className, textValue) {
    var node = document.createElement(tag)
    if (className) node.className = className
    if (textValue != null) node.textContent = String(textValue)
    return node
  }
  function mergeClass(base, extra) { return extra ? base + ' ' + extra : base }
  function mount(parent, child) {
    if (child == null || child === false) return parent
    if (Array.isArray(child)) { child.forEach(function (item) { mount(parent, item) }); return parent }
    if (child instanceof Node) { parent.appendChild(child); return parent }
    parent.appendChild(document.createTextNode(String(child)))
    return parent
  }
  function toneClass(tone) { return tone ? 'tone-' + String(tone) : '' }

  K.Panel = function (opts) {
    opts = opts || {}
    var root = opts.fold ? el('details', mergeClass('kit-panel', opts.className)) : el('section', mergeClass('kit-panel', opts.className))
    if (opts.fold) root.open = opts.open === true
    var head = opts.fold ? el('summary', 'kit-panel-head') : el('div', 'kit-panel-head')
    var title = el('div', 'kit-panel-title')
    title.appendChild(el('b', null, opts.title || ''))
    if (opts.hint) title.appendChild(el('small', null, opts.hint))
    head.appendChild(title)
    if (opts.onClose) {
      var close = el('button', 'kit-panel-close', opts.closeText || '收起')
      close.type = 'button'
      close.addEventListener('click', opts.onClose)
      head.appendChild(close)
    }
    root.appendChild(head)
    if (!opts.fold) {
      var body = el('div', 'kit-panel-body')
      mount(body, opts.children)
      root.appendChild(body)
    } else if (opts.children) {
      var body2 = el('div', 'kit-panel-body')
      mount(body2, opts.children)
      root.appendChild(body2)
    }
    return root
  }

  K.Row = function (opts) {
    opts = opts || {}
    var row = el('div', mergeClass('kit-row', (opts.disabled ? 'is-disabled ' : '') + (opts.className || '')))
    var main = el('div', 'kit-row-main')
    main.appendChild(el('b', null, opts.label || ''))
    if (opts.note) main.appendChild(el('small', null, opts.note))
    row.appendChild(main)
    var side = el('div', 'kit-row-side')
    if (opts.value != null) {
      if (opts.value instanceof Node) side.appendChild(opts.value)
      else side.appendChild(el('span', 'kit-row-value', opts.value))
    }
    if (opts.control) mount(side, opts.control)
    row.appendChild(side)
    return row
  }

  K.Switch = function (opts) {
    opts = opts || {}
    var label = el('label', mergeClass('kit-switch', (opts.disabled ? 'is-disabled ' : '') + (opts.className || '')))
    var input = el('input')
    input.type = 'checkbox'
    input.checked = !!opts.checked
    input.disabled = !!opts.disabled
    if (opts.inputAttrs) Object.keys(opts.inputAttrs).forEach(function (key) { input.setAttribute(key, opts.inputAttrs[key]) })
    if (opts.onChange) input.addEventListener('change', function () { opts.onChange(input.checked) })
    label.appendChild(input)
    label.appendChild(el('span'))
    return label
  }

  K.Bar = function (opts) {
    opts = opts || {}
    var max = Number(opts.max)
    if (!isFinite(max) || max <= 0) max = 1
    var value = Number(opts.value)
    if (!isFinite(value)) value = 0
    var pct = Math.max(0, Math.min(100, Math.round((value / max) * 100)))
    var bar = el('div', mergeClass('kit-bar', (opts.tone ? 'tone-' + opts.tone : '') + ' ' + (opts.className || '')))
    var track = el('div', 'kit-bar-track')
    var fill = el('i')
    fill.style.width = pct + '%'
    track.appendChild(fill)
    bar.appendChild(track)
    if (opts.label) bar.appendChild(el('small', 'kit-bar-label', opts.label))
    return bar
  }

  K.Stat = function (opts) {
    opts = opts || {}
    var stat = el('div', mergeClass('kit-stat', opts.className))
    stat.appendChild(el('small', 'kit-stat-label', opts.label || ''))
    var line = el('span', 'kit-stat-value', opts.value == null ? '—' : opts.value)
    if (opts.unit) line.appendChild(el('em', null, opts.unit))
    stat.appendChild(line)
    if (opts.delta) stat.appendChild(el('em', mergeClass('kit-stat-delta', opts.delta > 0 ? 'is-up' : 'is-down'), (opts.delta > 0 ? '+' : '') + opts.delta))
    return stat
  }

  K.Badge = function (opts) {
    opts = opts || {}
    return el('span', mergeClass('kit-badge', (toneClass(opts.tone) + ' ' + (opts.className || '')).trim()), opts.text == null ? '' : opts.text)
  }

  K.Empty = function (opts) {
    opts = opts || {}
    var box = el('div', mergeClass('kit-empty', opts.className))
    box.appendChild(el('p', 'kit-empty-text', opts.text || '暂无数据'))
    if (opts.action && typeof opts.onAction === 'function') {
      var btn = el('button', 'kit-empty-action', opts.action)
      btn.type = 'button'
      btn.addEventListener('click', opts.onAction)
      box.appendChild(btn)
    }
    return box
  }

  K.el = el
  K.mount = mount
  window.UIKit = K
  if (typeof module !== 'undefined' && module.exports) module.exports = K
})()
