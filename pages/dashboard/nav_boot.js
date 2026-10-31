/* UI-KIT · 导航启动（pages/dashboard/nav_boot.js）
 * 阶段 2：三页通过 registry.registerPage 注册；本文件补齐 legacy 页面注册，
 * 并用 registry.buildNav 生成左栏导航（不再手写 nav 项）。选中页仍复用现有 #view-* 区块。
 */
(function () {
  'use strict'
  if (window.__NavBootInstalled) return
  window.__NavBootInstalled = true

  var LEGACY = [
    { id: 'overview', label: '情绪概览', order: 10, icon: 'dot' },
    { id: 'persona', label: '人格自我', order: 30, icon: 'persona' },
    { id: 'sessions', label: '活动会话', order: 40, icon: 'sessions' },
    { id: 'pipeline', label: '流水线', order: 60, icon: 'pipeline' },
    { id: 'intent', label: '表达意图', group: 'advanced', order: 80, icon: 'intent' },
    { id: 'settings', label: '设置', group: 'advanced', order: 90, icon: 'settings' }
  ]

  function hasPage(id) {
    var R = window.__Registry
    if (!R) return false
    return R.listPages().some(function (page) { return page.id === id })
  }
  function registerLegacy() {
    var R = window.__Registry
    if (!R) return
    LEGACY.forEach(function (def) {
      if (hasPage(def.id)) return
      R.registerPage({
        id: def.id, label: def.label, group: def.group || 'main',
        order: def.order, icon: def.icon, data: [],
        render: function () { return document.getElementById('view-' + def.id) }
      })
    })
  }
  function findPage(id) {
    var found = null
    var R = window.__Registry
    if (R) R.listPages().forEach(function (page) { if (page.id === id) found = page })
    return found
  }
  function currentView() {
    var view = document.querySelector('.view.active')
    if (view && view.id.indexOf('view-') === 0) return view.id.slice(5)
    try { return String(new URLSearchParams(location.search).get('view') || '') } catch (e) { return '' }
  }
  function showPage(id) {
    var page = findPage(id)
    if (!page) return
    Array.prototype.forEach.call(document.querySelectorAll('.nav-item'), function (item) {
      item.classList.toggle('active', item.getAttribute('data-view') === id)
    })
    Array.prototype.forEach.call(document.querySelectorAll('.view'), function (view) {
      view.classList.toggle('active', view.id === 'view-' + id)
    })
    var crumb = document.getElementById('crumbView')
    if (crumb) crumb.textContent = page.label
    try { window.dispatchEvent(new CustomEvent('page:show', { detail: { id: id } })) } catch (e) {}
  }
  function boot() {
    var R = window.__Registry
    if (!R) return
    registerLegacy()
    var host = document.querySelector('.nav')
    var active = currentView()
    if (host) {
      host.innerHTML = ''
      R.buildNav({ container: host, active: active, onSelect: showPage })
    }
    if (active) showPage(active)
    window.__Nav = { showPage: showPage, currentView: currentView }
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { setTimeout(boot, 0) })
  else setTimeout(boot, 0)
})()
