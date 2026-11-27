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


class TestSearch(MemTest):
    def test_search_special_chars(self):
        self.obs(title="GST ristoranti", files=["rates.json"], facts=["composition-scheme 5%"])
        for q in ["rates.json", "composition-scheme 5%", '"', "", "AND OR NOT", "a*b:c"]:
            mem.search(q)  # non deve sollevare
        self.assertEqual(len(mem.search("rates.json")), 1)
        self.assertEqual(len(mem.search("composition-scheme 5%")), 1)

    def test_search_ranks_match_first(self):
        self.obs(title="Login utente", narrative="sessioni")
        best = self.obs(title="Fattura GST ristorante", narrative="GST ristorante abbassata al 5", facts=["GST"])
        self.obs(title="Altro", narrative="ristorante")
        hits = mem.search("GST ristorante")
        self.assertEqual(hits[0]["id"], best)
        self.assertEqual(set(hits[0]), {"id", "ts", "type", "title", "files"})

    def test_get_keeps_order_and_skips_missing(self):
        a = self.obs(title="a")
        b = self.obs(title="b")
        got = mem.get([b, "zzzzzz", a])
        self.assertEqual([g["id"] for g in got], [b, a])
        self.assertIn("narrative", got[0])

    def test_cache_rebuilds_after_append(self):
        self.obs(title="primo")
        self.assertEqual(mem.search("secondo"), [])
        with open(self.dir / "observations.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": "abc123", "ts": "2026-01-01 10:00", "type": "change",
                                "title": "secondo arrivato da git pull", "narrative": "",
                                "facts": [], "files": []}) + "\n")
        self.assertEqual([h["id"] for h in mem.search("secondo")], ["abc123"])

    def test_search_without_fts5_fallback(self):
        self.obs(title="Altro", narrative="ristorante")
        best = self.obs(title="GST ristorante", files=["rates.json"])
        old, mem._FTS5 = mem._FTS5, False
        try:
            hits = mem.search("GST ristorante rates.json")
        finally:
            mem._FTS5 = old
        self.assertEqual(hits[0]["id"], best)

    def test_to_match_query_quotes_and_drops_stopwords(self):
        self.assertEqual(mem.to_match_query("Perché il GST è 5?"), '"gst" OR "5"')
        self.assertEqual(mem.to_match_query("the and"), "")


if __name__ == "__main__":
    unittest.main()
