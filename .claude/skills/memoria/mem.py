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
            sqlite3.connect(":memory:").execute("CREATE VIRTUAL TABLE t USING fts5(x)")
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
