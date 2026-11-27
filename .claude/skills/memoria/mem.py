#!/usr/bin/env python3
"""Memoria persistente per Claude Code, ispirata a claude-mem.

Fonte di verità: un file JSONL per sessione in .claude/memory/ (committati nel repo:
sessioni diverse scrivono file diversi, quindi niente conflitti di merge, nemmeno su GitHub).
Cache di ricerca: .claude/memory/cache.db (SQLite FTS5, ricostruita da sola, non committata).
Solo libreria standard.
"""
import json
import os
import re
import secrets
import sqlite3
import sys
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

CURRENT_FILE = ".current_session"
CACHE_FILE = "cache.db"
SKILL_CMD = "python3 .claude/skills/memoria/mem.py"


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
    return secrets.token_hex(4)


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def set_current_session(sid: str) -> None:
    (memory_dir() / CURRENT_FILE).write_text(sid, encoding="utf-8")


def current_session() -> str:
    p = memory_dir() / CURRENT_FILE
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def _session_key(sid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", sid or "")[:12] or "manuale"


def session_file(sid: str = None) -> Path:
    """Il file JSONL della sessione: <data di inizio>_<sessione>.jsonl."""
    key = _session_key(current_session() if sid is None else sid)
    existing = sorted(memory_dir().glob(f"*_{key}.jsonl"))
    if existing:
        return existing[0]
    return memory_dir() / f"{datetime.now():%Y-%m-%d}_{key}.jsonl"


def _append(record: dict, sid: str = None) -> None:
    with open(session_file(sid), "a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _read(path: Path) -> list:
    out = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
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


def _load_all() -> list:
    """Tutti i record, in ordine: file per data/ora del primo record, righe nell'ordine scritto."""
    files = [(p, _read(p)) for p in memory_dir().glob("*.jsonl")]
    def key(fr):
        first = fr[1][0] if fr[1] else {}
        return (str(first.get("ts", ""))[:16], float(first.get("t") or 0), fr[0].name)
    files.sort(key=key)
    return [r for _, recs in files for r in recs]


def add_observation(obs: dict, session: str = None) -> str:
    """Salva una nota e ne ritorna l'id."""
    sid = current_session() if session is None else session
    rec = {
        "kind": "obs",
        "id": new_id(),
        "ts": now(),
        "t": time.time(),
        "session": sid,
        "source": obs.get("source", "claude"),
        "type": obs.get("type", "note"),
        "title": obs.get("title", "").strip(),
        "narrative": obs.get("narrative", "").strip(),
        "facts": list(obs.get("facts") or []),
        "files": list(obs.get("files") or []),
    }
    _append(rec, sid)
    return rec["id"]


def add_summary(s: dict) -> None:
    """Salva il riassunto di fine lavoro della sessione corrente."""
    sid = current_session()
    rec = {"kind": "summary", "session": sid, "ts": now(), "t": time.time()}
    for k in ("request", "investigated", "learned", "completed", "next_steps"):
        rec[k] = (s.get(k) or "").strip()
    _append(rec, sid)


def load_observations() -> list:
    return [r for r in _load_all() if r.get("kind") == "obs"]


def load_sessions() -> list:
    return [r for r in _load_all() if r.get("kind") == "summary"]


# --------------------------------------------------------------------------- ricerca

STOPWORDS = {
    # inglese
    "the", "and", "for", "why", "what", "who", "how", "did", "does", "was", "were", "this",
    "that", "with", "from", "are", "is", "do", "of", "to", "in", "on", "it", "at", "by", "be",
    "as", "or", "an", "not",
    # italiano
    "il", "lo", "la", "le", "gli", "un", "una", "uno", "di", "da", "del", "della", "dei",
    "delle", "al", "alla", "ai", "nel", "nella", "per", "con", "su", "che", "chi", "cosa",
    "come", "quando", "perché", "perche", "è", "e", "ed", "o", "non", "ho", "abbiamo",
    "sono", "era", "stato", "stata", "fatto", "si", "ci", "mi", "ti", "questo",
    "questa", "quello", "quella",
}
_FTS5 = None  # None = da verificare; True/False dopo il primo controllo


def _fts5_available() -> bool:
    global _FTS5
    if _FTS5 is None:
        try:
            with closing(sqlite3.connect(":memory:")) as db:
                db.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='unicode61 remove_diacritics 2')")
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
    for p in sorted(memory_dir().glob("*.jsonl")):
        st = p.stat()
        parts.append(f"{p.name}:{st.st_size}:{st.st_mtime_ns}")
    return "|".join(parts)


def connect() -> sqlite3.Connection:
    """Apre la cache FTS5, ricostruendola dai JSONL se sono cambiati."""
    sig = _signature()
    db = sqlite3.connect(memory_dir() / CACHE_FILE, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN IMMEDIATE")  # un processo alla volta ricostruisce
        db.execute("CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT)")
        row = db.execute("SELECT v FROM meta WHERE k='sig'").fetchone()
        if row is None or row["v"] != sig:
            db.execute("DROP TABLE IF EXISTS obs_fts")
            db.execute("CREATE VIRTUAL TABLE obs_fts USING fts5("
                       " oid UNINDEXED, title, narrative, facts, files, type,"
                       " tokenize='unicode61 remove_diacritics 2')")
            db.executemany(
                "INSERT INTO obs_fts(oid, title, narrative, facts, files, type) VALUES (?,?,?,?,?,?)",
                [(o.get("id", ""), o.get("title", ""), o.get("narrative", ""),
                  "\n".join(map(str, o.get("facts") or [])), " ".join(map(str, o.get("files") or [])),
                  o.get("type", "")) for o in load_observations()],
            )
            db.execute("INSERT OR REPLACE INTO meta(k, v) VALUES ('sig', ?)", (sig,))
        db.commit()
    except BaseException:
        db.close()
        raise
    return db


def _fts_ids(query: str) -> list:
    with closing(connect()) as db:
        rows = db.execute(
            "SELECT oid FROM obs_fts WHERE obs_fts MATCH ?"
            " ORDER BY bm25(obs_fts, 0, 3.0, 1.0, 1.0, 1.0, 0.5)",
            (query,),
        ).fetchall()
    return [r["oid"] for r in rows]


def _fts_ids_safe(query: str):
    """Ricerca FTS5; con cache rovinata la cancella e riprova una volta. None = usa il ripiego."""
    for attempt in range(2):
        try:
            return _fts_ids(query)
        except sqlite3.Error:
            if attempt == 0:
                for suffix in ("", "-journal", "-wal", "-shm"):
                    try:
                        (memory_dir() / (CACHE_FILE + suffix)).unlink()
                    except OSError:
                        pass
    return None


def _plain_ids(text: str, by_id: dict) -> list:
    """Ripiego senza FTS5: conta le parole in comune, il titolo pesa di più."""
    terms = set(_words(text))
    scored = []
    for oid, o in by_id.items():
        body = set(_words(" ".join([o.get("narrative", ""), " ".join(map(str, o.get("facts") or [])),
                                    " ".join(map(str, o.get("files") or []))])))
        score = 3 * len(terms & set(_words(o.get("title", "")))) + len(terms & body)
        if score:
            scored.append((-score, oid))
    return [i for _, i in sorted(scored)]


def _brief(o: dict) -> dict:
    return {k: o.get(k, "" if k != "files" else []) for k in ("id", "ts", "type", "title", "files")}


def search(text: str, limit: int = 5) -> list:
    """Note che condividono parole con la domanda (livello 2: solo titoli).

    Le note scritte da Claude (con il perché) vengono prima; le note automatiche
    con lo stesso titolo contano una volta sola.
    """
    query = to_match_query(text)
    if not query:
        return []
    by_id = {o.get("id"): o for o in load_observations()}
    ids = _fts_ids_safe(query) if _fts5_available() else None
    if ids is None:
        ids = _plain_ids(text, by_id)
    seen_auto, ranked = set(), []
    for i in ids:
        o = by_id.get(i)
        if o is None:
            continue
        if o.get("source") == "auto":
            if o.get("title") in seen_auto:
                continue
            seen_auto.add(o.get("title"))
        ranked.append(o)
    ranked.sort(key=lambda o: o.get("source") == "auto")  # stabile: mantiene l'ordine BM25
    return [_brief(o) for o in ranked[:limit]]


def get(ids: list) -> list:
    """Note complete (livello 3), nell'ordine richiesto; id inesistenti saltati."""
    by_id = {o.get("id"): o for o in load_observations()}
    return [by_id[i] for i in ids if i in by_id]


# --------------------------------------------------------------------------- indice (livello 1)

USAGE_LINE = f'Dettagli: {SKILL_CMD} search "parole" -> get ID... (vedi skill "memoria")'
INDEX_NOTES = 15
INDEX_FILES = 5
INDEX_MIN_NOTES = 6
FILES_LINE_MAX = 200


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
        line = f"Ultima sessione ({s.get('ts', '')}): {_cut(s.get('completed') or s.get('request'), 140)}"
        if s.get("next_steps"):
            line += f" | Prossimi passi: {_cut(s['next_steps'], 60)}"
        head.append(line)

    counts, recent = {}, []
    for o in reversed(obs):
        if o.get("source") == "auto":
            for f in o.get("files") or []:
                if f not in counts:
                    recent.append(f)
                counts[f] = counts.get(f, 0) + 1
    files_line = ""
    if counts:
        top = sorted(recent, key=lambda f: -counts[f])[:INDEX_FILES]
        # la coda del percorso: il nome del file è la parte che conta
        files_line = _cut("File toccati: " + ", ".join(
            f"{_cut(f[-35:] if len(f) > 35 else f, 36)} ({counts[f]})" for f in top), FILES_LINE_MAX)

    notes = [o for o in reversed(obs) if o.get("source") != "auto"][:INDEX_NOTES]
    lines = [f"{o.get('id')} {str(o.get('ts', ''))[5:10]} {o.get('type', '')} {_cut(o.get('title'), 60)}"
             for o in notes]
    if lines:
        lines.insert(0, "Note recenti (id data tipo titolo):")
    budget = max_chars - sum(len(x) + 1 for x in head + [USAGE_LINE])
    # le note col perché hanno la precedenza: i file prendono solo quello che avanza
    reserved = sum(len(x) + 1 for x in lines[:INDEX_MIN_NOTES + 1])
    if files_line:
        room = budget - reserved - 1
        files_line = _cut(files_line, room) if room > 20 else ""
        budget -= len(files_line) + 1 if files_line else 0
    body = []
    for line in lines:
        if len(line) + 1 > budget:
            break
        body.append(line)
        budget -= len(line) + 1

    tail = ([files_line] if files_line else []) + [USAGE_LINE]
    return "\n".join(head + body + tail)[:max_chars]


# --------------------------------------------------------------------------- hook

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
# comandi che non cambiano nulla; git è escluso del tutto: la sua storia la tiene già git
SKIP_CMDS = {"ls", "cat", "head", "tail", "grep", "rg", "find", "pwd", "echo", "which",
             "cd", "wc", "less", "more", "tree", "stat", "file", "type", "env", "date",
             "sort", "uniq", "diff", "true", "git"}
TOOL_CMD_CHARS = 100


def _rel(path: str, cwd: str):
    """Percorso relativo al progetto, o None se il file è fuori dal progetto."""
    base = os.environ.get("CLAUDE_PROJECT_DIR") or cwd
    if not base or not path:
        return None
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(base))
    except ValueError:  # Windows, dischi diversi
        return None
    rel = rel.replace(os.sep, "/")
    if rel == ".." or rel.startswith("../") or os.path.isabs(rel):
        return None
    return rel


def _skip_command(cmd: str) -> bool:
    if "mem.py" in cmd:
        return True
    # toglie il testo tra virgolette, così "a|b" dentro un grep non conta come pipe
    unquoted = re.sub(r"'[^']*'|\"(?:\\.|[^\"\\])*\"", "''", cmd)
    for seg in re.split(r"&&|\|\||;|\|", unquoted):
        words = seg.split()
        if words and words[0] not in SKIP_CMDS:
            return False
    return True


def auto_note(event: dict):
    """Nota automatica (0 token) per una tool call di Claude Code, o None se non interessa."""
    tool = event.get("tool_name", "")
    inp = event.get("tool_input") or {}
    if tool in EDIT_TOOLS:
        rel = _rel(inp.get("file_path") or inp.get("notebook_path") or "", event.get("cwd", ""))
        if rel is None or rel.startswith(".claude/memory/"):
            return None
        return {"source": "auto", "type": "change", "title": f"Modificato {rel}", "files": [rel]}
    if tool == "Bash":
        cmd = " ".join(str(inp.get("command", "")).split())
        if not cmd or _skip_command(cmd):
            return None
        return {"source": "auto", "type": "command", "title": "$ " + _cut(cmd, TOOL_CMD_CHARS)}
    return None


def stop_decision(event: dict):
    """Blocca lo stop una volta se ci sono modifiche di questa sessione non spiegate da una nota."""
    if event.get("stop_hook_active"):
        return None
    sid = event.get("session_id") or current_session()
    path = session_file(sid)
    recs = _read(path) if path.exists() else []
    cutoff = -1
    for i, r in enumerate(recs):
        if r.get("kind") == "summary" or (r.get("kind") == "obs" and r.get("source") != "auto"):
            cutoff = i
    pending = [r for r in recs[cutoff + 1:]
               if r.get("kind") == "obs" and r.get("source") == "auto" and r.get("type") == "change"]
    if not pending:
        return None
    files = list(dict.fromkeys(f for r in pending for f in r.get("files") or []))
    shown = ", ".join(files[:5]) + (" …" if len(files) > 5 else "")
    return {"decision": "block", "reason": (
        f"Memoria: hai modificato {len(files)} file ({shown}) senza salvare il perché. "
        f'Salva un riassunto breve: {SKILL_CMD} summary --request "..." --completed "..." '
        '[--learned "..."] [--next "..."]; per scelte importanti anche: '
        'mem.py add --type decision --title "..." --narrative "...". '
        "Poi fai commit e push anche di .claude/memory/ (nelle sessioni cloud è l'unico modo "
        "perché la memoria sopravviva). Su Windows usa python al posto di python3.")}


def run_hook(name: str) -> int:
    """Punto d'ingresso degli hook: non deve mai rompere la sessione."""
    try:
        buf = getattr(sys.stdin, "buffer", None)  # byte grezzi: niente cp1252 su Windows
        raw = buf.read().decode("utf-8", errors="replace") if buf else sys.stdin.read()
        try:
            event = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            event = {}
        if not isinstance(event, dict):
            event = {}
        sid = event.get("session_id")
        if sid and sid != current_session():
            set_current_session(sid)
        if name == "hook-start":
            print(build_index())
        elif name == "hook-tool":
            note = auto_note(event)
            if note:
                add_observation(note, session=sid)
        elif name == "hook-stop":
            decision = stop_decision(event)
            if decision:
                print(json.dumps(decision, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - un hook non deve mai fallire
        print(f"[memoria] errore ignorato: {exc}", file=sys.stderr)
    return 0


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


def _utf8_console() -> None:
    # Claude Code legge l'output come UTF-8; su Windows la console di default è cp1252.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: list) -> int:
    _utf8_console()
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


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
