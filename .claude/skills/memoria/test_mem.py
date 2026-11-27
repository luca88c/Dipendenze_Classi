"""Test per mem.py. Esegui: python3 -m unittest discover -s .claude/skills/memoria"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import mem  # noqa: E402


class MemTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["MEMORIA_DIR"] = self.tmp.name
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        os.environ.pop("MEMORIA_DIR", None)
        self.tmp.cleanup()

    def obs(self, **kw):
        base = {"type": "decision", "title": "Titolo", "narrative": "", "facts": [], "files": []}
        base.update(kw)
        return mem.add_observation(base)


class TestStorage(MemTest):
    def test_add_and_load_roundtrip(self):
        oid = self.obs(title="GST ristoranti al 5%", narrative="Deciso da Priya", facts=["rate 5"], files=["rates.json"])
        self.assertEqual(len(oid), 6)
        [o] = mem.load_observations()
        self.assertEqual(o["id"], oid)
        self.assertEqual(o["title"], "GST ristoranti al 5%")
        self.assertEqual(o["facts"], ["rate 5"])
        self.assertEqual(o["files"], ["rates.json"])
        self.assertEqual(o["source"], "claude")
        self.assertRegex(o["ts"], r"^\d{4}-\d\d-\d\d \d\d:\d\d$")

    def test_corrupt_line_skipped(self):
        self.obs(title="uno")
        with open(self.dir / "observations.jsonl", "a", encoding="utf-8") as f:
            f.write("{rotta\n")
        self.obs(title="due")
        self.assertEqual([o["title"] for o in mem.load_observations()], ["uno", "due"])

    def test_session_tagging(self):
        mem.set_current_session("sess-1")
        self.obs(title="x")
        mem.add_summary({"request": "r", "completed": "c"})
        self.assertEqual(mem.current_session(), "sess-1")
        self.assertEqual(mem.load_observations()[0]["session"], "sess-1")
        [s] = mem.load_sessions()
        self.assertEqual(s["session"], "sess-1")
        self.assertEqual(s["completed"], "c")


if __name__ == "__main__":
    unittest.main()
