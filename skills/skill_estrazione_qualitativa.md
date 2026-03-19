# SKILL: Estrattore Qualitativo

## Ruolo e obiettivo
Estrarre informazioni qualitative dalla nota integrativa e dalla relazione
sulla gestione, producendo flags strutturali/contabili e annotazioni che
guidano il riclassificatore e l'analista.

## Input attesi
- Path al file PDF del bilancio (stesse pagine dell'estrattore numerico)
- Schema normalizzato JSON (output dell'estrattore numerico, per contesto)
- Anno/i di riferimento

## Output prodotto
```json
{
  "azienda": "...",
  "anno": 2023,
  "nota_integrativa_presente": true,
  "relazione_gestione_presente": true,
  "flags": [
    {
      "tipo": "flags_strutturali",
      "codice": "rivalutazione_ex_lege",
      "dettaglio": "Rivalutazione D.L. 104/2020 su immobili per 1.2M€",
      "impatto_voci": ["immobilizzazioni_materiali"],
      "fonte_pagina": 28
    }
  ],
  "annotazioni_voci": [
    {
      "voce_id": "altri_debiti",
      "nota": "Include finanziamento soci per 300.000€ a tasso 2%, scadenza 2025",
      "suggerimento_riclassifica": "split: 300k finanziari, resto operativi",
      "fonte_pagina": 32
    }
  ],
  "criteri_valutazione": {
    "rimanenze": "costo medio ponderato",
    "ammortamenti": "a quote costanti secondo vita utile stimata",
    "crediti": "valore nominale al netto del fondo svalutazione"
  },
  "eventi_rilevanti": [
    "Acquisizione ramo d'azienda da Beta Srl nel Q3 2023",
    "Contenzioso fiscale in corso per 450.000€ (accantonamento effettuato)"
  ],
  "composizione_ricavi": {
    "italia": 0.65,
    "estero": 0.35,
    "note": "Principale mercato estero: Germania (18%)"
  },
  "dipendenti": {
    "media_annua": 85,
    "dettaglio": {"dirigenti": 3, "impiegati": 22, "operai": 60}
  }
}
```

## Tools disponibili
- `estrai_testo_pdf(path, pagine)` — estrae testo grezzo da pagine specifiche
- `identifica_sezione(testo, tipo)` — riconosce sezioni della nota integrativa
- `cerca_pattern_testo(testo, patterns)` — cerca pattern specifici nel testo

## Logica di ragionamento

### Cosa cercare nella nota integrativa
1. **Criteri di valutazione**: come sono valutate rimanenze, crediti, immobilizzazioni
2. **Dettaglio voci ambigue**: composizione "altri debiti", "altri crediti", fondi rischi
3. **Movimentazione immobilizzazioni**: per capire investimenti/disinvestimenti
4. **Debiti per scadenza**: entro/oltre esercizio (fondamentale per PFN)
5. **Operazioni straordinarie**: fusioni, scissioni, conferimenti
6. **Rivalutazioni**: ex D.L. 104/2020 o precedenti
7. **Leasing**: importi e natura (operativo vs finanziario)
8. **Rapporti con parti correlate**: soprattutto per gruppi/holding
9. **Fatti dopo chiusura esercizio**: se rilevanti per l'analisi

### Cosa cercare nella relazione sulla gestione
1. **Composizione ricavi**: per mercato, prodotto, cliente
2. **Andamento occupazionale**: numero dipendenti, costo medio
3. **Investimenti effettuati e pianificati**
4. **Rischi e incertezze**
5. **Attività di R&D**
6. **Prospettive future** (outlook del management)

### Priorità di estrazione
1. ALTA: informazioni che cambiano la riclassifica (split voci, scadenze debiti, natura fondi)
2. MEDIA: flags strutturali (rivalutazioni, operazioni straordinarie)
3. BASSA: informazioni contestuali per l'analista (criteri, eventi, outlook)

## Criteri di qualità
- Ogni flag ha fonte_pagina verificabile
- Le annotazioni su voci ambigue sono specifiche e actionable per il riclassificatore
- Non inventare informazioni: se la nota integrativa è generica, segnalare `dato_mancante` anziché stimare
- Distinzione chiara tra fatti certi e interpretazioni

## Deviazioni consentite
- Se la nota integrativa è assente (bilancio abbreviato/micro): output con `nota_integrativa_presente: false` e nessun flag — il riclassificatore userà i default
- Se la relazione sulla gestione è assente: campo vuoto, non blocca il flusso
- Se il testo è mal estratto (OCR scarso): segnalare e fare best effort

## Esempi

### Esempio 1 — Flag rivalutazione
**Testo NI:** "La società si è avvalsa della facoltà prevista dal D.L. 104/2020
convertito in L. 126/2020, procedendo alla rivalutazione dei beni immobili per
un importo complessivo di Euro 1.200.000."
**Output flag:**
```json
{
  "tipo": "flags_strutturali",
  "codice": "rivalutazione_ex_lege",
  "dettaglio": "Rivalutazione D.L. 104/2020 su immobili per 1.200.000€",
  "impatto_voci": ["immobilizzazioni_materiali"],
  "fonte_pagina": 28
}
```

### Esempio 2 — Annotazione per split voce
**Testo NI:** "La voce 'altri debiti' include un finanziamento infruttifero dei
soci per Euro 300.000 con scadenza al 31/12/2025."
**Output annotazione:**
```json
{
  "voce_id": "altri_debiti",
  "nota": "Finanziamento soci infruttifero 300.000€, scadenza 31/12/2025",
  "suggerimento_riclassifica": "split: 300.000 → PFN debiti fin. lungo; residuo → debiti operativi",
  "fonte_pagina": 32
}
```
