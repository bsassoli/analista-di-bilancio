"""Agente estrattore qualitativo: estrae info dalla nota integrativa.

Approccio a due fasi:
  Fase 1 (deterministica): identifica pagine NI e relazione sulla gestione.
  Fase 2 (LLM): estrae flags strutturali, annotazioni voci, criteri.
"""

import json
import re
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv(override=True)

from agents.base import crea_client
from tools.pdf_parser import estrai_testo_pdf, identifica_sezione


# ---------------------------------------------------------------------------
# Fase 1 — Ricognizione pagine NI e Relazione sulla gestione
# ---------------------------------------------------------------------------

_KEYWORDS_NI = [
    "nota integrativa",
    "criteri di valutazione",
    "principi contabili",
    "composizione delle voci",
    "movimentazione delle immobilizzazioni",
    "crediti verso clienti",
    "debiti verso fornitori",
    "fondi per rischi",
]

_KEYWORDS_RELAZIONE = [
    "relazione sulla gestione",
    "relazione del consiglio",
    "andamento della gestione",
    "fatti di rilievo",
]


def _densita_numerica(testo: str) -> float:
    """Calcola densità di numeri formattati nel testo."""
    lines = testo.strip().split("\n")
    numeri = re.findall(r'\b\d{1,3}(?:\.\d{3})+\b', testo)
    return len(numeri) / max(len(lines), 1)


def _identifica_pagine_ni(testi: list[dict]) -> list[int]:
    """Identifica pagine della nota integrativa.

    Criteri: bassa densità numerica + presenza keywords NI.
    """
    pagine_ni = []
    for item in testi:
        testo_lower = item["testo"].lower()
        pagina_0based = item["pagina"] - 1  # pdfplumber usa 1-based

        # Verifica keywords
        keyword_hits = sum(1 for kw in _KEYWORDS_NI if kw in testo_lower)
        if keyword_hits == 0:
            continue

        # La NI ha poca densità numerica rispetto ai prospetti
        densita = _densita_numerica(item["testo"])
        if densita < 0.3 or keyword_hits >= 3:
            pagine_ni.append(pagina_0based)

    return pagine_ni


def _identifica_pagine_relazione(testi: list[dict]) -> list[int]:
    """Identifica pagine della relazione sulla gestione."""
    pagine = []
    for item in testi:
        testo_lower = item["testo"].lower()
        pagina_0based = item["pagina"] - 1
        if any(kw in testo_lower for kw in _KEYWORDS_RELAZIONE):
            pagine.append(pagina_0based)
    return pagine


def _ricognizione_qualitativa(pdf_path: str) -> dict:
    """Identifica pagine NI e relazione sulla gestione."""
    testi = estrai_testo_pdf(pdf_path)

    ni_pagine = _identifica_pagine_ni(testi)
    rel_pagine = _identifica_pagine_relazione(testi)

    return {
        "ni_pagine": ni_pagine,
        "relazione_pagine": rel_pagine,
        "nota_integrativa_presente": len(ni_pagine) > 0,
        "relazione_gestione_presente": len(rel_pagine) > 0,
    }


# ---------------------------------------------------------------------------
# Fase 2 — Estrazione qualitativa con Claude
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """Sei un esperto di bilanci italiani. Analizza il testo della nota integrativa e della relazione sulla gestione e produci un output JSON strutturato.

PRIORITÀ (estrai solo queste, non inventare):
1. ALTA: informazioni che cambiano la riclassifica:
   - Split voci ambigue (es. "altri debiti" che include finanziamenti soci)
   - Scadenze debiti (entro/oltre esercizio)
   - Natura fondi rischi (operativi vs finanziari)
2. MEDIA: flags strutturali:
   - Rivalutazioni ex lege (D.L. 104/2020 o precedenti)
   - Operazioni straordinarie (fusioni, scissioni, acquisizioni)
   - Leasing operativo significativo
3. BASSA: informazioni contestuali:
   - Criteri di valutazione
   - Composizione ricavi
   - Numero dipendenti

REGOLE:
1. Restituisci SOLO JSON valido, nessun testo prima o dopo.
2. Ogni flag/annotazione DEVE avere fonte_pagina verificabile.
3. NON inventare informazioni: se il dato non è nel testo, non includerlo.
4. Distingui fatti certi da interpretazioni.

FORMATO OUTPUT:
{
  "flags": [
    {"tipo": "flags_strutturali|flags_contabili", "codice": "...", "dettaglio": "...", "impatto_voci": ["..."], "fonte_pagina": 0}
  ],
  "annotazioni_voci": [
    {"voce_id": "...", "nota": "...", "suggerimento_riclassifica": "...", "fonte_pagina": 0}
  ],
  "criteri_valutazione": {},
  "eventi_rilevanti": [],
  "composizione_ricavi": {},
  "dipendenti": {}
}"""


def _estrazione_con_claude(
    pdf_path: str,
    ni_pagine: list[int],
    rel_pagine: list[int],
    schema: dict,
    model: str = "claude-sonnet-4-20250514",
) -> dict:
    """Invia testo NI a Claude per estrazione qualitativa."""
    client = crea_client()

    # Limita a prime 15 pagine NI (info rilevante è all'inizio)
    pagine_da_leggere = sorted(set(ni_pagine[:15] + rel_pagine[:5]))

    if not pagine_da_leggere:
        return {"flags": [], "annotazioni_voci": []}

    testi = estrai_testo_pdf(pdf_path, pagine_da_leggere)

    parti = []
    for item in testi:
        parti.append(f"\n--- PAGINA {item['pagina']} ---")
        parti.append(item["testo"])
    testo_completo = "\n".join(parti)

    # Limita lunghezza per non eccedere context
    if len(testo_completo) > 50_000:
        testo_completo = testo_completo[:50_000] + "\n\n[...TESTO TRONCATO...]"

    # Contesto voci dallo schema per guidare l'estrazione
    voci_ambigue = []
    for sez in ("sp", "ce"):
        for v in schema.get(sez, []):
            vid = v.get("id", "")
            if any(kw in vid for kw in ("altri_debiti", "altri_crediti", "fondi_rischi", "fondi_per_rischi")):
                voci_ambigue.append(f"- {v['label']} (id: {vid})")

    contesto_voci = ""
    if voci_ambigue:
        contesto_voci = (
            "\n\nVOCI AMBIGUE DA CHIARIRE:\n"
            + "\n".join(voci_ambigue)
            + "\nCerca informazioni sulla composizione di queste voci nella nota integrativa."
        )

    user_msg = f"""Analizza questa nota integrativa/relazione sulla gestione.
Azienda: {schema.get('azienda', 'N/D')}
Anni: {schema.get('anni_estratti', [])}
{contesto_voci}

{testo_completo}"""

    response = client.messages.create(
        model=model,
        max_tokens=8192,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    text = response.content[0].text.strip()
    return _estrai_json_da_risposta(text)


def _estrai_json_da_risposta(testo: str) -> dict:
    """Estrae JSON dalla risposta di Claude."""
    testo = testo.strip()

    try:
        return json.loads(testo)
    except json.JSONDecodeError:
        pass

    # Blocco markdown
    match = re.search(r"```(?:json)?\s*\n(.*?)\n\s*```", testo, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Primo { ... } bilanciato
    start = testo.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(testo)):
            if testo[i] == "{":
                depth += 1
            elif testo[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(testo[start:i + 1])
                    except json.JSONDecodeError:
                        break

    return {"flags": [], "annotazioni_voci": [], "error": "JSON non parsabile"}


# ---------------------------------------------------------------------------
# API pubblica
# ---------------------------------------------------------------------------

def estrai_qualitativo(
    pdf_path: str,
    schema: dict,
    model: str = "claude-sonnet-4-20250514",
) -> dict:
    """Estrae informazioni qualitative dalla nota integrativa.

    Args:
        pdf_path: Path al PDF.
        schema: Schema normalizzato (per contesto voci).

    Returns:
        Dict con flags, annotazioni_voci, criteri_valutazione, etc.
    """
    pdf_path = str(Path(pdf_path).resolve())
    azienda = schema.get("azienda", "N/D")
    print(f"[qualitativo] Estrazione qualitativa da: {Path(pdf_path).name}")

    # --- Fase 1: Ricognizione ---
    print("[qualitativo] Fase 1: Ricognizione pagine NI...")
    ricognizione = _ricognizione_qualitativa(pdf_path)

    ni_pagine = ricognizione["ni_pagine"]
    rel_pagine = ricognizione["relazione_pagine"]
    ni_presente = ricognizione["nota_integrativa_presente"]

    print(f"[qualitativo]   NI: {len(ni_pagine)} pagine trovate")
    print(f"[qualitativo]   Relazione: {len(rel_pagine)} pagine trovate")

    if not ni_presente:
        print("[qualitativo]   NI non trovata (bilancio abbreviato?)")
        return {
            "azienda": azienda,
            "nota_integrativa_presente": False,
            "relazione_gestione_presente": ricognizione["relazione_gestione_presente"],
            "flags": [],
            "annotazioni_voci": [],
            "criteri_valutazione": {},
            "eventi_rilevanti": [],
            "composizione_ricavi": {},
            "dipendenti": {},
        }

    # --- Fase 2: Estrazione con Claude ---
    print("[qualitativo] Fase 2: Estrazione con Claude...")
    risultato = _estrazione_con_claude(
        pdf_path, ni_pagine, rel_pagine, schema, model,
    )

    # Merge con metadata ricognizione
    output = {
        "azienda": azienda,
        "nota_integrativa_presente": True,
        "relazione_gestione_presente": ricognizione["relazione_gestione_presente"],
        "flags": risultato.get("flags", []),
        "annotazioni_voci": risultato.get("annotazioni_voci", []),
        "criteri_valutazione": risultato.get("criteri_valutazione", {}),
        "eventi_rilevanti": risultato.get("eventi_rilevanti", []),
        "composizione_ricavi": risultato.get("composizione_ricavi", {}),
        "dipendenti": risultato.get("dipendenti", {}),
    }

    n_flags = len(output["flags"])
    n_ann = len(output["annotazioni_voci"])
    print(f"[qualitativo]   Completato: {n_flags} flags, {n_ann} annotazioni")

    return output


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python -m agents.estrattore_qualitativo <pdf_path> [schema_json_path]")
        sys.exit(1)

    pdf = sys.argv[1]

    # Carica schema se disponibile
    schema = {}
    if len(sys.argv) > 2:
        schema = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))

    result = estrai_qualitativo(pdf, schema)

    out_path = Path("data/output/qualitativo_result.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nRisultato salvato in: {out_path}")
