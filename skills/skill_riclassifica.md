# SKILL: Riclassificatore di Bilancio

## Ruolo e obiettivo
Trasformare lo schema normalizzato estratto dal bilancio (SP e CE) nello schema
riclassificato target, applicando il criterio finanziario per lo SP e il criterio
a valore aggiunto per il CE, gestendo deviazioni e voci non standard.

## Input attesi
- Schema normalizzato JSON: lista di voci con struttura `{id, label, livello, aggregato, valore, fonte_riga_bilancio, non_standard, flags, note}`
- Flags globali dall'orchestratore (es. `rivalutazione_ex_lege`, `cambio_perimetro`)
- Anno/i di riferimento
- Eventuale output del checker (severity e issues)

## Output prodotto
```json
{
  "azienda": "...",
  "anno": 2023,
  "sp_riclassificato": {
    "attivo": {
      "capitale_fisso_netto": {
        "totale": 0,
        "dettaglio": {
          "immobilizzazioni_materiali_nette": 0,
          "immobilizzazioni_immateriali_nette": 0,
          "immobilizzazioni_finanziarie": 0
        }
      },
      "ccon": {
        "totale": 0,
        "dettaglio": {
          "crediti_commerciali": 0,
          "rimanenze": 0,
          "altri_crediti_operativi": 0,
          "debiti_operativi_sottratti": 0
        }
      },
      "altre_attivita_non_operative": {
        "totale": 0,
        "dettaglio": {
          "crediti_finanziari": 0,
          "attivita_fiscali_differite": 0
        }
      }
    },
    "passivo": {
      "patrimonio_netto": {
        "totale": 0,
        "dettaglio": {
          "capitale_sociale": 0,
          "riserve": 0,
          "utile_perdita_esercizio": 0
        }
      },
      "pfn": {
        "totale": 0,
        "dettaglio": {
          "debiti_finanziari_lungo": 0,
          "debiti_finanziari_breve": 0,
          "disponibilita_liquide_sottratte": 0
        }
      },
      "debiti_operativi": {
        "totale": 0,
        "nota": "Alimentano CCON, qui per quadratura"
      }
    },
    "quadratura": {
      "totale_attivo": 0,
      "totale_passivo": 0,
      "delta": 0,
      "ok": true
    }
  },
  "ce_riclassificato": {
    "ricavi_netti": 0,
    "costi_materie_prime_merci": 0,
    "valore_aggiunto_industriale": 0,
    "costi_servizi_godimento": 0,
    "costi_personale": 0,
    "ebitda": 0,
    "ammortamenti_svalutazioni": 0,
    "ebit": 0,
    "proventi_oneri_finanziari": 0,
    "ebt": 0,
    "imposte": 0,
    "utile_netto": 0
  },
  "deviazioni": [],
  "voci_non_mappate": [],
  "confidence": 0.0
}
```

## Tools disponibili
- `calcola_subtotale(voci, ids)` — somma valori di un subset di voci
- `verifica_quadratura(attivo, passivo, tolleranza)` — controlla SP
- `cerca_voce_schema(schema, pattern)` — fuzzy match su label/id
- `applica_mapping(voce, regola)` — assegna voce a categoria target

## Logica di ragionamento

### Mapping SP — Criterio finanziario

Il criterio finanziario classifica le voci per **tempo di conversione in cassa**:
- **Capitale fisso netto**: attività che restano investite oltre 12 mesi
- **Capitale circolante**: attività/passività che si convertono entro 12 mesi
- **PFN**: debiti finanziari netti (debiti finanziari − liquidità)

#### Regole di mapping SP (dalla voce civilistica alla voce riclassificata)

| Voce civilistica (rif. art. 2424 CC) | Destinazione riclassificata | Note |
|---|---|---|
| B.I — Immobilizzazioni immateriali | CFN → Imm. immateriali nette | Al netto del fondo ammortamento |
| B.II — Immobilizzazioni materiali | CFN → Imm. materiali nette | Al netto del fondo ammortamento |
| B.III — Immobilizzazioni finanziarie | CFN → Imm. finanziarie | Partecipazioni, crediti > 12m |
| B.III — Crediti finanziari esigibili entro | Altre attività → Crediti finanziari | Riclassificare da fisso a circolante |
| C.I — Rimanenze | CCON → Rimanenze | |
| C.II.1 — Crediti verso clienti | CCON → Crediti commerciali | Solo quota entro esercizio |
| C.II.1 — Crediti verso clienti oltre | CFN → Imm. finanziarie | Quota oltre 12m va in fisso |
| C.II.2 — Crediti verso controllate | Valutare caso per caso | Commerciali → CCON, finanziari → Altre att. |
| C.II.4bis — Crediti tributari | CCON → Altri crediti operativi | |
| C.II.4ter — Imposte anticipate | Altre attività → Att. fiscali differite | |
| C.II.5 — Crediti verso altri | CCON → Altri crediti operativi | Salvo natura finanziaria |
| C.III — Attività finanziarie non immobilizzate | PFN (in diminuzione) o Altre att. | Titoli liquidabili → riducono PFN |
| C.IV — Disponibilità liquide | PFN → Disponibilità liquide (sottratte) | Riducono la PFN |
| D — Ratei e risconti attivi | CCON → Altri crediti operativi | Salvo natura finanziaria |
| A — Patrimonio netto (tutte le voci) | PN | Incluso utile/perdita esercizio |
| B — Fondi rischi e oneri | Valutare natura | TFR-like → PFN lungo; operativi → Debiti op. |
| C — TFR | Debiti operativi | Alcuni analisti lo mettono in PFN lungo |
| D — Debiti v/banche entro | PFN → Debiti fin. breve | |
| D — Debiti v/banche oltre | PFN → Debiti fin. lungo | |
| D — Debiti v/obbligazionisti | PFN → lungo o breve per scadenza | |
| D — Debiti v/soci per finanziamenti | PFN → lungo o breve per scadenza | |
| D — Debiti v/altri finanziatori | PFN → lungo o breve per scadenza | |
| D — Debiti v/fornitori | Debiti operativi (alimentano CCON) | |
| D — Debiti tributari | Debiti operativi | |
| D — Debiti v/istituti previdenziali | Debiti operativi | |
| D — Acconti ricevuti | Debiti operativi | |
| D — Altri debiti | Valutare natura | Operativi → Deb. op.; finanziari → PFN |
| E — Ratei e risconti passivi | Debiti operativi | Salvo natura finanziaria |

#### Casi speciali SP
- **Leasing operativo** (flag `leasing_operativo_rilevante`): se il bilancio è pre-IFRS16 o in OIC con leasing operativo significativo, considerare la capitalizzazione pro-forma (aggiungere asset in CFN e debito in PFN)
- **Rivalutazione ex lege** (flag `rivalutazione_ex_lege`): segnalare nelle note che il CFN include rivalutazioni; non modificare il valore ma annotare per l'analista
- **Crediti/debiti infragruppo**: nelle holding, distinguere commerciali da finanziari. Se non chiaro dalla nota integrativa, classificare come finanziari e flaggare `dato_stimato`
- **Fondi rischi**: default → debiti operativi. Se la nota integrativa indica natura finanziaria (es. fondo per derivati), → PFN

### Mapping CE — Criterio a valore aggiunto

| Voce civilistica (rif. art. 2425 CC) | Destinazione riclassificata | Note |
|---|---|---|
| A.1 — Ricavi vendite e prestazioni | Ricavi netti | |
| A.2 — Variazione rimanenze prodotti | Ricavi netti (rettifica) | Sommare algebricamente |
| A.3 — Variazione lavori in corso | Ricavi netti (rettifica) | |
| A.4 — Incrementi immobilizzazioni | Ricavi netti (rettifica) | Capitalizzazione costi interni |
| A.5 — Altri ricavi e proventi | Ricavi netti | Salvo componenti straordinarie |
| B.6 — Materie prime, sussidiarie, merci | Costi materie prime e merci | |
| B.7 — Servizi | Costi per servizi e godimento | |
| B.8 — Godimento beni di terzi | Costi per servizi e godimento | Inclusi canoni leasing |
| B.9 — Costi del personale (a-e) | Costi del personale | Tutte le sottovoci |
| B.10a — Ammortamento imm. immateriali | Ammortamenti e svalutazioni | |
| B.10b — Ammortamento imm. materiali | Ammortamenti e svalutazioni | |
| B.10c — Altre svalutazioni immobilizzazioni | Ammortamenti e svalutazioni | |
| B.10d — Svalutazione crediti circolante | Ammortamenti e svalutazioni | |
| B.11 — Variazione rimanenze MP | Costi materie prime (rettifica) | Sommare algebricamente a B.6 |
| B.12 — Accantonamenti rischi | Da valutare | Operativi → pre-EBITDA; finanziari → post-EBIT |
| B.13 — Altri accantonamenti | Da valutare | Come B.12 |
| B.14 — Oneri diversi di gestione | Costi per servizi e godimento | Salvo componenti straordinarie |
| C.15 — Proventi da partecipazioni | Proventi/oneri finanziari | |
| C.16 — Altri proventi finanziari | Proventi/oneri finanziari | |
| C.17 — Interessi e altri oneri finanziari | Proventi/oneri finanziari | |
| C.17bis — Utili/perdite su cambi | Proventi/oneri finanziari | |
| D.18 — Rivalutazioni | Proventi/oneri finanziari | Post-EBIT, prima delle imposte |
| D.19 — Svalutazioni | Proventi/oneri finanziari | Svalutazioni finanziarie |
| 20 — Imposte sul reddito | Imposte | Correnti + differite + anticipate |

#### Casi speciali CE
- **A.5 con componenti straordinarie**: se la nota integrativa segnala proventi straordinari in A.5 (es. plusvalenze rilevanti), isolarli sotto EBIT come "Componenti straordinarie" e flaggare
- **B.12/B.13 accantonamenti**: default → operativi (pre-EBITDA come "altri costi operativi"). Se natura finanziaria → post-EBIT
- **Variazione rimanenze** (A.2, B.11): segno contabile. Aumento rimanenze prodotti = ricavo positivo. Aumento rimanenze MP = costo ridotto
- **A.4 capitalizzazioni**: se flag `capitalizzazione_anomala`, segnalare all'analista — può distorcere EBITDA

### Algoritmo di mapping

1. **Per ogni voce dello schema normalizzato**:
   a. Cercare corrispondenza nella tabella di mapping tramite `fonte_riga_bilancio`
   b. Se match diretto → applicare regola
   c. Se match ambiguo (es. "altri debiti") → consultare flags e note
   d. Se nessun match → aggiungere a `voci_non_mappate` e flaggare

2. **Calcolare aggregati**:
   a. CCON = Crediti commerciali + Rimanenze + Altri crediti operativi − Debiti operativi
   b. PFN = Debiti fin. lungo + Debiti fin. breve − Disponibilità liquide
   c. Totali SP

3. **Verificare quadratura**:
   a. Totale Attivo = CFN + CCON (lordo, prima di sottrarre debiti op.) + Altre attività
   b. Totale Passivo = PN + PFN (lordo, prima di sottrarre liquidità) + Debiti operativi
   c. Tolleranza: ≤ 1€ (arrotondamenti)

4. **Calcolare confidence score**:
   - 1.0: tutte le voci mappate, quadratura ok, nessun flag ambiguo
   - 0.8-0.99: quadratura ok, 1-2 voci stimate
   - 0.5-0.79: voci non mappate significative o delta quadratura
   - < 0.5: riclassifica inaffidabile, richiede intervento manuale

## Criteri di qualità
- Quadratura SP: delta ≤ 1€
- Quadratura CE: Utile netto = utile da schema normalizzato (delta ≤ 1€)
- Zero voci non mappate con peso > 1% del totale attivo/ricavi
- Confidence ≥ 0.8 per procedere all'analisi
- Ogni deviazione dallo schema standard è documentata con motivazione

## Deviazioni consentite
- **TFR in PFN**: se richiesto esplicitamente dall'utente o se la prassi settoriale lo prevede, il TFR può essere incluso nella PFN anziché nei debiti operativi. Documentare la scelta.
- **Leasing capitalizzato**: se flag `leasing_operativo_rilevante`, aggiungere riga pro-forma in CFN e PFN con nota esplicita.
- **Voci aggregate**: se il bilancio abbreviato non dettaglia le sottovoci, mappare l'aggregato alla categoria più probabile e flaggare `dato_stimato`.
- **Componenti straordinarie**: se identificate in A.5 o B.14, possono essere isolate in una riga aggiuntiva tra EBIT ed EBT.
- **Settore servizi**: il "Valore Aggiunto Industriale" diventa "Valore Aggiunto" (senza variazione rimanenze prodotti significativa).

## Esempi

### Esempio 1 — Mapping diretto di un credito commerciale
**Input:**
```json
{
  "id": "crediti_verso_clienti_entro",
  "label": "Crediti verso clienti esigibili entro l'esercizio successivo",
  "livello": 3,
  "aggregato": "C.II.1",
  "valore": {"2023": 1250000},
  "fonte_riga_bilancio": "C.II.1",
  "non_standard": false,
  "flags": [],
  "note": ""
}
```
**Output:** → CCON → Crediti commerciali: 1.250.000

### Esempio 2 — Voce ambigua: "altri debiti"
**Input:**
```json
{
  "id": "altri_debiti",
  "label": "Altri debiti",
  "livello": 2,
  "aggregato": "D.14",
  "valore": {"2023": 500000},
  "fonte_riga_bilancio": "D.14",
  "non_standard": false,
  "flags": ["voce_non_standard"],
  "note": "Include finanziamento soci per 300.000€"
}
```
**Output:**
- 300.000 → PFN → Debiti finanziari (lungo o breve da nota integrativa)
- 200.000 → Debiti operativi
- Flag: `dato_stimato` sulla ripartizione
- Deviazione documentata: "Split altri debiti basato su nota integrativa"

### Esempio 3 — Bilancio abbreviato senza dettaglio
**Input:** Voce unica "Immobilizzazioni" senza split materiali/immateriali
**Output:**
- Mappare intero importo a CFN → Immobilizzazioni materiali nette (più probabile per PMI manifatturiera)
- Flag: `dato_stimato`
- Nota: "Bilancio abbreviato — dettaglio non disponibile, assegnato a materiali"
- Confidence penalizzata (−0.1)
