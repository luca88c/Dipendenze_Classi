---
name: crea-playbook
description: Trasforma un lavoro ripetitivo dell'utente in un playbook scritto (una cartella [job-name] con SKILL.md e files/) che Claude può eseguire da solo. Usalo quando l'utente dice "crea un playbook", "trasforma questo lavoro in una skill", "aggiungi la definition of done" o "salva questo nella toolbox".
---

# Crea playbook

Tre fasi, in ordine. Ogni fase si può anche lanciare da sola se il playbook esiste già.

- **Fase 1 – Intervista e SKILL.md**: dal nulla a un playbook eseguibile.
- **Fase 2 – Definition of done**: controlli verificabili da eseguire a ogni esecuzione.
- **Fase 3 – Toolbox**: salvare script/template/email/checklist riusabili in `[job-name]/files/`.

Input iniziale: il lavoro descritto in una riga. Se l'utente non l'ha dato, la prima domanda è proprio questa.

---

## Fase 1 – Intervista e SKILL.md

### Regole dell'intervista
- Fai **una domanda alla volta** e aspetta la risposta.
- **Non scrivere nessun file** finché non hai fatto **almeno otto domande** **e** l'utente ha detto che avete finito.
- Copri tutti questi punti (una o più domande ciascuno):
  1. cosa fa partire il lavoro, e quanto spesso
  2. gli input, ed esattamente dove si trova ognuno
  3. i passi nell'ordine in cui l'utente li fa davvero
  4. ogni decisione che prende, e la regola dietro
  5. cosa controlla prima di dire che ha finito
  6. i casi limite che sono già andati storti in passato
  7. il tono o lo standard che il risultato deve rispettare
  8. com'è fatta una versione sbagliata
- Se una risposta è vaga ("dipende", "a occhio"), chiedi la regola concreta o un esempio.

### Scrittura
Quando potresti eseguire il lavoro senza l'utente, crea la cartella `[job-name]` (nome breve, minuscolo, con trattini) e dentro `SKILL.md` con queste sezioni:

1. **Purpose** – una riga.
2. **When to use this** – cosa lo fa partire e con che frequenza.
3. **Inputs** – ogni input e dove si trova esattamente (percorso, URL, cartella, persona).
4. **Steps** – numerati, linguaggio semplice, niente gergo.
5. **Decisions** – nella forma "Se X allora Y".
6. **Definition of done** – vedi Fase 2.
7. **Edge cases** – cosa è andato storto prima e come gestirlo.

Includi anche lo standard di tono e la descrizione di "versione sbagliata" (dentro Steps, Decisions o Edge cases, dove servono).

### Chiusura
Mostra **l'intero file** all'utente, poi fai esattamente due domande:
1. Cosa ho sbagliato?
2. Cosa ti sei dimenticato di dirmi?

Applica le correzioni e rimostra il file.

---

## Fase 2 – Definition of done

Aggiungi (o riscrivi) la sezione **Definition of done** nel `SKILL.md` di `[job-name]`.

### Come scrivere i controlli
- Da **5 a 10** controlli, **specifici per questo lavoro**.
- Ogni controllo deve essere verificabile con una prova esterna alla tua opinione:
  - un numero ricondotto al suo file sorgente
  - un link che si apre
  - uno screenshot del risultato renderizzato
  - un test che gira
  - un'affermazione abbinata a una citazione
  - un conteggio
  - un valore confrontato con un file di riferimento
- **Vietate** parole di qualità vaghe come "chiaro", "professionale", "di alta qualità".

Formato consigliato di ogni controllo:
`N. [cosa si verifica] — Prova: [come si verifica e su quale file/link/test]`

### Da ora in poi, ogni volta che finisci questo lavoro, prima di mostrare qualsiasi cosa
1. Esegui ogni controllo.
2. Correggi quello che fallisce.
3. Riesegui i controlli.
4. Dai un esito di una riga per ciascun controllo: `PASS` o `FAIL`, con la prova usata.
5. Elenca quello che non hai potuto verificare e perché, invece di darlo per superato.

**Regola di stop:** se **più di due** controlli falliscono al primo giro, fermati. Non correggere l'output: di' all'utente quale parte del processo (quale passo, decisione o input del SKILL.md) ha causato i fallimenti.

Copia anche queste regole dentro il `SKILL.md` del playbook, sotto la Definition of done, così valgono a ogni esecuzione.

---

## Fase 3 – Toolbox

Si applica allo script / template / email / checklist appena prodotto, **se l'utente ne avrà bisogno di nuovo**.

1. Salvalo in `[job-name]/files/` con un nome descrittivo, es. `numbers-pull.py` o `update-template.md`. **Niente date o numeri di versione** nel nome.
2. Trasforma i dati specifici dell'utente in **segnaposto tra parentesi quadre** (es. `[nome-cliente]`) così è riusabile, e lascia **un esempio compilato** sotto, come riferimento.
3. Aggiorna `SKILL.md` in modo che il passo che ne ha bisogno citi il file per nome e dica **quando usarlo e quando no**.
4. Aggiungi una riga a `[job-name]/files/INDEX.md`: nome del file, a cosa serve, data di oggi.
   Formato: `- \`nome-file.ext\` — a cosa serve — AAAA-MM-GG`

**Non salvare:** output usati una volta sola, qualsiasi cosa contenga una password o una API key, bozze che l'utente non ha approvato.

Poi **riesegui l'intero lavoro da zero** e di' all'utente:
- quali file salvati hai usato;
- quali parti hai ricostruito da zero.

Tutto ciò che hai ricostruito è un candidato per la toolbox: di' cosa salveresti come prossimo file.

---

## Se non puoi scrivere file

Non fingere di averlo fatto. Stampa in chat il contenuto **completo** del file, indica il **nome esatto** e **dove va** nella cartella, e ricorda all'utente di **sostituire la vecchia copia caricata** invece di aggiungerne una seconda.

## Struttura finale attesa

```
[job-name]/
├── SKILL.md
└── files/
    ├── INDEX.md
    └── [file-riusabili]
```
