# -*- coding: utf-8 -*-
import sys
sys.path.insert(0, '.')
from biocore_model import autonomy_model as am

def simulate_ticks(drift, theta=0.55, leak=0.15, sigma=0.0, max_ticks=100):
    V = 0.0
    for tick in range(1, max_ticks + 1):
        out = am.step(V, drift, leak, sigma, theta)
        V = out['V']
        if out['fire']:
            return tick
    return None

parts = {k: 0.0 for k in am.DRIFT_WEIGHTS}
parts['anxiety_fear'] = 0.8
drift_anxiety = am.drift_value(parts)
t1_tick = simulate_ticks(drift_anxiety)
print('T1 anxiety-only drift=%.3f ticks=%s -> %s' % (drift_anxiety, t1_tick, 'PASS' if t1_tick and 6 <= t1_tick <= 12 else 'FAIL'))

delta = am.silence_nudges(6, 'protest', 0.8)
print('T2 6h silence valence=%.3f -> %s' % (delta['valence'], 'PASS' if abs(delta['valence']) >= 0.10 else 'FAIL'))

acc = {}
for _ in range(5):
    out = am.block_feedback(acc, 1_700_000_000)
    acc = out['acc']
print('T3 after 5 blocked drive_mult=%.2f -> %s' % (acc['drive_mult'], 'PASS' if acc['drive_mult'] >= 1.20 else 'FAIL'))

baseline = am.drift_value({k: 0.05 for k in am.DRIFT_WEIGHTS})
v_inf = baseline / 0.15
print('T4 baseline drift=%.3f Vinf=%.3f ratio=%.2f -> %s' % (baseline, v_inf, v_inf / 0.55, 'PASS' if v_inf <= 0.8 * 0.55 else 'FAIL'))
parts8 = {k: 0.0 for k in am.DRIFT_WEIGHTS}
parts8['memory_due'] = 1.0
parts8['social_gap'] = 0.0
t8 = simulate_ticks(am.drift_value(parts8))
print('T8 memory_due-only drift=%.3f ticks=%s -> %s' % (am.drift_value(parts8), t8, 'PASS' if t8 and t8 <= 12 else 'FAIL'))

parts9 = {k: 0.0 for k in am.DRIFT_WEIGHTS}
parts9['guilt'] = 1.0; parts9['gratitude'] = 1.0
t9 = simulate_ticks(am.drift_value(parts9))
print('T9 guilt+gratitude drift=%.3f ticks=%s -> %s' % (am.drift_value(parts9), t9, 'PASS' if t9 is None or t9 > 12 else 'FAIL'))

print('T5 social_gap24=%.3f' % am.social_gap(24, 18, 0.7, 0.5))
print('T6 self_blame24=%.3f' % am.self_blame_value(24, 0.4, 'secure'))
print('T7 confidence_blame07=%.3f' % am.blame_effects(0.7)['confidence'])
print('weights_sum=%.4f' % sum(am.DRIFT_WEIGHTS.values()))

from biocore_model import relationship_stage as _rs
_t10 = [(h, _rs.stage_for(h)) for h in (9.9, 10, 50, 55, 90, 91)]
print('T10 stage boundaries %s -> %s' % (_t10, 'PASS' if _t10[1][1] == 'acquaintance' and _t10[3][1] == 'friend' and _t10[5][1] == 'close' else 'FAIL'))
_t11 = {name: _rs.stage_config(h)['tau_hours'] for name, h in (('stranger', 0), ('acquaintance', 20), ('friend', 60), ('close', 100))}
print('T11 stage tau %s -> %s' % (_t11, 'PASS' if _t11['friend'] == 24 and _t11['close'] == 36 else 'FAIL'))
