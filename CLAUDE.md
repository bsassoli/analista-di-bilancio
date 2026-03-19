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

# Singoli step
python -m agents.estrattore_pdf "data/input/bilancio.pdf"
python -m agents.estrattore_numerico
python -m agents.pipeline
python -m agents.analista
python -m agents.produttore
```

## Architettura

Pipeline lineare a 7 step: PDF → Estrattore PDF (LLM) → Estrattore numerico (det.) → Checker (det.) → Riclassificatore (LLM per OIC, det. per IFRS) → Analista (det. + LLM narrative) → Produttore (det.)

3 livelli:
- **L0** `main.py` — orchestratore
- **L1** `agents/` — subagenti (base.py ha l'agent loop e il tool dispatch)
- **L2** `tools/` — funzioni deterministiche testabili

Gli `skills/*.md` sono il system prompt degli agenti. Migliorarli migliora il comportamento senza toccare codice.

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

- Estrattore qualitativo (nota integrativa) non implementato
- Multi-anno (N PDF separati) non implementato
- Riclassificatore deterministico è Enervit-specific, quello LLM funziona per tutti
- Bilanci abbreviati/micro non testati
- Nessun test per gli agents (solo per tools)
