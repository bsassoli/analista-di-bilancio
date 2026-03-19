# CLAUDE.md — Istruzioni per Claude Code

## Setup

- Python 3.14, venv in `.venv/`
- Attivare: `source .venv/bin/activate`
- API key Anthropic in `.env` (caricata con `python-dotenv`, `override=True`)
- Installare dipendenze: `pip install anthropic pdfplumber pandas openpyxl python-docx python-dotenv pytest`

## Comandi frequenti

```bash
# Test
python -m pytest tests/ -v

# Pipeline completa su un bilancio
python main.py "data/input/nome_bilancio.pdf" "Nome Azienda"

# Pipeline multi-anno (N PDF stessa azienda)
python main.py --multi "data/input/2022.pdf" "data/input/2023.pdf" "data/input/2024.pdf" -- "Nome Azienda"

# Singoli step (richiedono argomento path)
python -m agents.estrattore_pdf "data/input/bilancio.pdf"
python -m agents.estrattore_qualitativo "data/input/bilancio.pdf"
python -m agents.pipeline "data/output/schema.json"
python -m agents.analista "data/output/pipeline_result.json"
python -m agents.produttore "data/output/pipeline_result.json" "data/output/analisi.json"
```

## Architettura

Pipeline lineare a 8 step: PDF → Estrattore PDF (LLM) → Estrattore numerico (det.) → Estrattore qualitativo (LLM, nota integrativa) → Checker (det.) → Riclassificatore (LLM primario, det. fallback) → Analista (det. + LLM narrative) → Produttore (det.)

3 livelli:
- **L0** `main.py` — orchestratore (singolo PDF e multi-anno)
- **L1** `agents/` — subagenti (base.py ha l'agent loop e il tool dispatch)
- **L2** `tools/` — funzioni deterministiche testabili

Gli `skills/*.md` sono il system prompt degli agenti. Migliorarli migliora il comportamento senza toccare codice.

### Agenti
- `estrattore_pdf.py` — 2 fasi: ricognizione deterministica pagine + parsing LLM
- `estrattore_numerico.py` — normalizza valori stringa in interi
- `estrattore_qualitativo.py` — estrae flags e annotazioni dalla nota integrativa
- `pipeline.py` — checker + riclassificatore (LLM primario con retry, det. fallback)
- `analista.py` — calcolo indici, trend, alert, narrative
- `produttore.py` — genera Excel e Word
- `orchestratore_multi.py` — processa N PDF, merge risultati, dedup anni

### Tools registrati in base.py
- `calcola_ccon`, `calcola_pfn` — aggregati SP (disponibili per skill_riclassifica)
- `cerca_pattern_testo` — ricerca regex con contesto (per skill_estrazione_qualitativa)

## Convenzioni

- Tutti i valori monetari sono **interi** (euro, niente centesimi)
- Formattazione italiana: punto separatore migliaia, virgola decimale
- Gli ID delle voci sono generati da `tools.pdf_parser.genera_id(label)`
- I bilanci di test sono in `data/input/`, gli output in `data/output/`
- `.env`, `data/input/*.pdf`, `data/output/*` sono nel `.gitignore`

## Bilanci di test disponibili

- **Enervit S.p.A.** — IFRS, quotata, bilancio separato 2024/2023 (120 pagine, SP pag 52-53, CE pag 54)
- **MDC S.p.A.** — OIC ordinario, consolidato 2024/2023 (48 pagine, SP pag 2-4, CE pag 5)

## Limiti noti

- Bilanci abbreviati/micro non testati
- Multi-anno testato solo con mock, non con PDF reali
- Estrattore qualitativo: scope iniziale limitato a split voci, scadenze debiti, fondi rischi
