#!/usr/bin/env python3
"""Memoria persistente per Claude Code, ispirata a claude-mem.

Fonte di verità: due file JSONL in .claude/memory/ (committati nel repo).
Cache di ricerca: .claude/memory/cache.db (SQLite FTS5, ricostruita da sola).
Solo libreria standard.
"""
import json
import os
import secrets
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
