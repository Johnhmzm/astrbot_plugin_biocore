import assert from 'node:assert'
import { TAB_STORAGE_KEYS, tabStorageKey, resolveTab, defaultTab, resolveActiveTab, safeRead, safeWrite } from '../tabs_state.mjs'

assert.equal(tabStorageKey('settings'), 'biocore_settings_tab')
assert.equal(TAB_STORAGE_KEYS.persona !== TAB_STORAGE_KEYS.session, true)
assert.equal(defaultTab(['settingsApi', 'settingsMemory'], 'settingsApi'), 'settingsApi')
assert.equal(resolveTab('settingsMemory', ['settingsApi', 'settingsMemory'], 'settingsApi'), 'settingsMemory')
assert.equal(resolveTab('bogus', ['settingsApi', 'settingsMemory'], 'settingsApi'), 'settingsApi')  // invalid -> fallback
assert.equal(resolveTab('', ['a'], null), null)
assert.equal(defaultTab([], 'settingsApi'), 'settingsApi')
// four combinations: mem present/absent x stored present/absent
const VALID = ['settingsApi', 'settingsMemory']
assert.equal(resolveActiveTab({ mem: 'settingsMemory', stored: 'settingsApi', valid: VALID, fallback: 'settingsApi' }), 'settingsMemory')  // mem wins
assert.equal(resolveActiveTab({ mem: null, stored: 'settingsMemory', valid: VALID, fallback: 'settingsApi' }), 'settingsMemory')       // stored when no mem
assert.equal(resolveActiveTab({ mem: 'settingsMemory', stored: '', valid: VALID, fallback: 'settingsApi' }), 'settingsMemory')       // mem without storage
assert.equal(resolveActiveTab({ mem: null, stored: '', valid: VALID, fallback: 'settingsApi' }), 'settingsApi')                       // default
assert.equal(resolveActiveTab({ mem: 'bogus', stored: 'settingsMemory', valid: VALID, fallback: 'settingsApi' }), 'settingsMemory')    // invalid mem ignored
// localStorage throws: mem still wins, no default fallback
const throwing = { getItem() { throw new Error('SecurityError') }, setItem() { throw new Error('SecurityError') } }
assert.equal(safeRead(throwing, 'x'), '')
assert.equal(safeWrite(throwing, 'x', 'y'), false)
const memValue = resolveActiveTab({ mem: 'settingsMemory', stored: safeRead(throwing, 'biocore_settings_tab'), valid: VALID, fallback: 'settingsApi' })
assert.equal(memValue, 'settingsMemory')  // stub throw must not fall back to default
console.log('TABS STATE OK (15 checks)')
