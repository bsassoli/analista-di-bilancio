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

## Principi fondamentali dell'analisi

### 1. Analizzare trend, non snapshot
Lavorare SEMPRE con più anni (idealmente 5-10). Un singolo anno non dice nulla.
Ogni indice va letto in serie storica per distinguere:
- Trend strutturali (miglioramento/peggioramento costante)
- Anomalie puntuali (un anno fuori trend → cercare la causa nei flags)
- Ciclicità (pattern che si ripetono)

### 2. Capire i driver, non solo i numeri
Per ogni variazione significativa di un margine, chiedersi PERCHÉ:
- **Ricavi crescono** → è pricing power (prezzi) o volume? Crescita organica o acquisizioni?
- **EBITDA margin migliora** → costi materie prime calati? Efficienza operativa? Leva operativa (costi fissi su base ricavi più ampia)?
- **EBITDA margin peggiora** → costo del personale cresciuto più dei ricavi? Materie prime in aumento senza possibilità di repricing?

Analizzare la struttura dei costi come % dei ricavi nel tempo:
- Incidenza materie prime / ricavi → pricing power vs costo input
- Incidenza personale / ricavi → produttività, automazione
- Incidenza servizi / ricavi → outsourcing, marketing
- Se un costo scende come % dei ricavi mentre i ricavi crescono → leva operativa

### 3. Separare performance operativa da effetti non operativi
L'analisi si concentra sulla capacità del business di generare valore:
- **Core**: EBITDA, EBIT, margini operativi — qui si giudica il business
- **Sotto EBIT**: oneri finanziari (scelta di struttura del capitale), imposte (non controllabili) — contesto, non giudizio
- **Straordinari**: se identificati, isolarli dal trend. Un EBITDA in crescita che include una plusvalenza non ricorrente non è vera crescita

### 4. Analisi forward-looking (quando possibile)
Se disponibili dati infrannuali (semestrali, trimestrali):
- Usarli per aggiornare le aspettative sull'anno in corso
- Attenzione alla stagionalità: H1 non è necessariamente 50% dell'anno
- Se il trend H1 diverge dal trend storico, segnalarlo

Essere conservativi dove c'è compressione margini o rallentamento crescita.
Non estrapolale linearmente un singolo semestre sull'intero anno.

### 5. Qualità dei dati riclassificati
Prima di analizzare, verificare:
- Quadratura SP (delta = 0)
- Utile CE = utile dichiarato
- Confidence riclassifica ≥ 0.8
- Se ci sono voci non mappate significative, l'analisi è meno affidabile → segnalare

## Disciplina analitica

Regole che separano un'analisi meccanica da un'analisi intelligente.

### Distinguere effetti contabili da realtà economica
Mai prendere un KPI al valore nominale. Chiedersi sempre: "cosa è cambiato
operativamente vs cosa è solo riclassificazione contabile?"

Ogni volta che un flag segnala un effetto contabile, la narrative DEVE:
1. Quantificare l'effetto sul KPI (es. "EBITDA +914k per IFRS 16")
2. Calcolare il KPI "adjusted" al netto dell'effetto
3. Commentare il delta reale, non quello reported

Casi comuni (applicabili a QUALSIASI azienda):
- **IFRS 16 / leasing**: l'EBITDA migliora meccanicamente. Calcolare SEMPRE
  EBITDA adjusted = EBITDA reported - effetto IFRS 16 (da flags). Comparare
  l'adjusted YoY per capire il vero trend operativo. Idem per PFN: segnalare
  PFN al netto dei debiti per leasing.
- **Rivalutazioni ex lege**: il PN cresce, il ROE peggiora meccanicamente.
  Segnalare: "ROE impattato da rivalutazione per X€; al netto, ROE sarebbe Y%".
- **PPA da acquisizioni**: ammortamenti aggiuntivi su intangibili acquisiti
  deprimono EBIT. Calcolare EBIT adjusted pre-PPA per leggere la performance
  operativa sottostante.
- **Variazioni di perimetro**: se un anno include una nuova controllata,
  la crescita ricavi/EBITDA non è organica. La narrative deve distinguere:
  "Crescita totale +15%, di cui +8% organica e +7% per consolidamento di X."
- **Componenti non ricorrenti**: plusvalenze/minusvalenze, accantonamenti
  straordinari, ristrutturazioni. Escluderli dal trend EBITDA/EBIT per non
  distorcere il giudizio sulla capacità strutturale del business.

### Trattare il capitale circolante come strumento diagnostico
Non fermarsi a "il CCN è aumentato". Decomporre SEMPRE:
- Crediti commerciali → cresciuti con i ricavi? (fisiologico) O cresciuti più
  dei ricavi? (allungamento incassi, red flag)
- Rimanenze → crescita proporzionale ai ricavi? O stockpiling strategico /
  involontario? Ha conseguenze su cassa e debito.
- Debiti fornitori → accorciamento pagamenti? (rischio liquidità) O
  allungamento? (leva sul fornitore, attenzione alla sostenibilità)

Seguire SEMPRE la catena causale fino alle conseguenze finanziarie:
```
↑ rimanenze → ↑ capitale circolante → assorbimento di cassa → ↑ debito
```
Molte analisi si fermano a "il working capital è aumentato". Non basta.

### Stagionalità e limiti dei dati annuali
I bilanci annuali mostrano una fotografia al 31/12 — non l'intero film.
La narrative DEVE sempre ricordarlo:
- **Debito**: il saldo di fine anno può non rappresentare il picco reale.
  Aziende con business stagionale (turismo, agricoltura, sport, edilizia)
  possono avere debito molto più alto a metà anno. Se il settore è stagionale,
  segnalare: "Il debito a fine esercizio potrebbe non riflettere il picco
  infrannuale tipico del settore [X]."
- **Working capital**: le rimanenze al 31/12 possono essere in fase di build-up
  (pre-stagione) o smaltimento (post-stagione). Contestualizzare.
- **Confronti**: SEMPRE anno su anno (31/12 vs 31/12), mai mescolare periodi.
- **Dati semestrali**: se disponibili, NON annualizzare linearmente. H1 non è
  50% dell'anno in business stagionali. Segnalare il limite.
- **Regola generale**: in assenza di dati infrannuali, dichiarare esplicitamente
  nella narrative che l'analisi si basa su saldi di fine anno e che il profilo
  infrannuale potrebbe differire.

### Connettere bilancio, cassa e debito
Ogni movimento patrimoniale ha una conseguenza finanziaria. La narrative DEVE
esplicitare la catena causale completa, non fermarsi al primo anello.

**Template mentale per ogni variazione significativa:**
```
COSA è cambiato? → PERCHÉ è cambiato? → COME è stato finanziato? → QUAL È l'effetto sulla cassa/debito?
```

Esempi applicabili a qualsiasi azienda:
- ↑ CFN (investimento) → finanziato come? Autofinanziamento (utili)? Nuovo
  debito? Aumento capitale? Se debito → PFN/EBITDA peggiora, è sostenibile?
- ↑ Rimanenze → assorbimento cassa → se non compensato da utili → ↑ debito
- Distribuzione dividendi → ↓ PN e cassa. Se contemporaneamente il debito sale,
  il dividendo è finanziato a debito (red flag in qualsiasi settore).
- Acquisizione → pagata cash (↓ liquidità), con leva (↑ PFN), o con azioni
  (↑ capitale)? Quantificare.

### Integrare capex nella strategia
Gli investimenti NON sono solo un numero — raccontano la strategia dell'azienda.
La narrative DEVE:
- Quantificare il capex totale e il ratio capex/ricavi (intensità di capitale)
- Distinguere capex di mantenimento (ammortamenti ≈ capex → business stabile)
  da capex di espansione (capex >> ammortamenti → azienda che investe in crescita)
- Collegare ai flussi: capex > utili + ammortamenti → l'azienda si finanzia
  a debito per investire. È sostenibile?
- Se disponibili dati da estrattore qualitativo (dettaglio investimenti),
  commentare: nuova capacità produttiva? Manutenzione? Digitalizzazione?
- Trend capex nel tempo: sta accelerando o rallentando? Cosa implica per la
  crescita futura?

### Posizionamento settoriale
Anche SENZA dati di peer, la narrative deve contestualizzare l'azienda:
- Identificare il settore di appartenenza dai dati disponibili (composizione
  ricavi, struttura costi, intensità di capitale)
- Commentare se i margini sono tipici del settore o anomali. Es: un EBITDA
  margin del 5% è buono nel food retail ma basso nel software.
- Se i dati non consentono un confronto, dichiararlo esplicitamente:
  "In assenza di dati di peer comparabili, gli indici sono valutati rispetto
  a benchmark generali per PMI manifatturiere italiane. Un confronto con
  operatori del settore [X] migliorerebbe significativamente l'analisi."
- Segnalare SEMPRE quali peer sarebbero rilevanti per un eventuale confronto
  (basandosi su settore, dimensione, formato bilancio).
- Non fingere di avere dati che non si hanno. Meglio dire "mancano i comparabili"
  che inventare un confronto.

### Validazione forward-looking
Dopo ogni analisi, identificare 2-3 variabili chiave che confermeranno o
invalideranno la tesi. Questo va SEMPRE nelle conclusioni — è la parte
più importante dell'intera analisi.

**Formato:** "La tesi regge SE [condizione verificabile]. Il rischio principale
è [scenario avverso specifico]."

Come identificare le variabili chiave:
- Qual è la singola cosa più importante da verificare nei prossimi 6-12 mesi?
- Quale variabile, se si muove nella direzione sbagliata, invalida l'intera
  narrativa positiva (o negativa)?
- Quale dato del prossimo bilancio guarderesti PER PRIMO?

Esempi generalizzabili:
- Se il business ha investito molto: "Il capex di X€ si giustifica se i ricavi
  crescono di almeno Y% nei prossimi 2 anni. Monitorare la top line."
- Se le scorte sono salite: "L'assorbimento di cassa di X€ in rimanenze
  è sostenibile solo se smaltite entro [periodo]. Se giorni magazzino non
  rientrano sotto [N], la PFN si deteriora strutturalmente."
- Se il debito è salito: "La PFN/EBITDA di Nx è temporanea se guidata da
  [investimento/acquisizione]. Deve tornare sotto [soglia]x entro [anno]."
- Se i margini si comprimono: "Il calo di EBITDA margin da X% a Y% diventa
  preoccupante se prosegue. Verificare se l'azienda riesce a trasferire
  l'aumento dei costi input sui prezzi."

Questo è dove emerge il vero insight: non nell'elenco di 20 indici, ma
nella capacità di isolare le 2-3 cose che contano davvero e di formulare
una tesi che il prossimo bilancio confermerà o smentirà.

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

### Analisi dei driver (margin bridge)
Per ogni variazione significativa dei margini, decomporre:

**Ricavi**:
- Crescita organica vs acquisizioni (se flag `ACQUISIZIONE`)
- Mix canale/prodotto (se dati da estrattore qualitativo)
- Effetto prezzo vs volume (raramente disponibile, ma segnalare se la NI lo menziona)

**EBITDA margin**:
- Incidenza materie prime / ricavi (pricing power)
- Incidenza personale / ricavi (produttività)
- Incidenza servizi / ricavi (efficienza)
- Se margine migliora con ricavi in crescita → probabile leva operativa
- Se margine peggiora con ricavi in crescita → costi crescono più dei ricavi (red flag)

**Dal EBITDA al utile netto**:
- Ammortamenti / ricavi → intensità investimenti
- Oneri finanziari / PFN → costo medio del debito
- Tax rate effettivo → imposte / EBT

### Soglie e alert
- Ogni indice ha soglie di riferimento per PMI manifatturiere italiane
- Alert generati quando un indice supera soglia critica
- Alert contestualizzati: un PFN/EBITDA alto in anno di investimento è diverso da uno strutturale
- Usare i flags per contestualizzare (es. `cambio_perimetro` spiega discontinuità)

### Narrative
L'analista produce testi strutturati per sezione. Ogni sezione ha un obiettivo
specifico — non ripetere le stesse informazioni in sezioni diverse.

1. **Sintesi** (5-8 righe): overview dell'azienda e del suo stato di salute.
   - Settore, dimensione (ricavi), posizione (crescita/stabile/declino)
   - I 2-3 numeri chiave dell'ultimo anno (EBITDA, PFN, utile)
   - Il trend principale nel periodo analizzato
   - Se ci sono effetti contabili rilevanti (IFRS 16, acquisizioni), menzionarli
     subito: "L'EBITDA reported di X€ include effetti IFRS 16 per Y€."

2. **Redditività**: andamento margini con DRIVER ANALYSIS. La domanda è PERCHÉ.
   - Evoluzione struttura costi come % ricavi: materie prime, servizi, personale
   - Identificare il driver principale del cambiamento margini
   - Se ci sono effetti contabili, calcolare KPI adjusted
   - Se il qualitativo ha composizione ricavi, usarla per commentare il mix
   - Esempio di cosa NON scrivere: "Il ROS è migliorato dal 5% al 7%."
   - Esempio di cosa scrivere: "Il ROS è migliorato dal 5% al 7% (+2pp) grazie
     alla riduzione dell'incidenza materie prime (da 42% a 38% dei ricavi),
     parzialmente compensata dall'aumento del personale (da 25% a 27%).
     La leva operativa ha amplificato il miglioramento: su una crescita ricavi
     del 6%, l'EBITDA è cresciuto del 12%."

3. **Struttura finanziaria**: come l'azienda si finanzia e se è sostenibile.
   - Evoluzione PFN nel tempo: miglioramento o deterioramento?
   - Connessione esplicita: capex → finanziamento → debito → sostenibilità
   - Se flag IFRS 16: "PFN include X€ di debiti per leasing; al netto, PFN
     sarebbe Y€ con PFN/EBITDA di Zx."
   - Copertura immobilizzazioni: fonti a lungo termine sufficienti?
   - Segnalare la natura dei dati: "L'analisi si basa su saldi al 31/12.
     Il profilo infrannuale del debito potrebbe differire in settori stagionali."
   - Se disponibili dati su scadenze debiti (dal qualitativo), commentarli:
     concentrazione scadenze? refinancing risk?

4. **Liquidità**: capacità di far fronte agli impegni a breve e gestione del
   ciclo commerciale.
   - Current/quick ratio e loro evoluzione
   - Decomposizione working capital: quale componente guida il cambiamento?
   - Catena causale completa: es. "↑ rimanenze (+X€) → assorbimento cassa →
     ↑ PFN di Y€ nel periodo"
   - Confronto giorni crediti vs giorni debiti: l'azienda finanzia i clienti
     o si fa finanziare dai fornitori?
   - Se disponibile: fatturato per dipendente, costo medio per dipendente

5. **Conclusioni**: tesi, rischi, variabili da monitorare.
   - Punti di forza (3-4, specifici e quantificati)
   - Aree di attenzione (2-3, con soglie e timeline)
   - TESI PRINCIPALE: "L'azienda è in fase [X] perché [Y]. La tesi regge
     SE [condizione verificabile entro 6-12 mesi]."
   - VARIABILE CHIAVE: "La singola cosa da verificare nel prossimo bilancio
     è [Z], perché [motivazione]."
   - Posizionamento settoriale: anche senza peer data, commentare se i margini
     sono tipici del settore. Suggerire peer comparabili.

Le narrative devono:
- Essere basate su dati, mai generiche — ogni affermazione ha un numero
- Citare i numeri specifici (euro, percentuali, multipli, punti percentuali)
- Spiegare il "perché", non solo il "cosa" (usando flags, annotazioni, driver)
- Distinguere trend strutturali da effetti puntuali e contabili
- Dichiarare i limiti dell'analisi (dati annuali, assenza peer, stime)
- Integrare TUTTI i dati qualitativi disponibili (dipendenti, capex, ricavi, dividendi)
- Terminare SEMPRE con una tesi falsificabile e una variabile chiave da monitorare

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

### Esempio 3 — Decomposizione working capital
"Il capitale circolante operativo netto è cresciuto da 2.4M€ a 5.6M€ (+134%)
nel 2023, assorbendo 3.2M€ di cassa. La decomposizione rivela che l'aumento è
interamente guidato dalle rimanenze (+2.8M€, +65%), mentre i crediti commerciali
sono cresciuti in linea con i ricavi (+8%). L'incremento delle scorte riflette
una scelta strategica di stockpiling pre-lancio nuova linea (fonte: relazione
sulla gestione, pag. 8). L'assorbimento di cassa ha portato la PFN da -0.4M€
(cassa netta) a +1.2M€ (indebitamento netto). Variabile chiave da monitorare:
lo smaltimento delle scorte nel H1 2024 — se rimanenze non rientrano sotto 5M€,
la PFN potrebbe stabilizzarsi su livelli strutturalmente più elevati."

### Esempio 4 — Effetto contabile vs economico (IFRS 16)
"L'EBITDA 2024 include un effetto IFRS 16 di +914k€ (costi leasing riclassificati
in ammortamenti e oneri finanziari). Al netto dell'effetto, l'EBITDA 'adjusted'
sarebbe 8.3M€ vs 8.9M€ dell'anno precedente (adjusted), evidenziando una
compressione del margine operativo reale di 0.6 pp. L'effetto è puramente
contabile e non riflette un miglioramento della capacità di generazione di cassa."

## Note per sviluppo futuro

### Analisi comparativa (non implementata)
Quando disponibili dati di peer, i principi da seguire sono:
- I comparabili non sono mai plug-and-play: aggiustare per dimensione, segmenti,
  standard contabili, geografia
- Un titolo può essere cheap vs peer e expensive vs se stesso: servono entrambe
  le lenti (multipli relativi + multipli storici)
- Triangolazione: non fermarsi a un singolo multiplo. Incrociare margini
  (giustificano parte dello sconto?), crescita (contraddice lo sconto?),
  multipli storici (è davvero a buon mercato rispetto alla sua storia?)
