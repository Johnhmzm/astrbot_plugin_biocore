(function () {
  'use strict'
  if (window.__ui3GraphInstalled) return
  window.__ui3GraphInstalled = true
  var API = 'page/graph'
  var POLL_MS = 15000
  var state = { data: null, selected: '', ready: false, error: '', preview: false }

  function $(id) { return document.getElementById(id) }
  function esc(value) { return String(value == null ? '' : value).replace(/[&<>"']/g, function (ch) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch] }) }
  function when(ts) { var n = Number(ts); if (!n) return '—'; try { return new Date(n * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) } catch (e) { return '—' } }
  function pageBridge() {
    var b = window.AstrBotPluginView || window.AstrBotPluginPage || window.astrbotPluginView || null
    if (!b) { try { if (window.parent && window.parent !== window) b = window.parent.AstrBotPluginView || window.parent.AstrBotPluginPage || null } catch (e) { b = null } }
    return b
  }
  function unwrap(raw) { if (!raw || typeof raw !== 'object') return {}; return raw.data && typeof raw.data === 'object' ? raw.data : raw }

  function skeleton() {
    return '<div class="section-title"><div><div class="eyebrow">GRAPH</div><h2>记忆图谱</h2></div><span class="hint" id="graphHint">读取中…</span></div>' +
      '<div class="signal-grid" id="graphStats"></div>' +
      '<div class="panel dsh-mem-panel" style="margin-top:12px"><div class="panel-head"><h3>实体</h3><span class="hint">点击查看关联条目 / 时间线</span></div><div class="dsh-mem-list" id="graphEntityList"></div></div>' +
      '<div class="panel dsh-mem-panel" style="margin-top:12px"><div class="panel-head"><h3>关联条目与时间线</h3><span class="hint" id="graphDetailTitle">—</span></div><div id="graphDetail"></div></div>'
  }
  function ensureRoot() {
    var view = $('view-graph')
    if (!view) return null
    if (!view.getAttribute('data-graph-ready')) { view.innerHTML = skeleton(); view.setAttribute('data-graph-ready', '1') }
    return view
  }
  function entities() { return (state.data && Array.isArray(state.data.entities)) ? state.data.entities : [] }
  function edges() { return (state.data && Array.isArray(state.data.edges)) ? state.data.edges : [] }
  function selectedEntity() {
    var list = entities()
    for (var i = 0; i < list.length; i += 1) if (String(list[i].name) === String(state.selected)) return list[i]
    return list.length ? list[0] : null
  }
  function relatedEdges(name) {
    return edges().filter(function (edge) { return String(edge.src_name) === String(name) || String(edge.dst_name) === String(name) })
  }
  function statCell(label, value) { return '<div><small>' + esc(label) + '</small><b>' + esc(value) + '</b></div>' }
  function renderStats() {
    var host = $('graphStats')
    if (!host) return
    var stats = (state.data && state.data.stats) || {}
    host.innerHTML = statCell('实体', stats.entities == null ? entities().length : stats.entities) +
      statCell('关系边', stats.edges == null ? edges().length : stats.edges) +
      statCell('别名', stats.aliases == null ? '—' : stats.aliases) +
      statCell('最近更新', when(stats.latest_ts))
  }
  function renderList() {
    var host = $('graphEntityList')
    if (!host) return
    var list = entities()
    if (!list.length) { host.innerHTML = '<div class="dsh-mem-empty">图里还没有实体：先聊几句，或检查图库是否已建。</div>'; return }
    host.innerHTML = list.map(function (row) {
      var active = selectedEntity() && String(selectedEntity().name) === String(row.name)
      var alias = (row.aliases || []).length ? (' · ' + esc(row.aliases.slice(0, 3).join('/'))) : ''
      return '<div class="dsh-mem-row" data-graph-entity="' + esc(row.name) + '" style="cursor:pointer;' + (active ? 'border-left:2px solid #ff6b00;padding-left:6px;' : '') + '">' +
        '<div class="dsh-mem-text">' + esc(row.name) + '<span class="chip" style="margin-left:6px">' + esc(row.type_label || row.type || '话题') + '</span>' + alias + '</div>' +
        '<div class="dsh-mem-meta"><span>关系 ' + relatedEdges(row.name).length + '</span><span>' + esc(when(row.last_seen)) + '</span></div></div>'
    }).join('')
    Array.prototype.forEach.call(host.querySelectorAll('[data-graph-entity]'), function (node) {
      node.addEventListener('click', function () { state.selected = node.getAttribute('data-graph-entity'); render() })
    })
  }
  function renderDetail() {
    var entity = selectedEntity()
    var host = $('graphDetail')
    var title = $('graphDetailTitle')
    if (!host) return
    if (!entity) { host.innerHTML = '<div class="dsh-mem-empty">先选择左侧实体。</div>'; if (title) title.textContent = '—'; return }
    if (title) title.textContent = entity.name + ' · ' + (entity.aliases || []).join('/')
    var rows = relatedEdges(entity.name)
    var related = []
    rows.forEach(function (edge) { if (edge.source_entry && related.indexOf(edge.source_entry) < 0) related.push(edge.source_entry) })
    var edgeHtml = rows.length ? rows.map(function (edge) {
      return '<div class="dsh-mem-row"><div class="dsh-mem-text">' + esc(edge.src_name) + ' —' + esc(edge.rel_label || edge.rel) + '→ ' + esc(edge.dst_name) + '</div>' +
        '<div class="dsh-mem-meta"><span>' + esc(when(edge.ts)) + '</span><span>conf ' + Number(edge.confidence || 0).toFixed(2) + '</span><span>' + esc(edge.source_entry || '') + '</span></div></div>'
    }).join('') : '<div class="dsh-mem-empty">这个实体还没有关系边。</div>'
    host.innerHTML = '<div class="section-title" style="margin-top:6px"><div><div class="eyebrow">TIMELINE</div><h2>时间线</h2></div><span class="hint">' + esc(entity.type_label || '话题') + '</span></div>' + edgeHtml +
      '<p class="api-note">关联条目：' + (related.length ? esc(related.slice(0, 8).join('、')) : '—') + '</p>'
  }
  function render() {
    var hint = $('graphHint')
    if (hint) hint.textContent = state.error ? ('读取失败：' + state.error) : (state.preview ? '示例数据' : ('实体 ' + entities().length + ' · 关系 ' + edges().length + (state.ready ? '' : ' · 读取中')))
    renderStats()
    renderList()
    renderDetail()
  }
  function refresh() {
    ensureRoot()
    if (document.hidden) return
    var bridge = pageBridge()
    if (!bridge) {
      var demo = window.__biocoreGraphData
      if (!demo) { setTimeout(refresh, 800); return }
      state.data = demo; state.preview = true; state.ready = true; state.error = ''; render(); return
    }
    Promise.resolve(bridge.apiGet(API, {})).then(function (raw) {
      var data = unwrap(raw)
      if (data && data.ok === false) throw new Error(data.message || data.error || 'page/graph 返回 ok=false')
      state.data = data || {}; state.preview = false; state.ready = true; state.error = String((data && data.error) || ''); render()
    }).catch(function (error) { state.error = String((error && error.message) || error); state.ready = true; render() })
  }
  function boot() {
    if (!$('view-graph')) return
    ensureRoot()
    refresh()
    setInterval(refresh, POLL_MS)
    window.addEventListener('page:show', function (event) { if (event && event.detail && event.detail.id === 'graph') refresh() })
    document.addEventListener('visibilitychange', function () { if (!document.hidden) refresh() })
    window.__biocoreGraph = { refresh: refresh, state: state }
  }
  if (window.__Registry) {
    window.__Registry.registerPage({
      id: 'graph', label: '记忆图谱', group: 'advanced', order: 85, icon: 'relation',
      data: ['page/graph'],
      render: function () { ensureRoot(); return document.getElementById('view-graph') }
    })
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot)
  else boot()
})()
