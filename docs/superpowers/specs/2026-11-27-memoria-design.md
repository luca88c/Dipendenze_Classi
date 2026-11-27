# Memoria persistente per Claude Code — design breve

Ispirato alla guida "Build claude-mem From Scratch" (datasciencebrain): stessa idea a tre livelli
(indice → search → get), adattata a Claude Code senza API esterne.

## Perché
L'utente vuole che Claude Code ricordi davvero tutto il lavoro fatto tra una sessione e l'altra,
senza bruciare token: all'avvio solo un indice piccolo, i dettagli solo quando servono.

## Obiettivi
- All'avvio di ogni sessione Claude riceve un indice di ~300 token al massimo.
- Ogni modifica a file e ogni comando "che cambia qualcosa" viene annotato in automatico, a 0 token.
- Il "perché" delle decisioni viene scritto da Claude come nota breve, e a fine lavoro un riassunto.
- La memoria sopravvive alle sessioni cloud usa-e-getta: vive in file di testo nel repo.

## Non obiettivi
- Ricerca vettoriale (Chroma/MiniLM): download di ~80MB e rete. Sostituita da ricerca con sinonimi.
- LLM esterno per comprimere (Groq/Haiku): costa token/API. Le note auto sono meccaniche.
- Web viewer, worker in background.

## Anti-obiettivi
- Un indice che cresce e viene caricato intero (il problema di CLAUDE.md).
- Hook che rompono o rallentano la sessione: ogni hook deve uscire con 0 anche in caso di errore.

## Approcci considerati
- **A (scelto)**: memoria propria. Hook automatici gratuiti + note "perché" scritte da Claude,
  file JSONL nel repo + indice SQLite FTS5 ricostruito in cache.
- B: plugin claude-mem originale. Completo ma chiama un modello a ogni tool call e salva su disco
  locale, che nelle sessioni cloud sparisce.
- C: note a mano in CLAUDE.md. Zero infrastruttura ma caricato intero ogni volta: i token crescono.

## Design
- `.claude/memory/observations.jsonl` e `sessions.jsonl`: fonte di verità, testo, append-only,
  committati. `.gitattributes` con `merge=union` per evitare conflitti tra branch.
- `.claude/memory/cache.db` (gitignored): SQLite + FTS5 ricostruito quando i JSONL cambiano.
  Fallback a ricerca semplice se FTS5 manca.
- `.claude/skills/memoria/mem.py`, solo stdlib. Comandi: `index`, `search`, `get`, `add`,
  `summary`, `stats`, più i sottocomandi per gli hook.
- Id brevi esadecimali (6 caratteri), così note scritte su branch diversi non collidono.
- Hook in `.claude/settings.json`:
  - SessionStart → stampa l'indice (ultimo riassunto + note recenti + file toccati), tetto ~300 token.
  - PostToolUse (Edit/Write/MultiEdit/NotebookEdit/Bash) → nota automatica silenziosa;
    i comandi Bash di sola lettura (ls, cat, grep, git status…) vengono ignorati.
  - Stop → se in questa sessione ci sono modifiche non ancora spiegate da una nota o riassunto,
    blocca una volta e chiede a Claude di scrivere il riassunto (protezione anti-loop).
- `SKILL.md`: quando cercare (search poi get solo sugli id utili, provando sinonimi), quando
  scrivere note, come fare il riassunto, ricordarsi di committare `.claude/memory/`.

## Scelte lasciate a chi costruisce (mie)
- Comando hook `python3 … || python …` per funzionare anche su Windows.
- Ricerca: parole tra virgolette unite da OR, stopword italiane e inglesi, ordinamento BM25.
