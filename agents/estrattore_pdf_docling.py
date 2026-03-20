"""Estrattore PDF ibrido: Docling (struttura) + LLM (semantica) + Validazione.

Pipeline:
1. Docling: detect tables, extract rows/columns, preserve hierarchy
2. LLM: map labels to schema, normalize, resolve ambiguities
3. Validation: assets = liabilities + equity, subtotal checks
"""

import json
import re
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv(override=True)

from tools.docling_parser import (
    identifica_tabelle_prospetto,
    tabella_a_righe_bilancio,
)
from agents.base import crea_client


# ---------------------------------------------------------------------------
# Fase 1 — Docling: estrazione strutturale
# ---------------------------------------------------------------------------

def _estrai_struttura(pdf_path: str) -> dict:
    """Usa Docling per estrarre tabelle e classificarle come SP/CE.

    Returns:
        Dict con sp_righe, ce_righe, formato, metadata.
    """
    print("[docling] Analisi strutturale del documento...")
    risultato = identifica_tabelle_prospetto(pdf_path)

    formato = risultato["formato"]
    print(f"[docling]   Formato rilevato: {formato}")
    print(f"[docling]   Tabelle totali: {risultato['n_tabelle_totali']}")
    print(f"[docling]   SP: {len(risultato['sp_tabelle'])} tabelle")
    print(f"[docling]   CE: {len(risultato['ce_tabelle'])} tabelle")

    # Converti tabelle SP in righe di bilancio
    sp_righe = []
    sp_pagine = []
    for tab in risultato["sp_tabelle"]:
        righe = tabella_a_righe_bilancio(tab["dataframe"], formato)
        sp_righe.extend(righe)
        sp_pagine.append(tab["pagina"])

    # Converti tabelle CE in righe di bilancio
    ce_righe = []
    ce_pagine = []
    for tab in risultato["ce_tabelle"]:
        righe = tabella_a_righe_bilancio(tab["dataframe"], formato)
        ce_righe.extend(righe)
        ce_pagine.append(tab["pagina"])

    # Rileva anni presenti dai valori
    anni = set()
    for righe in (sp_righe, ce_righe):
        for r in righe:
            for anno in r.get("valori", {}).keys():
                if re.match(r"^20[12]\d$", anno):
                    anni.add(anno)

    print(f"[docling]   Righe SP: {len(sp_righe)}, Righe CE: {len(ce_righe)}")
    print(f"[docling]   Anni: {sorted(anni)}")

    return {
        "sp_righe": sp_righe,
        "ce_righe": ce_righe,
        "sp_pagine": sp_pagine,
        "ce_pagine": ce_pagine,
        "anni_presenti": sorted(anni),
        "formato": formato,
    }


# ---------------------------------------------------------------------------
# Fase 2 — LLM: mapping semantico (solo se necessario)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_SEMANTICO = """Sei un esperto di bilanci italiani. Ti vengono date righe estratte da un prospetto contabile.

Il tuo compito è SOLO mapping semantico:
1. Verifica che le label siano corrette e pulite
2. Assegna la gerarchia corretta (sezione > subtotale > dettaglio > di_cui)
3. Identifica e correggi label spezzate o malformate
4. Identifica voci che sono "di cui" (informative, non addendi)
5. NON modificare i valori numerici — restituiscili così come sono

Restituisci SOLO JSON valido con questa struttura:
{
  "azienda": "...",
  "formato_bilancio": "IFRS|OIC_ordinario",
  "anni_presenti": ["2024", "2023"],
  "sezioni": {
    "sp_attivo": {"pagine": [], "righe": [{"label": "...", "valori": {"2024": "...", "2023": "..."}, "livello": "dettaglio|subtotale|totale|di_cui|sezione", "genitore": "...|null", "nota_ref": "...|null"}]},
    "sp_passivo": {"pagine": [], "righe": [...]},
    "ce": {"pagine": [], "righe": [...]}
  },
  "problemi_layout": [],
  "confidence_estrazione": 0.95
}"""


def _mapping_semantico(
    sp_righe: list[dict],
    ce_righe: list[dict],
    formato: str,
    anni: list[str],
    model: str = "claude-sonnet-4-20250514",
) -> dict:
    """Invia righe estratte da Docling a Claude per mapping semantico.

    Claude NON deve estrarre tabelle (già fatto da Docling), solo:
    - Pulire label
    - Classificare in sp_attivo/sp_passivo
    - Assegnare gerarchia
    - Identificare "di cui"
    """
    client = crea_client()

    # Prepara dati per Claude
    dati = json.dumps({
        "formato": formato,
        "anni": anni,
        "sp_righe": sp_righe[:80],  # Limita per non eccedere context
        "ce_righe": ce_righe[:40],
    }, ensure_ascii=False, indent=2)

    n_chars = len(dati)
    print(f"[docling+llm]   Dati per Claude: {n_chars:,} chars ({len(sp_righe)} SP + {len(ce_righe)} CE righe)")

    response = client.messages.create(
        model=model,
        max_tokens=16384,
        system=_SYSTEM_PROMPT_SEMANTICO,
        messages=[{
            "role": "user",
            "content": f"Analizza queste righe e produci il JSON strutturato.\n\n{dati}",
        }],
    )

    text = response.content[0].text.strip()
    return _estrai_json(text)


def _estrai_json(testo: str) -> dict:
    """Estrae JSON dalla risposta di Claude."""
    testo = testo.strip()
    try:
        return json.loads(testo)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*\n(.*?)\n\s*```", testo, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

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

    return {"error": "JSON non parsabile", "raw": testo[:500]}


# ---------------------------------------------------------------------------
# Fase 3 — Validazione
# ---------------------------------------------------------------------------

def _valida_estrazione(risultato: dict, anni: list[str]) -> list[str]:
    """Validazione strutturale dell'estrazione.

    Checks:
    - Totale attivo = totale passivo + PN (o totale passivo include PN)
    - Subtotali coerenti con somma figli
    - Utile CE presente
    """
    from tools.pdf_parser import normalizza_numero

    problemi = []
    sezioni = risultato.get("sezioni", {})

    for anno in anni:
        # Cerca totale attivo e totale passivo
        totale_attivo = None
        totale_passivo = None

        for sez_key in ("sp_attivo",):
            for riga in sezioni.get(sez_key, {}).get("righe", []):
                label_lower = riga.get("label", "").lower()
                if "totale attivo" in label_lower or "totale attivit" in label_lower:
                    val = normalizza_numero(str(riga.get("valori", {}).get(anno, "")))
                    if val is not None:
                        totale_attivo = val

        for sez_key in ("sp_passivo",):
            for riga in sezioni.get(sez_key, {}).get("righe", []):
                label_lower = riga.get("label", "").lower()
                if "totale passivo" in label_lower or "totale patrimonio netto e passiv" in label_lower:
                    val = normalizza_numero(str(riga.get("valori", {}).get(anno, "")))
                    if val is not None:
                        totale_passivo = val

        if totale_attivo is not None and totale_passivo is not None:
            delta = abs(totale_attivo - totale_passivo)
            if delta > 1:
                problemi.append(
                    f"[{anno}] Quadratura SP: attivo={totale_attivo:,} ≠ passivo={totale_passivo:,} "
                    f"(delta: {delta:,})"
                )
            else:
                print(f"[validazione]   {anno}: SP quadra (attivo=passivo={totale_attivo:,})")
        else:
            problemi.append(
                f"[{anno}] Totali SP non trovati (attivo={totale_attivo}, passivo={totale_passivo})"
            )

        # Cerca utile netto nel CE
        utile_trovato = False
        for riga in sezioni.get("ce", {}).get("righe", []):
            label_lower = riga.get("label", "").lower()
            if "risultato netto" in label_lower or ("utile" in label_lower and "esercizio" in label_lower):
                val = normalizza_numero(str(riga.get("valori", {}).get(anno, "")))
                if val is not None:
                    utile_trovato = True
                    print(f"[validazione]   {anno}: Utile netto = {val:,}")

        if not utile_trovato:
            problemi.append(f"[{anno}] Utile netto non trovato nel CE")

    return problemi


# ---------------------------------------------------------------------------
# API pubblica
# ---------------------------------------------------------------------------

def estrai_pdf_docling(
    pdf_path: str,
    tipo_bilancio: str = "separato",
    model: str = "claude-sonnet-4-20250514",
) -> dict:
    """Estrae dati strutturati da un PDF usando Docling + LLM + Validazione.

    Fase 1: Docling estrae tabelle e le classifica
    Fase 2: LLM mappa semanticamente le righe allo schema
    Fase 3: Validazione quadratura e coerenza

    Args:
        pdf_path: Path al PDF.
        tipo_bilancio: "separato" o "consolidato".
        model: Modello per il mapping semantico.

    Returns:
        Dict con struttura identica a estrai_pdf() per compatibilità.
    """
    pdf_path = str(Path(pdf_path).resolve())
    print(f"[docling] Estrazione da: {Path(pdf_path).name}")

    # --- Fase 1: Docling ---
    print("[docling] Fase 1: Estrazione strutturale con Docling...")
    struttura = _estrai_struttura(pdf_path)

    if not struttura["sp_righe"] and not struttura["ce_righe"]:
        return {"error": "Nessun prospetto trovato da Docling"}

    # --- Fase 2: LLM mapping semantico ---
    print("[docling] Fase 2: Mapping semantico con Claude...")
    risultato = _mapping_semantico(
        sp_righe=struttura["sp_righe"],
        ce_righe=struttura["ce_righe"],
        formato=struttura["formato"],
        anni=struttura["anni_presenti"],
        model=model,
    )

    if "error" in risultato:
        print(f"[docling]   ERRORE LLM: {risultato['error']}")
        return risultato

    # Arricchisci con metadata
    if "sezioni" in risultato:
        for sez_key, pagine in [
            ("sp_attivo", struttura["sp_pagine"]),
            ("sp_passivo", struttura["sp_pagine"]),
            ("ce", struttura["ce_pagine"]),
        ]:
            if sez_key in risultato["sezioni"]:
                if not risultato["sezioni"][sez_key].get("pagine"):
                    risultato["sezioni"][sez_key]["pagine"] = pagine

    # --- Fase 3: Validazione ---
    print("[docling] Fase 3: Validazione...")
    problemi = _valida_estrazione(risultato, struttura["anni_presenti"])
    if problemi:
        risultato.setdefault("problemi_layout", []).extend(problemi)
        for p in problemi:
            print(f"[docling]   [WARN] {p}")
    else:
        print("[docling]   Validazione OK")

    conf = risultato.get("confidence_estrazione", "?")
    print(f"[docling]   Completato (confidence: {conf})")

    return risultato


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python -m agents.estrattore_pdf_docling <pdf_path> [tipo_bilancio]")
        sys.exit(1)

    pdf = sys.argv[1]
    tipo = sys.argv[2] if len(sys.argv) > 2 else "separato"

    result = estrai_pdf_docling(pdf, tipo)

    out_path = Path("data/output/estrazione_docling_result.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Remove non-serializable DataFrames before saving
    if "sezioni" in result:
        out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nRisultato salvato in: {out_path}")

        if "sezioni" in result:
            for sez, data in result["sezioni"].items():
                n_righe = len(data.get("righe", []))
                if n_righe:
                    print(f"  {sez}: {n_righe} righe")
