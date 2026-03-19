# SKILL: Checker

## Ruolo e obiettivo
Validare la coerenza e completezza dei dati estratti e riclassificati,
producendo un severity score per anno che guida le decisioni dell'orchestratore.

## Input attesi
- Schema normalizzato JSON (output estrattore numerico)
- Flags e annotazioni (output estrattore qualitativo)
- SP e CE riclassificati (se fase post-riclassifica)
- Anni di riferimento

## Output prodotto
```json
{
  "azienda": "...",
  "tipo_check": "pre_riclassifica|post_riclassifica",
  "risultati_per_anno": {
    "2023": {
      "severity": "ok|warning|critical",
      "score": 0.95,
      "checks": [
        {
          "codice": "SP_QUADRATURA",
          "esito": "pass|warn|fail",
          "dettaglio": "Totale attivo = Totale passivo (delta: 0€)",
          "severity_contributo": "ok"
        }
      ]
    }
  },
  "checks_cross_anno": [
    {
      "codice": "CONTINUITA_VOCI",
      "esito": "warn",
      "dettaglio": "Voce 'crediti_verso_controllate' presente nel 2022 ma assente nel 2023",
      "severity_contributo": "warning"
    }
  ]
}
```

## Tools disponibili
- `verifica_quadratura(attivo, passivo, tolleranza)` — controlla totali SP
- `verifica_utile(ce_utile, sp_utile)` — confronta utile CE con utile in PN
- `calcola_variazione_yoy(valore_n, valore_n1)` — calcola variazione percentuale
- `confronta_schemi(schema_anno_n, schema_anno_n1)` — identifica voci apparse/scomparse

## Logica di ragionamento

### Checks pre-riclassifica (sullo schema normalizzato)

| Codice | Descrizione | Severity se fallisce |
|---|---|---|
| SP_QUADRATURA | Totale attivo = Totale passivo | critical se delta > 1% totale; warning se delta ≤ 1% |
| CE_UTILE_SP | Utile netto CE = Utile in PN (SP) | warning (può essere legittimo: distribuzione dividendi infra-anno) |
| VOCI_ZERO | Voci tipicamente non-zero che risultano 0 | warning |
| VOCI_NEGATIVE | Voci che non dovrebbero essere negative | warning (es. immobilizzazioni negative) |
| COMPLETEZZA_SP | Presenti almeno le macro-voci SP | critical se mancano >2 macro-voci |
| COMPLETEZZA_CE | Presenti almeno le macro-voci CE | critical se mancano >2 macro-voci |
| DUPLICATI | Voci duplicate con stesso ID | critical |
| FORMATO_NUMERI | Tutti i valori sono numerici validi | critical se >5% non parsabili |

### Checks post-riclassifica

| Codice | Descrizione | Severity se fallisce |
|---|---|---|
| RICLASS_QUADRATURA | SP riclassificato quadra | critical |
| RICLASS_UTILE | Utile netto CE riclassificato = utile normalizzato | warning |
| RICLASS_COMPLETEZZA | Nessun aggregato riclassificato vuoto inatteso | warning |
| RICLASS_CONFIDENCE | Confidence score del riclassificatore | critical se < 0.5; warning se < 0.8 |
| VOCI_NON_MAPPATE | Voci non mappate dal riclassificatore | warning se peso < 1%; critical se peso > 5% |
| CCON_COERENZA | CCON positivo (tipico per PMI manifatturiera) | warning se negativo (potrebbe essere legittimo) |
| PFN_SEGNO | PFN positiva = indebitamento netto | ok (informativo, non errore) |

### Checks cross-anno

| Codice | Descrizione | Severity |
|---|---|---|
| CONTINUITA_VOCI | Stesse voci presenti in tutti gli anni | warning se voce scompare |
| VARIAZIONE_ANOMALA | Variazione YoY > 50% su voce principale | warning |
| COERENZA_TREND | Trend coerenti (es. ricavi crescono ma crediti calano molto) | warning |
| ANNO_MANCANTE | Gap nella serie storica | warning |

### Calcolo severity complessiva per anno
- `critical`: almeno un check con esito `fail` e severity `critical`
- `warning`: almeno un check con esito `warn`, nessun critical
- `ok`: tutti i check passati

### Score numerico (0-1)
- Partenza: 1.0
- Ogni critical: −0.3
- Ogni warning: −0.05
- Floor: 0.0

## Criteri di qualità
- Ogni check ha un codice univoco e un dettaglio leggibile
- Il severity score è deterministico e riproducibile
- I checks sono indipendenti (nessun check dipende dall'esito di un altro)
- False positive accettabili per warning, non per critical

## Deviazioni consentite
- Per bilanci micro-impresa, rilassare COMPLETEZZA_SP/CE (meno voci attese)
- Per holding, CCON_COERENZA non si applica (CCON spesso negativo o non significativo)
- Se l'utente segnala che un warning è noto e accettabile, l'orchestratore può sovrascrivere

## Esempi

### Esempio 1 — Check SP_QUADRATURA pass
```json
{
  "codice": "SP_QUADRATURA",
  "esito": "pass",
  "dettaglio": "Totale attivo (15.234.120) = Totale passivo (15.234.120), delta: 0€",
  "severity_contributo": "ok"
}
```

### Esempio 2 — Check SP_QUADRATURA fail
```json
{
  "codice": "SP_QUADRATURA",
  "esito": "fail",
  "dettaglio": "Totale attivo (15.234.120) ≠ Totale passivo (12.987.650), delta: 2.246.470€ (14.7%)",
  "severity_contributo": "critical"
}
```
