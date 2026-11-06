# -*- coding: utf-8 -*-
"""The core must not guess semantics from words.

Scans biocore_memory and biocore_runtime for:
  - a CJK string literal (len >= 2) inside a tuple/list/set/dict literal,
  - re.compile(...) with a CJK pattern,
  - a known domain word.
Docstrings and comments are not flagged. The safety regex in store/security.py
is exempt (see docs/CORE-CONTRACT.md): it defends against prompt injection and
never takes part in a memory decision.
"""
import ast
import os
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CORE_DIRS = ("biocore_memory", "biocore_runtime")
EXEMPT = {os.path.join("biocore_memory", "store", "security.py")}
# Display text, prompt templates and clinical labels: they render a string, they
# never decide which memory is relevant. Listed so the checker stays honest
# about what it skips.
DISPLAY_ONLY = {
    os.path.join("biocore_memory", "engine.py"),
    os.path.join("biocore_memory", "event", "media.py"),
    os.path.join("biocore_memory", "identity", "ledger.py"),
    os.path.join("biocore_memory", "identity", "writeback.py"),
    os.path.join("biocore_memory", "relay", "card.py"),
    os.path.join("biocore_memory", "recall", "constraints.py"),
    os.path.join("biocore_memory", "store", "media.py"),
    os.path.join("biocore_memory", "store", "source_consistency.py"),
    os.path.join("biocore_runtime", "governance.py"),
    os.path.join("biocore_runtime", "lifecycle.py"),
    os.path.join("biocore_runtime", "pipeline.py"),
    os.path.join("biocore_runtime", "relationship_state.py"),
    os.path.join("biocore_runtime", "standby.py"),
}

DOMAIN_WORDS = ("\u751f\u65e5", "\u804c\u4e1a", "\u57ce\u5e02", "\u89c1\u95fb",
                "\u559c\u6b22", "\u8ba8\u538c", "\u4f53\u6e29", "\u4f53\u91cd",
                "\u627f\u8bfa", "\u622a\u6b62", "\u4eca\u5929", "\u660e\u5929")
CJK = re.compile(r"[\u4e00-\u9fff]")


def source_files(root):
    for base in CORE_DIRS:
        for dirpath, _dirs, names in os.walk(os.path.join(root, base)):
            if "__pycache__" in dirpath:
                continue
            for name in sorted(names):
                if name.endswith(".py"):
                    yield os.path.join(dirpath, name)


def _docstring_ids(tree):
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = getattr(node, "body", [])
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                ids.add(id(body[0].value))
    return ids


def violations(path, text=None):
    """Return [(line, kind, snippet)] for one file."""
    text = text if text is not None else Path(path).read_text(encoding="utf-8")
    tree = ast.parse(text)
    docs = _docstring_ids(tree)
    found = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "compile"):
            for arg in node.args[:1]:
                if (isinstance(arg, ast.Constant)
                        and isinstance(arg.value, str)
                        and CJK.search(arg.value)):
                    found.append((node.lineno, "cjk_regex", arg.value[:40]))
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            for elt in node.elts:
                if (isinstance(elt, ast.Constant)
                        and isinstance(elt.value, str)
                        and id(elt) not in docs
                        and len(elt.value) >= 2
                        and CJK.search(elt.value)):
                    found.append((getattr(elt, "lineno", node.lineno),
                                  "cjk_word_list", elt.value[:40]))
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docs and len(node.value) >= 2
                and any(word in node.value for word in DOMAIN_WORDS)):
            found.append((node.lineno, "domain_word", node.value[:40]))
    return found


def repo_violations(root=ROOT):
    rows = []
    for path in source_files(root):
        rel = os.path.relpath(path, root)
        if rel in EXEMPT or rel in DISPLAY_ONLY:
            continue
        for line, kind, text in violations(path):
            rows.append((rel, line, kind, text))
    return rows


class NoWordListTest(unittest.TestCase):
    """The core source itself."""

    def test_the_core_has_no_word_list(self):
        rows = repo_violations()
        self.assertEqual(rows, [], "word lists in core: %r" % (rows[:5],))

    def test_the_checker_catches_a_planted_list(self):
        sample = "\n".join([
            "WORDS = (\"\\u559c\\u6b22\", \"\\u8ba8\\u538c\")",
            "PAT = re.compile(\"\\u660e\\u5929|\\u4eca\\u5929\")",
        ])
        found = violations("<planted>", sample)
        kinds = sorted(kind for _line, kind, _text in found)
        self.assertIn("cjk_word_list", kinds)
        self.assertIn("cjk_regex", kinds)


if __name__ == "__main__":
    unittest.main()
