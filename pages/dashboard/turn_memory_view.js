/* P0-3 本轮记忆可见 · pages/dashboard/turn_memory_view.js
 * 纯函数：把 GET page/status 的 turn_memory 收据（task-124）投影成面板行。
 * 不碰 DOM、不发请求；app.js 只负责把这些行拼成只读卡片。
 * 数据形状（后端 biocore_model/turn_memory.py build_record）：
 *   {ts, reply, count, rows:[{rank,id,text,source,tier,score,reason}]}
 */
(function (root) {
  'use strict'
  var MAX_ROWS = 4
  var MAX_TEXT = 160

  function text(value, limit) {
    var flat = String(value == null ? '' : value).replace(/\s+/g, ' ').trim()
    if (flat.length <= limit) return flat
    return flat.slice(0, limit).replace(/\s+$/, '') + '…'
  }

  function num(value, fallback) {
    var n = Number(value)
    return (value === null || value === undefined || value === '' || !isFinite(n))
      ? fallback : n
  }

  function capOf(limit) {
    var n = Math.floor(num(limit, MAX_ROWS))
    if (n <= 0) return 0
    return Math.min(n, MAX_ROWS)
  }

  function rows(record, limit) {
    var cap = capOf(limit)
    var out = []
    if (!cap) return out
    var src = (record && typeof record === 'object') ? record : {}
    var list = Array.isArray(src.rows) ? src.rows : []
    for (var i = 0; i < list.length; i++) {
      var row = (list[i] && typeof list[i] === 'object') ? list[i] : {}
      var id = text(row.id, 24)
      var body = text(row.text, MAX_TEXT)
      if (!id && !body) continue
      out.push({
        rank: Math.round(num(row.rank, out.length + 1)),
        id: id,
        text: body || id,
        source: text(row.source, 16) || 'unknown',
        tier: text(row.tier, 8),
        score: Math.round(num(row.score, 0) * 10000) / 10000,
        reason: text(row.reason, 60) || '规则打分'
      })
      if (out.length >= cap) break
    }
    return out
  }

  function summary(record) {
    var picked = rows(record, MAX_ROWS)
    var src = (record && typeof record === 'object') ? record : {}
    var total = Math.round(num(src.count, picked.length))
    return {
      count: picked.length,
      total: total > 0 ? total : picked.length,
      ts: num(src.ts, 0),
      reply: text(src.reply, 120),
      rows: picked
    }
  }

  root.BioTurnMemoryView = {
    MAX_ROWS: MAX_ROWS,
    rows: rows,
    summary: summary
  }
})(typeof window !== 'undefined' ? window : globalThis)
