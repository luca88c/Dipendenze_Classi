#!/usr/bin/env python3
"""Memoria persistente per Claude Code, ispirata a claude-mem.

Fonte di verità: due file JSONL in .claude/memory/ (committati nel repo).
Cache di ricerca: .claude/memory/cache.db (SQLite FTS5, ricostruita da sola).
Solo libreria standard.
"""
import json
import os
import re
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

OBS_FILE = "observations.jsonl"
SESS_FILE = "sessions.jsonl"
CURRENT_FILE = ".current_session"


# --------------------------------------------------------------------------- storage

def memory_dir() -> Path:
    """Cartella della memoria: MEMORIA_DIR, poi $CLAUDE_PROJECT_DIR/.claude/memory, poi accanto alla skill."""
    if os.environ.get("MEMORIA_DIR"):
        d = Path(os.environ["MEMORIA_DIR"])
    elif os.environ.get("CLAUDE_PROJECT_DIR"):
        d = Path(os.environ["CLAUDE_PROJECT_DIR"]) / ".claude" / "memory"
    else:
        d = Path(__file__).resolve().parents[2] / "memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def new_id() -> str:
    return secrets.token_hex(3)


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def set_current_session(sid: str) -> None:
    (memory_dir() / CURRENT_FILE).write_text(sid, encoding="utf-8")


def current_session() -> str:
    p = memory_dir() / CURRENT_FILE
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def _append(name: str, record: dict) -> None:
    with open(memory_dir() / name, "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load(name: str) -> list:
    p = memory_dir() / name
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue  # riga rovinata (es. merge sbagliato): la saltiamo
        if isinstance(rec, dict):
            out.append(rec)
    return out


def add_observation(obs: dict) -> str:
    """Salva una nota e ne ritorna l'id."""
    rec = {
        "id": new_id(),
        "ts": now(),
        "session": current_session(),
        "source": obs.get("source", "claude"),
        "type": obs.get("type", "note"),
        "title": obs.get("title", "").strip(),
        "narrative": obs.get("narrative", "").strip(),
        "facts": list(obs.get("facts") or []),
        "files": list(obs.get("files") or []),
    }
    _append(OBS_FILE, rec)
    return rec["id"]


def add_summary(s: dict) -> None:
    """Salva il riassunto di fine lavoro della sessione corrente."""
    rec = {"session": current_session(), "ts": now()}
    for k in ("request", "investigated", "learned", "completed", "next_steps"):
        rec[k] = (s.get(k) or "").strip()
    _append(SESS_FILE, rec)


def load_observations() -> list:
    return _load(OBS_FILE)


def load_sessions() -> list:
    return _load(SESS_FILE)


# --------------------------------------------------------------------------- ricerca

CACHE_FILE = "cache.db"
STOPWORDS = {
    # inglese
    "the", "and", "for", "why", "what", "who", "how", "did", "does", "was", "were", "this",
    "that", "with", "from", "are", "is", "do", "of", "to", "in", "on", "it", "at", "by", "be",
    "as", "or", "an", "not",
    # italiano
    "il", "lo", "la", "le", "gli", "un", "una", "uno", "di", "da", "del", "della", "dei",
    "delle", "al", "alla", "ai", "nel", "nella", "per", "con", "su", "che", "chi", "cosa",
    "come", "quando", "perché", "perche", "è", "e", "ed", "o", "non", "ho", "abbiamo",
    "abbiamo", "sono", "era", "stato", "stata", "fatto", "si", "ci", "mi", "ti", "questo",
    "questa", "quello", "quella",
}
_FTS5 = None  # None = da verificare; True/False dopo il primo controllo


def _fts5_available() -> bool:
    global _FTS5
    if _FTS5 is None:
        try:
            with closing(sqlite3.connect(":memory:")) as db:
                db.execute("CREATE VIRTUAL TABLE t USING fts5(x)")
            _FTS5 = True
        except sqlite3.Error:
            _FTS5 = False
    return _FTS5


def _words(text: str) -> list:
    words = [w.strip(".-") for w in re.findall(r"[\w.%-]+", (text or "").lower())]
    return [w for w in words if (len(w) > 1 or w.isdigit()) and w not in STOPWORDS]


def to_match_query(text: str) -> str:
    """Testo libero -> query FTS5 sicura: ogni parola tra virgolette, unite da OR."""
    return " OR ".join(f'"{w}"' for w in dict.fromkeys(_words(text)))


def _signature() -> str:
    parts = []
    for name in (OBS_FILE, SESS_FILE):
        p = memory_dir() / name
        st = p.stat() if p.exists() else None
        parts.append(f"{st.st_size}:{st.st_mtime_ns}" if st else "0")
    return "|".join(parts)


def connect() -> sqlite3.Connection:
    """Apre la cache FTS5, ricostruendola dai JSONL se sono cambiati."""
    path = memory_dir() / CACHE_FILE
    sig = _signature()
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
    row = db.execute("SELECT v FROM meta WHERE k='sig'").fetchone()
    if row is None or row["v"] != sig:
        db.executescript(
            "DROP TABLE IF EXISTS obs_fts;"
            "CREATE VIRTUAL TABLE obs_fts USING fts5("
            "  oid UNINDEXED, title, narrative, facts, files, type,"
            "  tokenize='unicode61 remove_diacritics 2');"
        )
        db.executemany(
            "INSERT INTO obs_fts(oid, title, narrative, facts, files, type) VALUES (?,?,?,?,?,?)",
            [(o.get("id", ""), o.get("title", ""), o.get("narrative", ""),
              "\n".join(map(str, o.get("facts") or [])), " ".join(map(str, o.get("files") or [])),
              o.get("type", "")) for o in load_observations()],
        )
        db.execute("INSERT OR REPLACE INTO meta(k, v) VALUES ('sig', ?)", (sig,))
        db.commit()
    return db


def _brief(o: dict) -> dict:
    return {k: o.get(k, "" if k != "files" else []) for k in ("id", "ts", "type", "title", "files")}


def search(text: str, limit: int = 5) -> list:
    """Note che condividono parole con la domanda, migliore prima. Solo titoli (livello 2)."""
    query = to_match_query(text)
    if not query:
        return []
    by_id = {o.get("id"): o for o in load_observations()}
    if _fts5_available():
        with closing(connect()) as db:
            rows = db.execute(
                "SELECT oid FROM obs_fts WHERE obs_fts MATCH ?"
                " ORDER BY bm25(obs_fts, 0, 3.0, 1.0, 1.0, 1.0, 0.5) LIMIT ?",
                (query, limit),
            ).fetchall()
        ids = [r["oid"] for r in rows]
    else:  # ripiego senza FTS5: conta le parole in comune, il titolo pesa di più
        terms = set(_words(text))
        scored = []
        for o in by_id.values():
            body = set(_words(" ".join([o.get("narrative", ""), " ".join(map(str, o.get("facts") or [])),
                                        " ".join(map(str, o.get("files") or []))])))
            score = 3 * len(terms & set(_words(o.get("title", "")))) + len(terms & body)
            if score:
                scored.append((-score, o.get("id")))
        ids = [i for _, i in sorted(scored)[:limit]]
    return [_brief(by_id[i]) for i in ids if i in by_id]


def get(ids: list) -> list:
    """Note complete (livello 3), nell'ordine richiesto; id inesistenti saltati."""
    by_id = {o.get("id"): o for o in load_observations()}
    return [by_id[i] for i in ids if i in by_id]


# --------------------------------------------------------------------------- indice (livello 1)

USAGE_LINE = ('Dettagli: python3 .claude/skills/memoria/mem.py search "parole" -> get ID... '
              '(vedi skill "memoria")')
INDEX_NOTES = 15
INDEX_FILES = 8


def _cut(text: str, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1] + "…"


def build_index(max_chars: int = 1200) -> str:
    """Il testo dato a Claude all'avvio: piccolo, solo titoli. I dettagli si chiedono dopo."""
    obs = load_observations()
    sessions = load_sessions()
    if not obs and not sessions:
        return "# Memoria del progetto vuota: nessuna nota ancora.\n" + USAGE_LINE

    head = [f"# Memoria del progetto ({len(obs)} note, {len(sessions)} riassunti) - solo titoli"]
    if sessions:
        s = sessions[-1]
        line = f"Ultima sessione ({s.get('ts', '')}): {_cut(s.get('completed') or s.get('request'), 200)}"
        if s.get("next_steps"):
            line += f" | Prossimi passi: {_cut(s['next_steps'], 120)}"
        head.append(line)

    counts = {}
    for o in obs:
        if o.get("source") == "auto":
            for f in o.get("files") or []:
                counts[f] = counts.get(f, 0) + 1
    files_line = ""
    if counts:
        recent_first = list(dict.fromkeys(f for o in reversed(obs) if o.get("source") == "auto"
                                          for f in (o.get("files") or [])))
        top = sorted(recent_first, key=lambda f: -counts[f])[:INDEX_FILES]
        files_line = "File toccati: " + ", ".join(f"{_cut(f, 40)} ({counts[f]})" for f in top)

    tail = ([files_line] if files_line else []) + [USAGE_LINE]
    budget = max_chars - sum(len(x) + 1 for x in head + tail)

    notes = [o for o in reversed(obs) if o.get("source") != "auto"][:INDEX_NOTES]
    body = []
    if notes:
        title = "Note recenti (id data tipo titolo):"
        if len(title) + 1 <= budget:
            body.append(title)
            budget -= len(title) + 1
        for o in notes:
            line = f"{o.get('id')} {str(o.get('ts', ''))[:10]} {o.get('type', '')} {_cut(o.get('title'), 70)}"
            if len(line) + 1 > budget:
                break
            body.append(line)
            budget -= len(line) + 1

    text = "\n".join(head + body + tail)
    return text[:max_chars]


# --------------------------------------------------------------------------- CLI

def _fmt_full(o: dict) -> str:
    lines = [f"[{o.get('id')}] {o.get('ts', '')} {o.get('type', '')} - {o.get('title', '')}"]
    if o.get("narrative"):
        lines.append(o["narrative"])
    lines += [f"- {f}" for f in o.get("facts") or []]
    if o.get("files"):
        lines.append("file: " + ", ".join(o["files"]))
    return "\n".join(lines)


def _parser():
    import argparse
    p = argparse.ArgumentParser(prog="mem.py", description="Memoria persistente del progetto.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index", help="indice breve (livello 1)")
    s = sub.add_parser("search", help="cerca note, solo titoli (livello 2)")
    s.add_argument("text", nargs="+")
    s.add_argument("-n", type=int, default=5)
    g = sub.add_parser("get", help="note complete per id (livello 3)")
    g.add_argument("ids", nargs="+")
    a = sub.add_parser("add", help="salva una nota")
    a.add_argument("--type", default="note",
                   help="decision, bugfix, feature, refactor, discovery, change, note")
    a.add_argument("--title", required=True)
    a.add_argument("--narrative", default="")
    a.add_argument("--facts", nargs="*", default=[])
    a.add_argument("--files", nargs="*", default=[])
    m = sub.add_parser("summary", help="riassunto di fine lavoro")
    m.add_argument("--request", default="")
    m.add_argument("--investigated", default="")
    m.add_argument("--learned", default="")
    m.add_argument("--completed", required=True)
    m.add_argument("--next", dest="next_steps", default="")
    sub.add_parser("stats", help="conteggi")
    for h in ("hook-start", "hook-tool", "hook-stop"):
        sub.add_parser(h, help="usato dagli hook di Claude Code (legge JSON da stdin)")
    return p


def main(argv: list) -> int:
    args = _parser().parse_args(argv)
    if args.cmd.startswith("hook-"):
        return run_hook(args.cmd)
    if args.cmd == "index":
        print(build_index())
    elif args.cmd == "search":
        hits = search(" ".join(args.text), args.n)
        if not hits:
            print("Nessun risultato. Prova sinonimi o parole del codice (nomi di file, classi).")
        for h in hits:
            files = f" [{', '.join(h['files'][:3])}]" if h["files"] else ""
            print(f"{h['id']} {str(h['ts'])[:10]} {h['type']} {h['title']}{files}")
    elif args.cmd == "get":
        found = get(args.ids)
        print("\n\n".join(_fmt_full(o) for o in found) or "Nessuna nota con questi id.")
    elif args.cmd == "add":
        oid = add_observation({"type": args.type, "title": args.title, "narrative": args.narrative,
                               "facts": args.facts, "files": args.files})
        print(f"Salvata nota {oid}")
    elif args.cmd == "summary":
        add_summary({"request": args.request, "investigated": args.investigated,
                     "learned": args.learned, "completed": args.completed,
                     "next_steps": args.next_steps})
        print("Riassunto salvato.")
    elif args.cmd == "stats":
        obs = load_observations()
        auto = sum(1 for o in obs if o.get("source") == "auto")
        print(f"note: {len(obs)} (scritte da Claude {len(obs) - auto}, automatiche {auto})")
        print(f"riassunti: {len(load_sessions())}")
    return 0


def run_hook(name: str) -> int:
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
