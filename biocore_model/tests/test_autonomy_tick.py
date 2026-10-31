# -*- coding: utf-8 -*-
import unittest
from biocore_model import autonomy_tick as at

NOW = 1_700_000_000

class FakeCore:
    def snapshot(self): return {}

class Deps:
    def __init__(self, **kw):
        self.acc = kw.get('acc', {})
        self.sessions = kw.get('sessions', [{'umo': 'u1'}])
        self.snapshot_value = kw.get('snapshot_value', {})
        self.step_result = kw.get('step_result', {'V': 0.0, 'fire': False})
        self.gate_result = kw.get('gate_result', (True, 'fired'))
        self.any_core_value = kw.get('any_core', FakeCore())
        self.sent = []
    def load_acc(self): return dict(self.acc)
    def save_acc(self, acc): self.acc = dict(acc)
    def list_sessions(self): return list(self.sessions)
    def get_core(self, umo): return FakeCore()
    def any_core(self): return self.any_core_value
    def snapshot(self, core): return dict(self.snapshot_value)
    def step(self, V, drift, theta): return dict(self.step_result)
    def gate(self, core, acc, silence, now): return self.gate_result
    def send_text(self, umo, text): self.sent.append(umo); return True
    def build_text(self, core, acc): return '在。'

class TickTest(unittest.TestCase):
    def test_window_skip_when_sleeping(self):
        ok, reason = at._check_window({}, NOW, {'sleep': {'sleeping': True}})
        self.assertFalse(ok); self.assertEqual(reason, 'sleeping')
    def test_window_allows_awake(self):
        self.assertTrue(at._check_window({}, NOW, {'sleep': {'sleeping': False}})[0])
    def test_silence_hours(self):
        self.assertAlmostEqual(at._compute_silence({'last_user_msg_ts': NOW - 7200}, NOW)['hours'], 2.0)
    def test_motive_drift_positive(self):
        self.assertGreater(at._compute_motive({}, {'social_gap': 0.5})['drift'], 0)
    def test_decide_sleep_skip(self):
        self.assertEqual(at._decide({}, FakeCore(), NOW, {'sleep': {'sleeping': True}})['action'], 'skip')
    def test_decide_awake_send(self):
        self.assertEqual(at._decide({}, FakeCore(), NOW, {})['action'], 'send')
    def test_tick_no_fire_skips(self):
        deps = Deps(step_result={'V': 0.2, 'fire': False})
        out = at.tick_once(deps, NOW)
        self.assertEqual(out['sent'], []); self.assertEqual(out['skipped'], ['u1'])
    def test_tick_fire_sends(self):
        deps = Deps(step_result={'V': 0.0, 'fire': True})
        out = at.tick_once(deps, NOW)
        self.assertEqual(out['sent'], ['u1']); self.assertEqual(deps.sent, ['u1'])
    def test_tick_gate_blocks(self):
        deps = Deps(step_result={'V': 0.0, 'fire': True}, gate_result=(False, 'cooldown'))
        out = at.tick_once(deps, NOW)
        self.assertEqual(out['blocked'], ['u1']); self.assertEqual(out['reason'], 'cooldown')
    def test_tick_records_last_tick(self):
        deps = Deps(step_result={'V': 0.0, 'fire': False})
        at.tick_once(deps, NOW)
        self.assertEqual(deps.acc['last_tick_ts'], NOW)
    def test_no_session_still_advances_v(self):
        deps = Deps(sessions=[])
        deps.acc = {"V": 0.1, "theta": 0.55, "leak": 0.15}
        deps.step = lambda V, drift, theta: {"V": V + 0.01, "fire": False}
        values = []
        for index in range(5):
            at.tick_once(deps, NOW + index)
            values.append(deps.acc["V"])
        for index, expected in enumerate([0.11, 0.12, 0.13, 0.14, 0.15]):
            self.assertAlmostEqual(values[index], expected)
        self.assertEqual(deps.acc.get("last_tick_ts"), NOW + 4)

    def test_no_session_reason_is_no_session(self):
        deps = Deps(sessions=[])
        deps.acc = {"V": 0.1, "theta": 0.55}
        deps.step = lambda V, drift, theta: {"V": V + 0.01, "fire": False}
        out = at.tick_once(deps, NOW)
        self.assertEqual(out["reason"], "no_session")

    def test_sleeping_still_steps_with_session(self):
        deps = Deps(sessions=[{"umo": "u1"}],
                    snapshot_value={"sleep": {"sleeping": True}})
        deps.acc = {"V": 0.0, "theta": 0.55}
        deps.step = lambda V, drift, theta: {"V": V + 0.01, "fire": False}
        out = at.tick_once(deps, NOW)
        self.assertAlmostEqual(deps.acc["V"], 0.01)
        self.assertEqual(out["reason"], "sleeping")
        self.assertEqual(out["sent"], [])

    def test_any_core_parts_feed_drift_without_session(self):
        drifts = []
        deps = Deps(sessions=[], snapshot_value={"parts": {"social_gap": 0.5}})
        deps.acc = {"V": 0.0, "theta": 0.55}
        deps.step = lambda V, drift, theta: (drifts.append(drift)
                                              or {"V": V, "fire": False})
        at.tick_once(deps, NOW)
        self.assertTrue(drifts and drifts[0] > 0.0)

    def test_main_has_no_session_guard(self):
        import pathlib
        source = pathlib.Path(__file__).resolve().parents[2].joinpath("main.py").read_text(encoding="utf-8")
        self.assertNotIn("no private session, skipped", source)
        self.assertIn("deps.any_core", source)
        self.assertIn("no session; V still advances", source)
        self.assertIn('payload.setdefault("last_umo"', source)

    def test_no_main_import(self):
        import pathlib
        source = pathlib.Path(__file__).resolve().parent.parent.joinpath('autonomy_tick.py').read_text(encoding='utf-8')
        self.assertNotIn('import main', source); self.assertNotIn('from main', source)

if __name__ == '__main__':
    unittest.main()
