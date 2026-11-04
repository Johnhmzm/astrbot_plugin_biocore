# -*- coding: utf-8 -*-
import os, tempfile, unittest
from pathlib import Path
from biocore_memory.engine import MemoryEngine
from biocore_memory.core import config as engine_config

class AffectEncodingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self._saved = {k: os.environ.get(k) for k in
                       ("BIOCORE_AFFECT_ENCODING", "BIOCORE_AFFECT_ENCODE_A", "BIOCORE_AFFECT_ENCODE_B")}
        for k in self._saved:
            os.environ.pop(k, None)

    def tearDown(self):
        self.tmp.cleanup()
        for k, v in self._saved.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v

    def remember(self, affect, **event):
        e = MemoryEngine(data_dir=str(self.dir), affect=affect)
        payload = {"text": event.pop("text", "affect encoding probe"), "role": "user"}
        payload.update(event)
        return e.remember(payload)

    def test_flag_defaults_off(self):
        self.assertIs(engine_config.FLAGS.get("affect_encoding"), False)

    def test_off_does_not_change(self):
        result = self.remember({"v": 0.8, "a": 0.8})
        self.assertAlmostEqual(result["importance"], 0.2, places=4)

    def test_high_arousal_boosts(self):
        os.environ["BIOCORE_AFFECT_ENCODING"] = "1"
        result = self.remember({"v": 0.8, "a": 0.8})
        self.assertAlmostEqual(result["importance"], 0.40, places=3)

    def test_calm_no_change(self):
        os.environ["BIOCORE_AFFECT_ENCODING"] = "1"
        result = self.remember({"v": 0.0, "a": 0.0})
        self.assertAlmostEqual(result["importance"], 0.2, places=3)

    def test_negative_valence_uses_abs(self):
        os.environ["BIOCORE_AFFECT_ENCODING"] = "1"
        result = self.remember({"v": -0.8, "a": 0.8})
        self.assertAlmostEqual(result["importance"], 0.40, places=3)

    def test_explicit_importance_wins(self):
        os.environ["BIOCORE_AFFECT_ENCODING"] = "1"
        result = self.remember({"v": 0.9, "a": 0.9}, importance=0.9)
        self.assertAlmostEqual(result["importance"], 0.9, places=4)

    def test_clamped_to_one(self):
        os.environ["BIOCORE_AFFECT_ENCODING"] = "1"
        os.environ["BIOCORE_AFFECT_ENCODE_A"] = "0.9"
        os.environ["BIOCORE_AFFECT_ENCODE_B"] = "0.9"
        result = self.remember({"v": 1.0, "a": 1.0})
        self.assertLessEqual(result["importance"], 1.0)
        self.assertGreater(result["importance"], 0.9)

    def test_no_affect_state_falls_back(self):
        os.environ["BIOCORE_AFFECT_ENCODING"] = "1"
        result = self.remember(None)
        self.assertAlmostEqual(result["importance"], 0.2, places=4)

    def test_custom_weights(self):
        os.environ["BIOCORE_AFFECT_ENCODING"] = "1"
        os.environ["BIOCORE_AFFECT_ENCODE_A"] = "0.3"
        os.environ["BIOCORE_AFFECT_ENCODE_B"] = "0.2"
        result = self.remember({"v": -0.8, "a": 0.8})
        self.assertAlmostEqual(result["importance"], 0.60, places=3)

    def test_flag_enabled_via_engine_flags(self):
        e = MemoryEngine(data_dir=str(self.dir), affect={"v": 0.8, "a": 0.8})
        e.flags["affect_encoding"] = True
        result = e.remember({"text": "flag probe", "role": "user"})
        self.assertAlmostEqual(result["importance"], 0.40, places=3)