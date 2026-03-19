# SKILL: Estrattore Numerico

## Ruolo e obiettivo
Trasformare le righe pulite prodotte dall'estrattore PDF nello schema
normalizzato JSON di progetto: conversione valori in interi, mapping a voci
civilistiche/IFRS, assegnazione ID, livelli gerarchici e flags.

Questo agente NON si occupa del parsing PDF (layout, label spezzate, celle
multi-riga) — quello è responsabilità dell'estrattore PDF.

## Input attesi
- Output dell'estrattore PDF: righe pulite con label, valori (stringhe), livello, genitore
- Formato bilancio (`IFRS`, `OIC_ordinario`, `OIC_abbreviato`, `OIC_micro`)
- Anni presenti (es. `["2024", "2023"]`)
- Nome azienda
- Eventuale indicazione "valori in migliaia di Euro"

## Output prodotto
```json
{
  "azienda": "...",
  "anni_estratti": [2024, 2023],
  "tipo_bilancio": "ordinario",
  "sp": [
    {
      "id": "immobilizzazioni_materiali",
      "label": "Immobilizzazioni materiali",
      "livello": 2,
      "aggregato": "B.II",
      "valore": {"2024": 5234120, "2023": 4987650},
      "fonte_riga_bilancio": "B.II",
      "non_standard": false,
      "flags": [],
      "note": ""
    }
  ],
  "ce": [],
  "metadata": {
    "pagine_sp": [52, 53],
    "pagine_ce": [54],
    "totale_attivo_dichiarato": {"2024": 67703856, "2023": 65037753},
    "totale_passivo_dichiarato": {"2024": 67703856, "2023": 65037753},
    "utile_dichiarato": {"2024": 4053349, "2023": 3781361},
    "formato": "IFRS",
    "valori_in_migliaia": false
  }
}
```

## Tools disponibili
- `normalizza_numero(stringa)` — converte "1.250.000" o "(350.000)" in intero
- `genera_id(label)` — genera ID normalizzato da label
- `mappa_voce_civilistica(label, formato)` — match label a riferimento art. 2424/2425 o categoria IFRS
- `calcola_subtotale(voci, ids, anno)` — verifica coerenza totali

## Logica di ragionamento

### Fase 1 — Conversione numerica
Per ogni riga dell'input:
1. Convertire ogni valore stringa in intero con `normalizza_numero`
2. Se `valori_in_migliaia`: moltiplicare per 1.000
3. Se il valore non è parsabile → flag `dato_mancante`, valore = None

Formati numerici italiani:
- `1.250.000` → 1250000
- `(350.000)` → -350000
- `1.250.000,50` → 1250000 (arrotondare)
- `-` o vuoto → 0
- `***` → None con flag `dato_mancante`

### Fase 2 — Mapping a voce civilistica/IFRS
Basandosi sul formato:

#### Per OIC (art. 2424 SP / art. 2425 CE)
- Cercare codici nella label: "B) II", "C.II.1", "A.1"
- Se il codice è nella label → estrarlo come `fonte_riga_bilancio`
- Altrimenti → fuzzy match sulla label → assegnare il codice più probabile

#### Per IFRS
- Non esiste una codifica standard
- Mapping basato su label → categoria semantica:
  - "Terreni", "Fabbricati", "Impianti" → Immobilizzazioni materiali
  - "Avviamento", "Costi di sviluppo" → Immobilizzazioni immateriali
  - "Crediti commerciali" → Crediti verso clienti
  - "Cassa e disponibilità liquide" → Disponibilità liquide
  - "Finanziamenti a lungo/breve termine" → Debiti finanziari
  - "Debiti commerciali" → Debiti verso fornitori
- Assegnare un aggregato convenzionale compatibile con lo schema di riclassifica

### Fase 3 — Generazione ID e livelli
Per ogni voce:
1. Generare `id` normalizzato dalla label con `genera_id`
2. Assegnare `livello`:
   - 1 = totale/macro-aggregato (TOTALE ATTIVO, TOTALE PN, EBITDA, EBIT)
   - 2 = subtotale (Totale immobilizzazioni materiali)
   - 3 = dettaglio (Terreni, Fabbricati)
   - 4 = "di cui" (informativo, non sommabile)
3. Derivare il livello dall'informazione `livello` dell'input PDF

### Fase 4 — Flags automatici
Applicare flags quando:
- `variazione_significativa_yoy`: variazione > 30% tra due anni consecutivi
- `voce_non_standard`: nessun match trovato nel mapping civilistico/IFRS
- `dato_mancante`: valore non parsabile
- `dato_stimato`: se il livello è "di_cui" usato come sostituto della voce genitore

### Fase 5 — Estrazione metadata
Dai totali presenti nelle righe:
1. Identificare TOTALE ATTIVO e TOTALE PASSIVO
2. Identificare UTILE NETTO (in SP e CE)
3. Popolare `metadata.totale_attivo_dichiarato`, etc.

### Fase 6 — Validazione interna
1. Verificare che i subtotali corrispondano alla somma delle voci figlie
2. Se discrepanza > 1€ → flag `quadratura_subtotale_ko` sulla voce totale
3. Contare voci per determinare tipo bilancio:
   - ≥ 30 voci SP → ordinario
   - 15-29 → abbreviato
   - < 15 → micro

## Criteri di qualità
- Tutti i valori stringa convertiti in interi (o esplicitamente None con flag)
- Ogni voce ha un `id` univoco
- Ogni voce ha un `aggregato` (o flag `voce_non_standard`)
- I totali dichiarati in metadata corrispondono alle voci totale nel dataset
- Nessuna voce persa rispetto all'input dell'estrattore PDF

## Deviazioni consentite
- Per IFRS: il campo `fonte_riga_bilancio` può essere vuoto (non c'è codifica civilistica)
- Se l'input indica "valori in migliaia" ma i totali quadrano senza moltiplicatore, non moltiplicare (il bilancio potrebbe dichiarare migliaia ma riportare unità)
- Per bilanci con voci non standard (es. "Prime" come prodotto, confondibile con voce contabile), usare il contesto del genitore per disambiguare

## Esempi

### Esempio 1 — Riga IFRS
**Input (dall'estrattore PDF):**
```json
{"label": "Terreni", "valori": {"2024": "207.243", "2023": "207.243"}, "livello": "dettaglio", "genitore": "Immobilizzazioni materiali"}
```
**Output:**
```json
{
  "id": "terreni",
  "label": "Terreni",
  "livello": 3,
  "aggregato": "B.II",
  "valore": {"2024": 207243, "2023": 207243},
  "fonte_riga_bilancio": "",
  "non_standard": false,
  "flags": [],
  "note": ""
}
```

### Esempio 2 — Voce con variazione significativa
**Input:**
```json
{"label": "Rimanenze", "valori": {"2024": "12.571.997", "2023": "8.773.211"}, "livello": "dettaglio"}
```
**Output:**
```json
{
  "id": "rimanenze",
  "label": "Rimanenze",
  "livello": 3,
  "aggregato": "C.I",
  "valore": {"2024": 12571997, "2023": 8773211},
  "fonte_riga_bilancio": "C.I",
  "non_standard": false,
  "flags": ["variazione_significativa_yoy"],
  "note": "Variazione +43.3% YoY"
}
```

### Esempio 3 — Bilancio in migliaia
**Input (valori_in_migliaia=true):**
```json
{"label": "Ricavi", "valori": {"2024": "95.097", "2023": "85.449"}, "livello": "dettaglio"}
```
**Output:**
```json
{
  "id": "ricavi",
  "label": "Ricavi",
  "livello": 2,
  "aggregato": "A.1",
  "valore": {"2024": 95097000, "2023": 85449000},
  "fonte_riga_bilancio": "A.1",
  "non_standard": false,
  "flags": [],
  "note": "Valori originali in migliaia di Euro"
}
```
