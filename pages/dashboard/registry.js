/* UI-KIT · 页面注册表（pages/dashboard/registry.js）
 * 加页面 = 新增文件 + registerPage 一条；导航由 buildNav 统一生成（阶段 2 接入）。
 * 本文件不 fetch、不依赖 app.js；data 字段只声明接口名，由接入方提供 ctx.data。
 */
(function () {
  'use strict'
  if (window.__Registry) return
  var pages = []
  var ICONS = { dot: '◉', now: '◍', relation: '◎', records: '☰', persona: '◐', sessions: '▤', pipeline: '⇉', settings: '⚙', clock: '◔', list: '≡' }
  var GROUP_LABELS = { main: '现在', advanced: '高级' }

  function validate(def) {
    if (!def || !def.id || !def.label) throw new Error('registerPage: id/label required')
    if (typeof def.render !== 'function') throw new Error('registerPage: render(ctx) required: ' + def.id)
    for (var i = 0; i < pages.length; i += 1) if (pages[i].id === def.id) throw new Error('registerPage: duplicate id ' + def.id)
    return true
  }
  function registerPage(def) {
    validate(def)
    var page = {
      id: String(def.id),
      label: String(def.label),
      group: def.group === 'advanced' ? 'advanced' : 'main',
      order: Number(def.order) || 0,
      icon: String(def.icon || 'dot'),
      data: Array.isArray(def.data) ? def.data.slice() : [],
      render: def.render
    }
    pages.push(page)
    pages.sort(function (a, b) { return (a.order - b.order) || a.label.localeCompare(b.label, 'zh') })
    return page
  }
  function listPages(group) {
    return pages.filter(function (page) { return !group || page.group === group }).slice()
  }
  function iconFor(name) {
    var key = String(name || '')
    if (ICONS[key]) return ICONS[key]
    return ICONS.dot
  }
  function buildNav(opts) {
    opts = opts || {}
    var nav = opts.container || document.createElement('nav')
    if (!opts.container) nav.className = opts.className || 'nav'
    var active = String(opts.active || '')
    var onSelect = typeof opts.onSelect === 'function' ? opts.onSelect : null
    var groups = ['main', 'advanced']
    groups.forEach(function (group) {
      var rows = listPages(group)
      if (!rows.length) return
      var labelText = group === 'advanced' ? (opts.advancedLabel || GROUP_LABELS.advanced) : String(opts.mainLabel || '')
      if (labelText) nav.appendChild(el('div', 'nav-group-label', labelText))
      rows.forEach(function (page) {
        var btn = el('button', 'nav-item' + (page.id === active ? ' active' : ''))
        btn.type = 'button'
        btn.setAttribute('data-view', page.id)
        var icon = el('span', 'ni-icon', iconFor(page.icon))
        var text = el('span', null, page.label)
        btn.appendChild(icon)
        btn.appendChild(text)
        if (onSelect) btn.addEventListener('click', function () { onSelect(page.id) })
        nav.appendChild(btn)
      })
    })
    return nav
  }

  function el(tag, className, textValue) {
    var node = document.createElement(tag)
    if (className) node.className = className
    if (textValue != null) node.textContent = String(textValue)
    return node
  }

  window.__Registry = { registerPage: registerPage, listPages: listPages, buildNav: buildNav, iconFor: iconFor }
})()
