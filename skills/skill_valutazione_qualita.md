# SKILL: Valutazione Qualità Analisi

## Ruolo e obiettivo
Valutare la qualità di un'analisi di bilancio prodotta dal sistema, assegnando un
punteggio da 1 a 5 su 10 criteri. Usato come test di qualità / benchmark per
calibrare e migliorare gli agenti.

## Rubric di valutazione

Valuta ciascuna area da 1 a 5.

### 1. Struttura e chiarezza del ragionamento
- 1 → Disorganizzato, descrittivo, nessun filo logico
- 3 → Organizzato per sezioni, ma meccanico
- 5 → Narrativa chiara che collega performance → bilancio → cassa → finanziamento

### 2. Consapevolezza contabile (effetti IFRS, rettifiche)
- 1 → Nessuna menzione di distorsioni contabili
- 3 → Identifica effetti IFRS 16
- 5 → Rettifica l'interpretazione di conseguenza (non tratta EBITDA meccanicamente)

### 3. Analisi del capitale circolante
- 1 → Riporta solo il totale working capital
- 3 → Scompone in componenti (crediti, rimanenze, debiti)
- 5 → Identifica il driver principale, spiega perché è cambiato, e le implicazioni

### 4. Collegamento bilancio ↔ flussi di cassa
- 1 → Nessuna connessione chiara
- 3 → Nota che il working capital impatta la cassa
- 5 → Spiega chiaramente la catena completa:
  working capital → assorbimento cassa → evoluzione debito

### 5. Analisi debito e stagionalità
- 1 → Vista statica (singolo punto nel tempo)
- 3 → Confronta valori di fine anno
- 5 → Riconosce pattern stagionali ed evita conclusioni fuorvianti

### 6. Capex vs dinamiche operative
- 1 → Ignora o menziona appena il capex
- 3 → Nota aumenti/diminuzioni investimenti
- 5 → Integra capex in flussi di cassa e strategia (crescita vs mantenimento)

### 7. Confronto con peer e multipli
- 1 → Nessun comparable o confronto puramente meccanico
- 3 → Usa comparable ma con interpretazione limitata
- 5 → Aggiusta per differenze (dimensione, segmenti, accounting) e interpreta sconto/premio
- NOTA: se il sistema non ha dati di peer, valutare se l'analisi SEGNALA la mancanza e suggerisce quali peer usare

### 8. Ragionamento sulla valutazione (multi-angolo)
- 1 → Metrica singola, nessuna profondità
- 3 → Usa metriche multiple
- 5 → Triangola: margini, crescita, rischio, multipli storici
- NOTA: se il sistema non fa valuation, valutare se fornisce le basi per farne una (margini normalizzati, crescita organica, rischi)

### 9. Identificazione dei rischi
- 1 → Rischi generici
- 3 → Identifica rischi rilevanti (es. working capital, debito)
- 5 → Specifici, prioritizzati, collegati a numeri e dinamiche reali

### 10. Conclusioni e insight forward-looking
- 1 → Puro riassunto
- 3 → Qualche interpretazione
- 5 → Tesi chiara + definisce cosa deve succedere (es. rientro scorte, normalizzazione debito)

## Punteggio finale
- 40-50 → Analisi di alta qualità (livello analista senior)
- 30-39 → Solida ma ancora meccanica
- 20-29 → Profondità analitica debole
- <20 → Non sufficiente

## Cosa si valuta davvero

NON si valuta:
- Se sa calcolare indici
- Se sa riclassificare il bilancio

SI valuta:
- Se collega causa ed effetto
- Se distingue contabilità da economia reale
- Se identifica uno o due driver chiave invece di elencare tutto
- Se arriva a dire: "questa è la cosa che conta, e questo è quello che dobbiamo verificare"

## Domanda finale
"Qual è la singola cosa più importante da verificare nei prossimi 6 mesi per validare questa analisi?"
La risposta a questa domanda dice quasi tutto sul livello dell'analisi.

## Formato output valutazione
```json
{
  "punteggi": {
    "struttura_chiarezza": {"score": 0, "motivazione": "..."},
    "consapevolezza_contabile": {"score": 0, "motivazione": "..."},
    "analisi_working_capital": {"score": 0, "motivazione": "..."},
    "collegamento_cassa": {"score": 0, "motivazione": "..."},
    "debito_stagionalita": {"score": 0, "motivazione": "..."},
    "capex_dinamiche": {"score": 0, "motivazione": "..."},
    "peer_comparison": {"score": 0, "motivazione": "..."},
    "valutazione_multiangolo": {"score": 0, "motivazione": "..."},
    "identificazione_rischi": {"score": 0, "motivazione": "..."},
    "conclusioni_forward": {"score": 0, "motivazione": "..."}
  },
  "totale": 0,
  "livello": "...",
  "domanda_chiave": "Qual è la singola cosa più importante da verificare nei prossimi 6 mesi?",
  "risposta_domanda_chiave": "...",
  "punti_forza": ["..."],
  "aree_miglioramento": ["..."]
}
```
