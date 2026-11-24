---
name: costruisci-e-rivedi
description: Sviluppa codice con due agent — un costruttore che scrive e un revisore che cerca problemi — che si passano il lavoro per massimo 3 giri, poi una verifica reale (build, test, app avviata). Usalo quando l'utente dice "costruisci e rivedi", "builder e reviewer", "fallo con revisione", o chiede di implementare una funzione/fix di codice partendo da una specifica e vuole che venga controllata prima della consegna.
---

# Costruisci e rivedi

```
Specifica ──▶ Costruttore ◀──▶ Revisore ──▶ Verifica ──▶ Resoconto
              (sempre lo stesso)  (max 3 giri)
```

Tu sei il **coordinatore**: non scrivi codice del lavoro e non fai tu la revisione. Lanci gli agent, passi loro il materiale giusto, conti i giri e riferisci all'utente.

Input: cosa va costruito (una riga, una specifica, una issue). Se manca, chiedilo.

---

## Passo 1 – Specifica: "come deve funzionare"

Prima di lanciare qualsiasi agent, serve una specifica scritta. Se l'utente ne ha data una completa, usala. Altrimenti scrivila tu leggendo il codice esistente, e mostrala.

Deve contenere:

1. **Cosa cambia** – in una o due righe.
2. **Come deve funzionare** – da 3 a 8 criteri di accettazione, ognuno verificabile: "dato X, quando Y, allora Z". Niente parole vaghe ("robusto", "pulito").
3. **Fuori ambito** – cosa non va toccato.
4. **Come si verifica** – il comando esatto di build e di test del progetto, e come si avvia l'app (trovali nel repo: README, file di progetto, CI).

Se un criterio dipende da una scelta che solo l'utente può fare, chiedi quella scelta — una domanda sola. Per il resto decidi tu e scrivi la decisione nella specifica.

## Passo 2 – Costruttore

Lancia **un** agent costruttore (tipo `general-purpose`) e **conserva il suo nome/ID**: servirà nei giri successivi.

Nel suo incarico metti:
- la specifica completa del Passo 1;
- i file e le cartelle da cui partire;
- le regole: restare nell'ambito, scrivere o aggiornare i test per ogni criterio, eseguire build e test prima di dichiarare finito, non fare commit né push;
- cosa deve restituire: elenco dei file modificati, esito reale di build e test (output, non un riassunto), e i criteri che non è riuscito a coprire.

## Passo 3 – Revisore

Lancia un agent revisore **nuovo a ogni giro** (così non è influenzato dal giro precedente).

Dagli:
- la specifica;
- il diff reale (`git diff`), non il riassunto del costruttore;
- **non** dargli le spiegazioni del costruttore né la tua opinione sul lavoro.

Chiedigli di cercare, in quest'ordine: criteri di accettazione non rispettati, bug e casi limite, errori non gestiti, problemi di sicurezza, test mancanti o che non provano nulla, modifiche fuori ambito.

Ogni problema va restituito così:

`[BLOCCANTE | MINORE] file:riga — cosa non va — scenario concreto in cui fallisce`

Un problema senza scenario concreto non è bloccante. Se non trova nulla di bloccante, deve dirlo esplicitamente.

## Passo 4 – Il giro

- **Nessun bloccante** → vai al Passo 5.
- **Ci sono bloccanti** → rimanda l'elenco **allo stesso costruttore** con SendMessage (non lanciarne uno nuovo: ha già il contesto e costa meno). Deve correggere ogni bloccante, rieseguire build e test, e rispondere punto per punto: corretto / non corretto e perché. Poi nuovo revisore (Passo 3).
- I **minori** si raccolgono e vanno nel resoconto; il costruttore li corregge solo se sono banali.

**Massimo 3 giri di revisione.** Tieni il conto e dillo all'utente a ogni giro: `Giro 2/3 — 2 bloccanti rimandati al costruttore`.

Se costruttore e revisore non sono d'accordo su un punto, non decidere a caso: controlla tu nel codice chi ha ragione, e se resta dubbio portalo all'utente.

## Passo 5 – Verifica reale

Lancia un agent verificatore nuovo, che **non legge il codice per giudicarlo: lo esegue**.

- Esegue i comandi di build e test della specifica e riporta l'output.
- Avvia davvero il programma e prova ogni criterio di accettazione:
  - app web → nel browser (Playwright), con uno screenshot per criterio;
  - CLI o servizio → lo lancia con input reali e riporta l'output;
  - libreria → un piccolo script che la chiama.
- Per ogni criterio: `PASS` o `FAIL` con la prova (output, screenshot, test).

Se un criterio fallisce e restano giri disponibili, rimandalo al costruttore come bloccante (conta come un giro). Se i giri sono finiti, fermati.

## Passo 6 – Resoconto

Riferisci all'utente, in quest'ordine:

1. **Esito** – consegnabile / non consegnabile, in una riga.
2. **Criteri** – ognuno con `PASS`/`FAIL` e la prova.
3. **Giri fatti** – quanti, e cosa ha trovato il revisore a ogni giro.
4. **Rimasto aperto** – minori non corretti, bloccanti non risolti, cose che non è stato possibile verificare e perché.
5. **File modificati.**

Poi chiedi se fare commit e push. Non farli prima.

---

## Regole di stop

- **3 giri esauriti con bloccanti ancora aperti** → fermati. Non dichiarare finito: elenca cosa resta e di' se il problema è nella specifica (criterio ambiguo o irrealizzabile) o nel codice.
- **Build o test che non partono per cause esterne** (dipendenza mancante, rete, credenziali) → fermati e dillo; non è un problema che il costruttore può correggere.
- **Il lavoro si rivela più grande della specifica** → fermati e proponi di dividerlo.

## Cosa non fare

- Non scrivere tu il codice "per fare prima": salta la revisione.
- Non passare al revisore il riassunto del costruttore al posto del diff.
- Non lanciare un costruttore nuovo a ogni giro.
- Non dire `PASS` senza aver visto l'output.
- Non disattivare o saltare un test per far passare la verifica.
- Non fare un quarto giro "perché manca poco".

## Quando non usarla

Modifiche da una riga, rinomine, testi: fai direttamente. Tre agent costano più del lavoro.
