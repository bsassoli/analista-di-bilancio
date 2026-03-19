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
 │   Ricognizione pagine (det.)     Identifica SP/CE, formato IFRS vs OIC
 │   Parsing con Claude             Solo 3-4 pagine, ~10-15K chars
 │
 ▼
[2] Estrattore numerico (det.)     → schema normalizzato JSON (valori interi, ID univoci)
 │
 ▼
[3] Checker pre-riclassifica (det.) → severity score per anno (ok/warning/critical)
 │
 ▼
[4] Riclassificatore               → SP criterio finanziario, CE valore aggiunto
 │   IFRS: deterministico            Pattern matching su voci note
 │   OIC: LLM                        Claude con skill_riclassifica.md
 │
 ▼
[5] Checker post-riclassifica (det.) → quadratura SP, coerenza utile, confidence
 │
 ▼
[6] Analista                        → indici, trend YoY, CAGR, alert, narrative
 │   Indici: deterministico           ROE, ROI, ROS, PFN/EBITDA, current ratio, ...
 │   Narrative: LLM con fallback      Commenti analitici in italiano
 │
 ▼
[7] Produttore (det.)              → Excel (.xlsx) + Word (.docx)
```

`det.` = deterministico (nessuna chiamata API). `LLM` = Claude via Anthropic SDK.

## Struttura progetto

```
├── main.py                        Entry point
├── skills/                        Knowledge base degli agenti (8 file .md)
│   ├── skill_riclassifica.md      Mapping completo art. 2424/2425 → schema riclassificato
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
│   ├── pipeline.py                Checker + riclassificatore + post-checker
│   ├── analista.py                Indici, trend, alert, narrative
│   └── produttore.py              Excel + Word
├── tools/                         Funzioni deterministiche e testabili (L2)
│   ├── pdf_parser.py              pdfplumber, normalizzazione numeri italiani
│   ├── calcolatori.py             Tutti gli indici di bilancio
│   ├── validatori.py              Checks coerenza e completezza
│   ├── schema.py                  Strutture dati e mapping voci
│   └── writer.py                  Output Excel (openpyxl) e Word (python-docx)
├── tests/                         62 test
└── data/
    ├── input/                     PDF bilanci
    └── output/                    JSON intermedi, Excel, Word
```

## Formati supportati

| Formato | Estrazione | Riclassifica | Testato su |
|---|---|---|---|
| IFRS (quotate) | LLM | Deterministico | Enervit S.p.A. 2024/2023 |
| OIC ordinario | LLM | LLM | MDC S.p.A. (consolidato) 2024/2023 |
| OIC abbreviato | LLM | LLM | Non ancora testato |

## Indici calcolati

**Redditività**: ROE, ROI, ROS, ROA, EBITDA margin
**Struttura**: indipendenza finanziaria, rapporto indebitamento, copertura immobilizzazioni, PFN/EBITDA, PFN/PN
**Liquidità**: current ratio, quick ratio, giorni crediti, giorni debiti, giorni magazzino, ciclo cassa
**Efficienza**: costo personale/VA, incidenza ammortamenti

## SKILL.md

Ogni subagente ha un file SKILL.md che ne definisce ruolo, input/output, logica di ragionamento, criteri di qualità e deviazioni consentite. Migliorare uno SKILL.md migliora il comportamento dell'agente senza modificare codice.

Il più critico è `skill_riclassifica.md` — contiene le tabelle complete di mapping delle voci civilistiche italiane (art. 2424 SP / art. 2425 CE) alla destinazione riclassificata.

## Limiti noti

- **Estrattore qualitativo** non implementato (nota integrativa non letta)
- **Serie storica multi-anno** non testata con PDF separati
- **Bilanci abbreviati/micro** non testati
- **Stato persistente** non implementato (ogni run è stateless)

## Stack

Python 3.11+, Anthropic SDK (Claude Sonnet), pdfplumber, pandas, openpyxl, python-docx
