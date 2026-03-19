# SKILL: Analista

## Ruolo e obiettivo
Calcolare indici di bilancio, analizzare trend pluriennali e produrre narrative
interpretative strutturate a partire dai dati riclassificati.

## Input attesi
- SP e CE riclassificati per tutti gli anni disponibili
- Flags e annotazioni dall'estrattore qualitativo
- Documento di stato con qualità dati per anno

## Output prodotto
```json
{
  "azienda": "...",
  "anni": [2019, 2020, 2021, 2022, 2023],
  "indici": {
    "redditivita": {
      "ROE": {"2023": 0.12, "2022": 0.10, "...": "..."},
      "ROI": {},
      "ROS": {},
      "ROA": {}
    },
    "struttura": {
      "indice_indipendenza_finanziaria": {},
      "rapporto_indebitamento": {},
      "copertura_immobilizzazioni": {},
      "pfn_ebitda": {},
      "pfn_pn": {}
    },
    "liquidita": {
      "current_ratio": {},
      "quick_ratio": {},
      "giorni_crediti": {},
      "giorni_debiti": {},
      "giorni_magazzino": {},
      "ciclo_cassa": {}
    },
    "efficienza": {
      "fatturato_per_dipendente": {},
      "costo_personale_su_va": {},
      "incidenza_ammortamenti": {}
    }
  },
  "trend": [
    {
      "indice": "ROE",
      "direzione": "crescente",
      "variazione_periodo": 0.04,
      "significativo": true,
      "nota": "Miglioramento costante guidato da crescita ROS"
    }
  ],
  "alert": [
    {
      "tipo": "rischio",
      "indice": "pfn_ebitda",
      "valore": 4.5,
      "soglia": 4.0,
      "messaggio": "PFN/EBITDA superiore a 4x — livello di indebitamento elevato"
    }
  ],
  "narrative": {
    "sintesi": "...",
    "redditivita": "...",
    "struttura_finanziaria": "...",
    "liquidita": "...",
    "conclusioni": "..."
  }
}
```

## Tools disponibili
- `calcola_indice(formula, valori)` — calcola un singolo indice
- `calcola_trend(serie, metodo)` — CAGR, media mobile, regressione lineare
- `valuta_soglia(indice, valore, settore)` — confronta con benchmark di settore
- `genera_narrative(indici, trend, flags)` — supporto alla generazione testo

## Logica di ragionamento

### Indici calcolati

#### Redditività
| Indice | Formula | Interpretazione |
|---|---|---|
| ROE | Utile netto / PN medio | Rendimento del capitale proprio |
| ROI | EBIT / Capitale investito netto | Rendimento del capitale investito |
| ROS | EBIT / Ricavi netti | Marginalità operativa |
| ROA | EBIT / Totale attivo | Rendimento delle attività |
| EBITDA margin | EBITDA / Ricavi netti | Margine operativo lordo |

#### Struttura finanziaria
| Indice | Formula | Soglie indicative |
|---|---|---|
| Indipendenza finanziaria | PN / Totale passivo | > 0.33 buono, < 0.20 critico |
| Rapporto indebitamento | (PFN + Deb. op.) / PN | < 2 buono, > 4 critico |
| Copertura immobilizzazioni | (PN + Deb. fin. lungo) / CFN | > 1 buono |
| PFN/EBITDA | PFN / EBITDA | < 3 buono, 3-4 attenzione, > 4 critico |
| PFN/PN | PFN / PN | < 1 buono, > 2 critico |

#### Liquidità e ciclo commerciale
| Indice | Formula | Note |
|---|---|---|
| Current ratio | (Crediti comm. + Rimanenze + Liquidità) / Deb. breve | > 1.5 buono |
| Quick ratio | (Crediti comm. + Liquidità) / Deb. breve | > 1 buono |
| Giorni crediti | (Crediti comm. / Ricavi) × 365 | Settore-dipendente |
| Giorni debiti | (Debiti fornitori / Acquisti) × 365 | |
| Giorni magazzino | (Rimanenze / Costo venduto) × 365 | |
| Ciclo cassa | GG crediti + GG magazzino − GG debiti | Più basso = meglio |

#### Efficienza
| Indice | Formula | Note |
|---|---|---|
| Fatturato per dipendente | Ricavi / N. dipendenti | Se dato disponibile |
| Costo personale / VA | Costi personale / Valore aggiunto | < 0.60 buono per manifattura |
| Incidenza ammortamenti | Ammortamenti / Ricavi | Intensità di capitale |

### Analisi trend
- Calcolare variazione YoY per ogni indice
- Identificare trend significativi (≥ 3 anni stessa direzione)
- Calcolare CAGR su periodo completo per ricavi e margini
- Evidenziare discontinuità (anno anomalo rispetto al trend)
- Correlare con flags (es. calo ROE in anno di rivalutazione → effetto tecnico su PN)

### Soglie e alert
- Ogni indice ha soglie di riferimento per PMI manifatturiere italiane
- Alert generati quando un indice supera soglia critica
- Alert contestualizzati: un PFN/EBITDA alto in anno di investimento è diverso da uno strutturale
- Usare i flags per contestualizzare (es. `cambio_perimetro` spiega discontinuità)

### Narrative
L'analista produce testi strutturati per sezione:
1. **Sintesi**: 3-5 righe di overview
2. **Redditività**: andamento margini, leve principali
3. **Struttura finanziaria**: equilibrio fonti/impieghi, sostenibilità debito
4. **Liquidità**: ciclo commerciale, tensione finanziaria
5. **Conclusioni**: punti di forza, aree di attenzione, outlook

Le narrative devono:
- Essere basate su dati, mai generiche
- Citare i numeri specifici
- Spiegare il "perché" quando possibile (usando flags e annotazioni)
- Segnalare dove i dati sono stimati o incompleti

## Criteri di qualità
- Tutti gli indici calcolabili sono calcolati (nessun indice mancante se i dati ci sono)
- Nessuna divisione per zero — gestire denominatori nulli con "n/a"
- Trend coerenti con i dati sottostanti
- Narrative coerenti con gli indici (non contraddittorie)
- Alert non ridondanti

## Deviazioni consentite
- Se dati insufficienti per un indice (es. n. dipendenti non disponibile), omettere con nota
- Per holding: omettere indici di ciclo commerciale (giorni crediti/debiti/magazzino non significativi)
- Se un solo anno disponibile: niente trend, solo snapshot
- Se flags indicano discontinuità (fusione, cessione ramo): analisi trend spezzata pre/post evento

## Esempi

### Esempio 1 — Alert su PFN/EBITDA
```json
{
  "tipo": "rischio",
  "indice": "pfn_ebitda",
  "valore": 4.5,
  "soglia": 4.0,
  "messaggio": "PFN/EBITDA di 4.5x, superiore alla soglia di attenzione (4.0x). L'indebitamento netto è elevato rispetto alla capacità di generare cassa operativa. Nota: nel 2023 effettuato investimento straordinario (flag: investimento_significativo) che ha incrementato la PFN di 1.2M€. Al netto, PFN/EBITDA sarebbe 3.2x."
}
```

### Esempio 2 — Narrativa redditività
"La redditività operativa mostra un trend positivo nel triennio 2021-2023, con
ROS in crescita dal 5.2% al 7.8% (+2.6 pp). Il miglioramento è guidato
dalla riduzione dell'incidenza dei costi per servizi (dal 32% al 28% dei ricavi),
a fronte di ricavi sostanzialmente stabili (CAGR +1.2%). L'EBITDA margin si
attesta al 12.3% nel 2023, in linea con la mediana di settore. Il ROE del 12%
beneficia della contenuta leva finanziaria (PFN/PN = 0.8x)."
