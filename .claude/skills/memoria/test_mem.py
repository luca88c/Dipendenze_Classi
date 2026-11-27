"""Test per mem.py. Esegui: python3 -m unittest discover -s .claude/skills/memoria"""
import io
import json
import os
import subprocess
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
        self._pd = os.environ.pop("CLAUDE_PROJECT_DIR", None)  # i test usano il cwd dell'evento
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        os.environ.pop("MEMORIA_DIR", None)
        if self._pd is not None:
            os.environ["CLAUDE_PROJECT_DIR"] = self._pd
        self.tmp.cleanup()

    def obs(self, **kw):
        base = {"type": "decision", "title": "Titolo", "narrative": "", "facts": [], "files": []}
        base.update(kw)
        return mem.add_observation(base)


class TestStorage(MemTest):
    def test_add_and_load_roundtrip(self):
        oid = self.obs(title="GST ristoranti al 5%", narrative="Deciso da Priya", facts=["rate 5"], files=["rates.json"])
        self.assertEqual(len(oid), 8)
        [o] = mem.load_observations()
        self.assertEqual(o["id"], oid)
        self.assertEqual(o["title"], "GST ristoranti al 5%")
        self.assertEqual(o["facts"], ["rate 5"])
        self.assertEqual(o["files"], ["rates.json"])
        self.assertEqual(o["source"], "claude")
        self.assertRegex(o["ts"], r"^\d{4}-\d\d-\d\d \d\d:\d\d$")

    def test_corrupt_line_skipped(self):
        self.obs(title="uno")
        with open(mem.session_file(), "a", encoding="utf-8") as f:
            f.write("{rotta\n<<<<<<< HEAD\n[1, 2]\n")
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

    def test_search_prefers_claude_notes_over_auto(self):
        mem.add_observation({"source": "auto", "type": "change", "title": "Modificato Order.cs", "files": ["Order.cs"]})
        why = self.obs(title="Order riceve INotifica nel costruttore", files=["Order.cs"])
        self.assertEqual(mem.search("Order usa notifiche")[0]["id"], why)

    def test_get_keeps_order_and_skips_missing(self):
        a = self.obs(title="a")
        b = self.obs(title="b")
        got = mem.get([b, "zzzzzz", a])
        self.assertEqual([g["id"] for g in got], [b, a])
        self.assertIn("narrative", got[0])

    def test_cache_rebuilds_after_append(self):
        self.obs(title="primo")
        self.assertEqual(mem.search("secondo"), [])
        with open(mem.session_file(), "a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": "obs", "id": "abc123", "ts": "2026-01-01 10:00", "type": "change",
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


def run_cli(*argv, stdin=""):
    out = io.StringIO()
    old_stdin = sys.stdin
    sys.stdin = io.StringIO(stdin)
    try:
        with redirect_stdout(out):
            code = mem.main(list(argv))
    finally:
        sys.stdin = old_stdin
    return code, out.getvalue()


class TestIndexCli(MemTest):
    def test_index_empty_memory(self):
        text = mem.build_index()
        self.assertIn("vuota", text)

    def test_index_respects_cap(self):
        for i in range(100):
            self.obs(title=f"Nota numero {i} con un titolo abbastanza lungo da riempire")
            mem.add_observation({"source": "auto", "type": "change", "title": f"Modificato f{i}.py",
                                 "files": [f"f{i}.py"]})
        mem.add_summary({"request": "x" * 500, "completed": "y" * 500, "next_steps": "z" * 500})
        text = mem.build_index()
        self.assertLessEqual(len(text), 1200)
        self.assertIn("Nota numero 99", text)   # la più recente c'è
        self.assertNotIn("Nota numero 0 ", text)  # le vecchie no
        self.assertIn("mem.py search", text)     # istruzioni d'uso sempre presenti

    def test_index_shows_last_summary_and_files(self):
        mem.add_observation({"source": "auto", "type": "change", "title": "Modificato Order.cs", "files": ["Order.cs"]})
        mem.add_summary({"request": "rifattorizza ordini", "completed": "Order usa INotifiche", "next_steps": "test"})
        text = mem.build_index()
        self.assertIn("Order usa INotifiche", text)
        self.assertIn("Order.cs", text)

    def test_cli_add_then_search_then_get(self):
        code, out = run_cli("add", "--type", "decision", "--title", "GST ristoranti al 5%",
                            "--narrative", "Confermato da Priya", "--facts", "rate 5", "--files", "rates.json")
        self.assertEqual(code, 0)
        oid = out.strip().split()[-1]
        code, out = run_cli("search", "ristoranti")
        self.assertIn(oid, out)
        self.assertNotIn("Confermato da Priya", out)  # search mostra solo titoli
        code, out = run_cli("get", oid)
        self.assertIn("Confermato da Priya", out)

    def test_cli_summary_and_stats(self):
        code, _ = run_cli("summary", "--request", "r", "--completed", "fatto")
        self.assertEqual(code, 0)
        self.assertEqual(mem.load_sessions()[-1]["completed"], "fatto")
        code, out = run_cli("stats")
        self.assertIn("riassunti: 1", out)


class TestHooks(MemTest):
    def edit_event(self, path="/proj/src/Order.cs", sid="s1"):
        return {"session_id": sid, "cwd": "/proj", "hook_event_name": "PostToolUse",
                "tool_name": "Edit", "tool_input": {"file_path": path}}

    def test_auto_note_edit(self):
        n = mem.auto_note(self.edit_event())
        self.assertEqual((n["type"], n["source"], n["files"]), ("change", "auto", ["src/Order.cs"]))
        self.assertIn("src/Order.cs", n["title"])

    def test_auto_note_bash_and_ignores_readonly(self):
        def bash(cmd):
            return mem.auto_note({"session_id": "s1", "cwd": "/proj", "tool_name": "Bash",
                                  "tool_input": {"command": cmd}})
        self.assertEqual(bash("dotnet build")["type"], "command")
        self.assertIsNotNone(bash("cd src && dotnet test"))
        for ro in ["ls -la", "git status", "cd src && git log --oneline | head", "grep -r x .",
                   'python3 .claude/skills/memoria/mem.py search "x"',
                   'git ls-tree HEAD | grep -i -E "template|PULL_REQUEST" ; git log | wc -l']:
            self.assertIsNone(bash(ro), ro)
        self.assertIsNone(mem.auto_note({"tool_name": "Read", "tool_input": {"file_path": "/a"}}))

    def test_stop_blocks_once_then_allows_after_summary(self):
        run_cli("hook-start", stdin=json.dumps({"session_id": "s1", "source": "startup"}))
        self.assertIsNone(mem.stop_decision({"session_id": "s1"}))  # niente modifiche: non blocca
        run_cli("hook-tool", stdin=json.dumps(self.edit_event()))
        d = mem.stop_decision({"session_id": "s1", "stop_hook_active": False})
        self.assertEqual(d["decision"], "block")
        self.assertIn("summary", d["reason"])
        run_cli("summary", "--completed", "fatto")
        self.assertIsNone(mem.stop_decision({"session_id": "s1"}))
        run_cli("hook-tool", stdin=json.dumps(self.edit_event("/proj/b.cs")))  # nuova modifica dopo
        self.assertIsNotNone(mem.stop_decision({"session_id": "s1"}))
        run_cli("add", "--title", "perché b.cs")
        self.assertIsNone(mem.stop_decision({"session_id": "s1"}))

    def test_stop_ignores_other_sessions(self):
        run_cli("hook-tool", stdin=json.dumps(self.edit_event(sid="vecchia")))
        self.assertIsNone(mem.stop_decision({"session_id": "nuova"}))

    def test_stop_never_blocks_when_active(self):
        run_cli("hook-tool", stdin=json.dumps(self.edit_event()))
        self.assertIsNone(mem.stop_decision({"session_id": "s1", "stop_hook_active": True}))

    def test_hook_start_prints_index_and_sets_session(self):
        code, out = run_cli("hook-start", stdin=json.dumps({"session_id": "abc", "source": "startup"}))
        self.assertEqual(code, 0)
        self.assertIn("Memoria del progetto", out)
        self.assertEqual(mem.current_session(), "abc")

    def test_hook_stop_prints_json_when_blocking(self):
        run_cli("hook-tool", stdin=json.dumps(self.edit_event()))
        code, out = run_cli("hook-stop", stdin=json.dumps({"session_id": "s1"}))
        self.assertEqual(json.loads(out)["decision"], "block")

    def test_hook_bad_stdin_exits_zero(self):
        for h in ("hook-start", "hook-tool", "hook-stop"):
            code, _ = run_cli(h, stdin="non è json")
            self.assertEqual(code, 0, h)


class TestReviewFixes(MemTest):
    MEM = str(Path(__file__).resolve().parent / "mem.py")

    def cli(self, *args, stdin=b""):
        env = dict(os.environ, PYTHONIOENCODING="cp1252")
        return subprocess.run([sys.executable, self.MEM, *args], input=stdin, env=env,
                              capture_output=True)

    def test_search_many_auto_notes_keeps_why_note(self):  # C1
        for _ in range(25):
            mem.add_observation({"source": "auto", "type": "change", "title": "Modificato Order.cs",
                                 "files": ["Order.cs"]})
        why = self.obs(title="Order riceve INotifica", files=["Order.cs"])
        hits = mem.search("Order.cs")
        self.assertEqual(hits[0]["id"], why)
        self.assertEqual([h["title"] for h in hits].count("Modificato Order.cs"), 1)

    def test_cli_utf8_on_cp1252_console(self):  # I1
        self.obs(title="Freccia → perché ✓ città")
        r = self.cli("search", "freccia")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("→ perché ✓ città", r.stdout.decode("utf-8"))
        r = self.cli("hook-start")
        self.assertIn("perché", r.stdout.decode("utf-8"))

    def test_hook_stdin_utf8_on_cp1252_console(self):  # I1
        ev = {"session_id": "s1", "cwd": "/proj", "tool_name": "Write",
              "tool_input": {"file_path": "/proj/Università.cs", "content": "dice “ciao”"}}
        self.cli("hook-tool", stdin=json.dumps(ev, ensure_ascii=False).encode("utf-8"))
        self.assertEqual(mem.load_observations()[-1]["files"], ["Università.cs"])

    def test_git_commands_not_logged_and_reason_mentions_push(self):  # I2
        for cmd in ["git add -A", "git commit -m x", "cd a && git push -u origin b", "git pull"]:
            self.assertIsNone(mem.auto_note({"cwd": "/proj", "tool_name": "Bash",
                                             "tool_input": {"command": cmd}}), cmd)
        mem.set_current_session("s1")
        mem.add_observation(mem.auto_note({"cwd": "/proj", "tool_name": "Edit",
                                           "tool_input": {"file_path": "/proj/a.cs"}}))
        self.assertIn("push", mem.stop_decision({"session_id": "s1"})["reason"])

    def test_each_session_writes_its_own_file(self):  # I3
        mem.set_current_session("sessione-uno")
        a = self.obs(title="a")
        mem.add_summary({"completed": "uno"})
        mem.set_current_session("sessione-due")
        b = self.obs(title="b")
        files = sorted(p.name for p in self.dir.glob("*.jsonl"))
        self.assertEqual(len(files), 2)
        self.assertTrue(any("sessione-uno" in f for f in files), files)
        self.assertTrue(any("sessione-due" in f for f in files), files)
        self.assertEqual([o["id"] for o in mem.load_observations()], [a, b])
        self.assertEqual(mem.load_sessions()[0]["completed"], "uno")

    def test_index_keeps_room_for_why_notes(self):  # I4
        for i in range(20):
            self.obs(title=f"Decisione {i} " + "x" * 50)
        for i in range(8):
            f = f"src/Progetto.Dominio/Fatturazione/Servizi/Molto/Profondo/Servizio{i}.cs"
            mem.add_observation({"source": "auto", "type": "change", "title": f"Modificato {f}", "files": [f]})
        mem.add_summary({"completed": "c" * 400, "next_steps": "n" * 400})
        text = mem.build_index()
        self.assertLessEqual(len(text), 1200)
        self.assertGreaterEqual(sum(1 for l in text.splitlines() if " Decisione " in l), 6)
        self.assertIn("Servizio7.cs", text)

    def test_search_survives_corrupt_cache(self):  # M1
        self.obs(title="ristorante")
        (self.dir / "cache.db").write_bytes(b"spazzatura" * 100)
        self.assertEqual(len(mem.search("ristorante")), 1)

    def test_paths_outside_project_or_in_memory_not_logged(self):  # M5
        def edit(path):
            return mem.auto_note({"cwd": "/proj", "tool_name": "Edit", "tool_input": {"file_path": path}})
        self.assertIsNone(edit("/tmp/scratch.txt"))
        self.assertIsNone(edit("C:/Users/mario/x.cs" if os.name == "nt" else "/home/mario/x.cs"))
        self.assertIsNone(edit("/proj/.claude/memory/2026-01-01_s1.jsonl"))
        self.assertIsNotNone(edit("/proj/src/a.cs"))


if __name__ == "__main__":
    unittest.main()
