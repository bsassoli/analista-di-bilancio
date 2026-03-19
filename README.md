# Analista di Bilancio

Sistema agentivo Python per l'analisi automatizzata di bilanci aziendali italiani. Estrae dati da PDF, riclassifica con criterio finanziario (SP) e a valore aggiunto (CE), calcola indici, genera report Excel e Word.

Supporta bilanci IFRS (società quotate) e OIC (Srl, Spa non quotate), sia separati che consolidati.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install anthropic pdfplumber pandas openpyxl python-docx python-dotenv pytest

# Configura API key
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# Analizza un bilancio
python main.py "data/input/bilancio.pdf" "Nome Azienda"

# Analisi multi-anno (N PDF stessa azienda)
python main.py --multi "data/input/2022.pdf" "data/input/2023.pdf" -- "Nome Azienda"
```

Output in `data/output/`:
- `{azienda}_analisi.xlsx` — SP e CE riclassificati, indici, dati grezzi
- `{azienda}_report.docx` — report con tabelle, indici, narrative, alert

## Architettura

```
PDF
 │
 ▼
[1] Estrattore PDF (LLM)          → righe pulite con label, valori stringa, gerarchia
 │   Ricognizione pagine (det.)     Identifica SP/CE/NI, formato IFRS vs OIC
 │   Parsing con Claude             Solo 3-4 pagine, ~10-15K chars
 │
 ▼
[2] Estrattore numerico (det.)     → schema normalizzato JSON (valori interi, ID univoci)
 │
 ▼
[3] Estrattore qualitativo (LLM)   → flags strutturali, annotazioni voci dalla NI
 │   Ricognizione pagine NI (det.)   Keyword + bassa densità numerica
 │   Estrazione con Claude           Split voci ambigue, scadenze debiti, fondi rischi
 │
 ▼
[4] Checker pre-riclassifica (det.) → severity score per anno (ok/warning/critical)
 │
 ▼
[5] Riclassificatore               → SP criterio finanziario, CE valore aggiunto
 │   Primario: LLM (tutti i formati)  Claude con skill_riclassifica.md
 │   Retry: con feedback su errori    Se quadratura fallisce, ritenta con delta
 │   Fallback: deterministico         Pattern matching format-agnostic (OIC + IFRS)
 │
 ▼
[6] Checker post-riclassifica (det.) → quadratura SP, coerenza utile, confidence
 │
 ▼
[7] Analista                        → indici, trend YoY, CAGR, alert, narrative
 │   Indici: deterministico           ROE, ROI, ROS, PFN/EBITDA, current ratio, ...
 │   Narrative: LLM con fallback      Commenti analitici in italiano
 │
 ▼
[8] Produttore (det.)              → Excel (.xlsx) + Word (.docx)
```

`det.` = deterministico (nessuna chiamata API). `LLM` = Claude via Anthropic SDK.

### Multi-anno

Per analisi su serie storiche (5-10 anni), la pipeline multi-anno:
1. Processa ogni PDF indipendentemente
2. Merge `risultati_per_anno` con dedup anni sovrapposti (preferisce l'anno primario di ciascun PDF)
3. Validazione cross-anno (salti >50% totale attivo, cambi segno EBITDA/PFN)
4. Analisi unificata e output con tutti gli anni

## Struttura progetto

```
├── main.py                        Entry point (singolo + multi-anno)
├── skills/                        Knowledge base degli agenti (8 file .md)
│   ├── skill_riclassifica.md      Mapping art. 2424/2425 + IFRS → schema riclassificato
│   ├── skill_orchestratore.md     Pipeline a 8 step
│   ├── skill_estrazione_pdf.md    Parsing PDF, layout, ambiguità
│   ├── skill_estrazione_numerica.md
│   ├── skill_estrazione_qualitativa.md
│   ├── skill_checker.md
│   ├── skill_analisi.md
│   └── skill_produzione.md
├── agents/                        Agenti (L0 orchestratore + L1 subagenti)
│   ├── base.py                    Agent loop, tool dispatch, skill loader
│   ├── estrattore_pdf.py          PDF → righe pulite (LLM)
│   ├── estrattore_numerico.py     Righe pulite → schema normalizzato
│   ├── estrattore_qualitativo.py  Nota integrativa → flags e annotazioni (LLM)
│   ├── pipeline.py                Checker + riclassificatore (LLM + det.) + post-checker
│   ├── analista.py                Indici, trend, alert, narrative
│   ├── produttore.py              Excel + Word
│   └── orchestratore_multi.py     Pipeline multi-anno (N PDF → merge → analisi)
├── tools/                         Funzioni deterministiche e testabili (L2)
│   ├── pdf_parser.py              pdfplumber, normalizzazione numeri, cerca_pattern_testo
│   ├── calcolatori.py             Tutti gli indici di bilancio, CCON, PFN
│   ├── validatori.py              Checks coerenza, completezza, cross-anno
│   ├── schema.py                  Strutture dati, mapping OIC + IFRS
│   └── writer.py                  Output Excel (openpyxl) e Word (python-docx)
├── tests/                         160 test (tools + agents + multi-anno)
│   ├── conftest.py                Fixture condivise (schema, pipeline_result, analisi)
│   ├── fixtures/                  JSON risposte LLM catturate
│   └── test_*.py                  10 file di test
└── data/
    ├── input/                     PDF bilanci
    ├── output/                    JSON intermedi, Excel, Word
    └── stato/                     Stato persistente per multi-anno
```

## Formati supportati

| Formato | Estrazione | Riclassifica | Testato su |
|---|---|---|---|
| IFRS (quotate) | LLM | LLM (primario) + det. (fallback) | Enervit S.p.A. 2024/2023 |
| OIC ordinario | LLM | LLM (primario) + det. (fallback) | MDC S.p.A. (consolidato) 2024/2023 |
| OIC abbreviato | LLM | LLM | Non ancora testato |

## Indici calcolati

**Redditività**: ROE, ROI, ROS, ROA, EBITDA margin
**Struttura**: indipendenza finanziaria, rapporto indebitamento, copertura immobilizzazioni, PFN/EBITDA, PFN/PN
**Liquidità**: current ratio, quick ratio, giorni crediti, giorni debiti, giorni magazzino, ciclo cassa
**Efficienza**: costo personale/VA, incidenza ammortamenti

## SKILL.md

Ogni subagente ha un file SKILL.md che ne definisce ruolo, input/output, logica di ragionamento, criteri di qualità e deviazioni consentite. Migliorare uno SKILL.md migliora il comportamento dell'agente senza modificare codice.

Il più critico è `skill_riclassifica.md` — contiene le tabelle complete di mapping delle voci civilistiche italiane (art. 2424 SP / art. 2425 CE) alla destinazione riclassificata, con sezione dedicata per bilanci IFRS e consolidati.

## Limiti noti

- **Bilanci abbreviati/micro** non testati
- **Multi-anno** testato solo con mock, non con PDF reali
- **Estrattore qualitativo** scope iniziale: solo split voci, scadenze debiti, fondi rischi

## Stack

Python 3.14, Anthropic SDK (Claude Sonnet), pdfplumber, openpyxl, python-docx, pytest
