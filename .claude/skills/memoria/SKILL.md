---
name: memoria
description: Memoria persistente del progetto tra sessioni, a basso consumo di token. Usala quando l'utente chiede "ti ricordi", "cosa abbiamo fatto", "perché abbiamo deciso", "la volta scorsa", "nella sessione precedente"; prima di lavorare su file o aree già toccate in passato; quando una scelta o il suo motivo non si capisce dal codice; e per salvare decisioni, scoperte e il riassunto a fine lavoro.
---

# Memoria

La memoria vive in `.claude/memory/<data>_<sessione>.jsonl`: un file di testo per sessione, committato nel repo
(sessioni diverse non vanno mai in conflitto, nemmeno nelle PR su GitHub). Tre livelli, come claude-mem:
paghi i dettagli solo quando li chiedi.

| Livello | Cosa vedi | Costo |
|---|---|---|
| 1. Indice | Ultimo riassunto + titoli delle note recenti + file toccati. Arriva da solo all'avvio (hook). | ~300 token |
| 2. `search` | id e titoli delle note che corrispondono | ~20 token a risultato |
| 3. `get` | nota completa: racconto, fatti, file | ~80 token a nota |

Comandi (dalla radice del repo; su Windows `python` al posto di `python3`):

```bash
python3 .claude/skills/memoria/mem.py search "parole chiave"      # livello 2
python3 .claude/skills/memoria/mem.py get a3f9c1 7b2e04           # livello 3
python3 .claude/skills/memoria/mem.py add --type decision --title "..." --narrative "..." --facts "..." --files Order.cs
python3 .claude/skills/memoria/mem.py summary --request "..." --completed "..." --learned "..." --next "..."
python3 .claude/skills/memoria/mem.py index | stats
```

## Leggere

1. Prima guarda l'indice che hai già nel contesto: spesso basta.
2. Se serve di più: `search` con 2-4 parole del dominio o nomi di file/classi.
3. `get` **solo** sugli id che servono davvero. Mai `get` su tutto.
4. Zero risultati? La ricerca è per parole, non per significato: riprova con sinonimi,
   nomi del codice, inglese/italiano ("tassa" -> "GST", "ristorante" -> "restaurant").
5. Se la memoria contraddice il codice, vale il codice: dillo e aggiorna con una nota nuova.

## Scrivere

Le modifiche ai file del progetto e i comandi che cambiano qualcosa vengono già annotati in automatico
(gratis; i comandi git no, li ricorda già git). Tu salvi solo
quello che il codice non dice: **il perché**.

Salva una nota (`add`) quando:
- l'utente spiega un motivo, un vincolo o chi ha deciso ("l'ha confermato il commercialista");
- scegli tra alternative (`decision`), trovi la causa di un bug (`bugfix`), scopri come funziona
  qualcosa di non ovvio (`discovery`), completi una funzionalità (`feature`) o un refactor (`refactor`).

Regole: titolo cercabile con le parole che useresti per ritrovarlo; racconto in 1-3 frasi;
fatti brevi e verificabili; niente segreti, password o dati personali.

Esempio:
```bash
python3 .claude/skills/memoria/mem.py add --type decision \
  --title "Order riceve INotifica nel costruttore invece di creare EmailSender" \
  --narrative "L'utente vuole poter passare da email a SMS senza toccare Order." \
  --facts "Order dipende da INotifica" "EmailSender e SmsSender implementano INotifica" \
  --files Order.cs Notifiche.cs
```

## A fine lavoro

Se hai modificato file, salva un `summary` (richiesta, cosa è fatto, cosa hai imparato, prossimi
passi). Se te ne dimentichi, lo Stop hook te lo ricorda una volta. Quando fai commit del lavoro,
includi anche `.claude/memory/*.jsonl`: nelle sessioni cloud è l'unico modo perché la memoria sopravviva.
