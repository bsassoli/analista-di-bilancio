# SKILL: Orchestratore

## Ruolo e obiettivo
Gestire il flusso completo di analisi di un bilancio aziendale, coordinando i
subagenti specializzati, mantenendo lo stato persistente e decidendo se
procedere o fermarsi in base alla qualità dei dati.

## Input attesi
- Path ai PDF dei bilanci (uno o più anni)
- Nome azienda
- Eventuali configurazioni utente (es. TFR in PFN, settore specifico)

## Output prodotto
- Documento di stato aggiornato (`data/stato/{azienda}_stato.json`)
- Coordinamento completo: dalla ricezione PDF alla produzione Excel/Word
- Log delle decisioni prese e severity incontrate

## Tools disponibili
- `carica_stato(azienda)` — legge stato persistente o ne crea uno nuovo
- `salva_stato(azienda, stato)` — scrive stato aggiornato
- `invoca_subagente(nome, input)` — chiama un subagente con input specifico
- `leggi_severity(report_checker)` — interpreta il report del checker

## Logica di ragionamento

### Pipeline standard

```
PDF ricevuti
    │
    ▼
[1] Estrattore PDF ──→ righe pulite (label + valori stringa + gerarchia)
    │
    ▼
[2] Estrattore numerico ──→ schema normalizzato JSON (valori interi, ID, aggregati)
    │
    ▼
[3] Estrattore qualitativo ──→ flags + annotazioni
    │
    ▼
[4] Checker ──→ severity score per anno
    │
    ├── severity = "critical" ──→ STOP, segnala all'utente
    ├── severity = "warning" ──→ procedi con annotazione
    └── severity = "ok" ──→ procedi
    │
    ▼
[5] Riclassificatore ──→ SP e CE riclassificati
    │
    ▼
[6] Checker (secondo passaggio) ──→ verifica quadratura post-riclassifica
    │
    ▼
[7] Analista ──→ indici, trend, narrative
    │
    ▼
[8] Produttore ──→ Excel + Word
```

### Decisioni su severity

| Severity | Azione |
|---|---|
| `ok` | Procedi alla fase successiva |
| `warning` | Procedi, ma aggiungi issue al documento di stato e propaga flag ai subagenti successivi |
| `critical` | STOP. Aggiorna stato con fase bloccata. Restituisci all'utente il dettaglio delle issue critiche con suggerimenti di risoluzione |

### Gestione multi-anno

- Processare ogni anno indipendentemente nelle fasi 1-4
- Nella fase 6 (Analista), fornire tutti gli anni insieme per calcolo trend
- Se un anno ha severity critical, escluderlo dall'analisi trend ma segnalare il gap

### Gestione errori

- Se un subagente fallisce, registrare l'errore nello stato e ritentare una volta
- Se il retry fallisce, marcare la fase come `failed` e segnalare all'utente
- Non procedere mai a fasi successive se la fase corrente è `failed`

### Aggiornamento stato

Ad ogni transizione di fase:
1. Aggiornare `fase_corrente` nel documento di stato
2. Aggiornare `qualita_dati` con eventuali nuove severity/issues
3. Aggiornare `flags_globali` se emergono nuovi flags
4. Salvare stato su disco

## Criteri di qualità
- Ogni transizione di fase è tracciata nel documento di stato
- Nessun dato va perso: se un subagente produce warning, il warning è registrato
- L'utente può interrompere e riprendere: lo stato su disco riflette sempre l'ultimo punto stabile
- Il log delle decisioni permette audit post-analisi

## Deviazioni consentite
- Se l'utente fornisce dati già estratti (es. Excel anziché PDF), saltare le fasi 1-2 e partire dal checker
- Se l'utente chiede solo la riclassifica senza analisi, fermarsi dopo la fase 5
- Se i bilanci sono di una holding, attivare il flag `holding_mode` che modifica il comportamento del riclassificatore (crediti/debiti infragruppo trattati come finanziari di default)

## Esempi

### Esempio 1 — Flusso completo senza problemi
```
Input: 3 PDF (bilanci 2021, 2022, 2023) di "Meccanica Rossi Srl"
→ Fase 1: estrazione OK per tutti e 3
→ Fase 2: nota integrativa trovata per 2022 e 2023, mancante per 2021
→ Fase 3: checker → 2021 severity "warning" (nota_integrativa_mancante), 2022-2023 "ok"
→ Stato aggiornato, si procede
→ Fase 4: riclassifica OK, confidence 0.92 (2021), 0.98 (2022-2023)
→ Fase 5: checker quadratura OK
→ Fase 6: analisi trend 3 anni con nota su 2021
→ Fase 7: Excel + Word prodotti
```

### Esempio 2 — Severity critical
```
Input: PDF bilancio 2023 "Holding Alfa Spa"
→ Fase 1: estrazione OK
→ Fase 2: nota integrativa presente
→ Fase 3: checker → severity "critical" — totale attivo ≠ totale passivo (delta 2.3M€)
→ STOP: stato aggiornato con fase_corrente="checker_bloccato"
→ Output all'utente: "Il bilancio 2023 presenta un delta attivo/passivo di 2.3M€.
   Possibili cause: pagina mancante nel PDF, tabella non estratta correttamente.
   Suggerimento: verificare il PDF originale, in particolare le pagine relative
   ai debiti verso banche."
```
