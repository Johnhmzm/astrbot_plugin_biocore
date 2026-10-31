import assert from 'node:assert'
import { migrateStorage, resolvePersonaId, OLD_SWITCH_MAP, UI_SCHEMA, UI_SCHEMA_KEY } from '../ui_compat.mjs'
const store = () => { const m = new Map(); return { m, read: (k) => (m.has(k) ? m.get(k) : null), write: (k, v) => m.set(k, String(v)) } }
// old localStorage keys copied to new, keeping old keys
let s = store(); s.write('biocore_settings_tab', 'settingsMemory'); s.write('biocore_settings_view', 'settings')
let r = migrateStorage(s.read, s.write)
assert.equal(r.migrated, true); assert.equal(s.read('biocore_settings_tab'), 'settingsMemory'); assert.equal(s.read(UI_SCHEMA_KEY), String(UI_SCHEMA))
// merged switch: only true migrates
s = store(); s.write('bio_feat_swShowNodes', '1'); s.write('bio_feat_swShowLinks', '0')
r = migrateStorage(s.read, s.write)
assert.equal(s.read('bio_feat_feat_visual_nodes'), '1')
assert.notEqual(s.read('bio_feat_feat_visual_links'), '1')
assert.equal(OLD_SWITCH_MAP.swShowNodes, 'feat_visual_nodes')
// second run is a no-op
const before = JSON.stringify([...s.m]); r = migrateStorage(s.read, s.write)
assert.equal(r.migrated, false); assert.equal(JSON.stringify([...s.m]), before)
// persona resolution: never render a bare default placeholder when others exist
assert.equal(resolvePersonaId([{ id: 'default' }, { id: 'x' }], ''), 'x')
assert.equal(resolvePersonaId([{ id: 'default' }], ''), '')  // never render a bare default placeholder
assert.equal(resolvePersonaId([], '', 'legacy.txt'), 'legacy.txt')
assert.equal(resolvePersonaId([{ id: 'a' }, { id: 'b' }], 'b'), 'b')
console.log('UI COMPAT OK (10 checks)')
