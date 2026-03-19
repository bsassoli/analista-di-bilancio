# SKILL: Produttore Output

## Ruolo e obiettivo
Generare i deliverable finali — Excel (.xlsx) con serie storica completa e
Word (.docx) con commenti analitici — a partire dall'output strutturato
dell'analista.

## Input attesi
- Output completo dell'analista (indici, trend, alert, narrative)
- SP e CE riclassificati per tutti gli anni
- Metadata azienda e flags globali

## Output prodotto
1. **Excel (.xlsx)**: `data/output/{azienda}_analisi.xlsx`
   - Foglio "SP Riclassificato": serie storica SP con tutte le voci
   - Foglio "CE Riclassificato": serie storica CE
   - Foglio "Indici": tabella indici per anno con formattazione condizionale
   - Foglio "Dati grezzi": schema normalizzato per riferimento

2. **Word (.docx)**: `data/output/{azienda}_report.docx`
   - Sezione: Dati anagrafici e perimetro analisi
   - Sezione: Stato Patrimoniale riclassificato (tabella)
   - Sezione: Conto Economico riclassificato (tabella)
   - Sezione: Indici di bilancio (tabella con evidenziazione)
   - Sezione: Analisi e commenti (narrative dell'analista)
   - Sezione: Alert e punti di attenzione
   - Sezione: Note metodologiche e limitazioni

## Tools disponibili
- `scrivi_excel(path, fogli)` — genera file Excel con openpyxl
- `scrivi_word(path, sezioni)` — genera file Word con python-docx
- `formatta_numero_it(valore)` — formattazione italiana (1.250.000)
- `formatta_percentuale(valore)` — formattazione percentuale (12,3%)
- `crea_tabella_serie_storica(dati, anni)` — prepara dati per tabella multi-anno

## Logica di ragionamento

### Excel — Struttura fogli

#### Foglio "SP Riclassificato"
- Colonna A: Voce (con indentazione per livelli)
- Colonne successive: un anno per colonna (dal più vecchio al più recente)
- Righe di totale in grassetto con bordo
- Riga finale: verifica quadratura
- Formattazione: numeri in formato italiano, negativo in rosso tra parentesi

#### Foglio "CE Riclassificato"
- Stessa struttura dello SP
- Righe intermedie calcolate evidenziate (VA, EBITDA, EBIT, EBT)
- Margini percentuali in colonna aggiuntiva per ogni anno

#### Foglio "Indici"
- Raggruppamento per categoria (Redditività, Struttura, Liquidità, Efficienza)
- Formattazione condizionale:
  - Verde: valore in zona buona
  - Giallo: zona di attenzione
  - Rosso: zona critica
- Frecce trend (↑ ↓ →) nell'ultima colonna

#### Foglio "Dati grezzi"
- Dump dello schema normalizzato per trasparenza e audit
- Nessuna formattazione particolare

### Word — Struttura documento

1. **Intestazione**: nome azienda, periodo analizzato, data report
2. **Indice**: auto-generato
3. **Dati anagrafici**: azienda, settore, anni analizzati, tipo bilancio
4. **Tabella SP**: formato compatto, evidenziazione aggregati
5. **Tabella CE**: formato compatto, con margini %
6. **Tabella Indici**: con benchmark e indicazione soglie
7. **Analisi**: narrative dell'analista, una sottosezione per area
8. **Alert**: lista puntata con livello di severità
9. **Note**: limitazioni, dati stimati, deviazioni dallo schema standard
10. **Appendice flags**: lista completa flags attivi con spiegazione

### Formattazione numeri
- Valori monetari: `1.250.000 €` (separatore migliaia punto, niente decimali)
- Percentuali: `12,3%` (virgola decimale)
- Indici: 2 decimali con virgola (`0,85`)
- Negativi: tra parentesi e in rosso `(125.430)`

## Criteri di qualità
- I totali in Excel sono formule, non valori statici
- Il Word è autocontenuto (leggibile senza Excel)
- Nessun dato troncato o overflow nelle celle
- Formattazione coerente in tutto il documento
- File apribili con Excel/Word standard (no dipendenze macro)

## Deviazioni consentite
- Se un solo anno: niente colonne trend, layout verticale anziché serie storica
- Se > 7 anni: in Excel tutti gli anni, in Word solo ultimi 5 con nota
- Se narrative non disponibili (skip fase analisi): Word solo tabelle e indici

## Esempi

### Esempio 1 — Riga Excel SP
| Voce | 2021 | 2022 | 2023 |
|---|---|---|---|
| **CAPITALE FISSO NETTO** | **8.234.120** | **8.567.890** | **9.012.340** |
|   Immobilizzazioni materiali nette | 6.500.000 | 6.800.000 | 7.200.000 |
|   Immobilizzazioni immateriali nette | 234.120 | 267.890 | 312.340 |
|   Immobilizzazioni finanziarie | 1.500.000 | 1.500.000 | 1.500.000 |

### Esempio 2 — Sezione Word alert
> **Punti di attenzione**
>
> - **PFN/EBITDA 4,5x** (soglia: 4,0x) — Livello di indebitamento elevato.
>   Contestualizzazione: investimento straordinario 2023 (+1,2M€ PFN).
>   Al netto: 3,2x.
>
> - **Giorni crediti 95gg** (benchmark settore: 75gg) — Tempi di incasso
>   superiori alla media. In peggioramento rispetto al 2022 (82gg).
