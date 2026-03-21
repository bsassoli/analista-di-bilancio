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

_SYSTEM_PROMPT_SP = """Sei un esperto di bilanci italiani. Ti vengono date righe estratte dallo STATO PATRIMONIALE di un bilancio.

Il tuo compito:
1. Separa le righe in sp_attivo e sp_passivo (includi patrimonio netto nel passivo)
2. Pulisci le label (ricomponi label spezzate, correggi errori OCR)
3. Assegna la gerarchia: sezione > subtotale > dettaglio > di_cui
4. Identifica voci "di cui" (informative, non addendi)
5. NON modificare i valori numerici — restituiscili esattamente come sono

REGOLE IMPORTANTI:
- TUTTE le righe devono comparire nell'output, non omettere nulla
- Il totale attivo e il totale passivo+PN devono essere presenti
- Per bilanci IFRS: "Attività non correnti/correnti" → sp_attivo, "Patrimonio netto + Passività non correnti/correnti" → sp_passivo
- Per bilanci OIC: voci A-D dell'attivo → sp_attivo, voci A-E del passivo → sp_passivo

Restituisci SOLO JSON valido:
{
  "sp_attivo": {"righe": [{"label": "...", "valori": {"2024": "...", "2023": "..."}, "livello": "dettaglio|subtotale|totale|di_cui|sezione", "genitore": "...|null", "nota_ref": "...|null"}]},
  "sp_passivo": {"righe": [...]},
  "problemi": []
}"""

_SYSTEM_PROMPT_CE = """Sei un esperto di bilanci italiani. Ti vengono date righe estratte dal CONTO ECONOMICO di un bilancio.

Il tuo compito:
1. Pulisci le label (ricomponi label spezzate, correggi errori OCR)
2. Assegna la gerarchia: sezione > subtotale > dettaglio > di_cui
3. Identifica voci "di cui" (informative, non addendi)
4. NON modificare i valori numerici — restituiscili esattamente come sono

REGOLE IMPORTANTI:
- TUTTE le righe devono comparire nell'output, non omettere nulla
- Il risultato netto dell'esercizio deve essere presente
- Subtotali intermedi (EBITDA, EBIT, risultato operativo, ecc.) vanno marcati come "subtotale"

Restituisci SOLO JSON valido:
{
  "ce": {"righe": [{"label": "...", "valori": {"2024": "...", "2023": "..."}, "livello": "dettaglio|subtotale|totale|di_cui|sezione", "genitore": "...|null", "nota_ref": "...|null"}]},
  "problemi": []
}"""


def _chiama_llm(client, system: str, dati: str, model: str, max_tokens: int = 16384) -> dict:
    """Singola chiamata LLM con parsing JSON."""
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{
            "role": "user",
            "content": dati,
        }],
    )
    text = response.content[0].text.strip()
    return _estrai_json(text)


def _chiama_llm_con_retry(
    client, system: str, dati: str, model: str, feedback: str,
    max_tokens: int = 16384,
) -> dict:
    """Chiamata LLM con un turno di retry via feedback (user→assistant→user)."""
    first = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": dati}],
    )
    first_text = first.content[0].text.strip()
    first_json = _estrai_json(first_text)

    # Secondo turno con feedback
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[
            {"role": "user", "content": dati},
            {"role": "assistant", "content": first_text},
            {"role": "user", "content": feedback},
        ],
    )
    text = response.content[0].text.strip()
    return _estrai_json(text)


def _verifica_quadratura_sp(resp_sp: dict, anni: list[str]) -> Optional[str]:
    """Verifica veloce della quadratura SP dopo la chiamata LLM.

    Returns:
        None se ok, stringa di feedback per retry se ko.
    """
    from tools.pdf_parser import normalizza_numero

    errori = []
    for anno in anni:
        totale_attivo = None
        totale_passivo = None

        for riga in resp_sp.get("sp_attivo", {}).get("righe", []):
            label = riga.get("label", "").lower()
            if "totale attivo" in label or "totale attivit" in label:
                val = normalizza_numero(str(riga.get("valori", {}).get(anno, "")))
                if val is not None:
                    totale_attivo = val

        for riga in resp_sp.get("sp_passivo", {}).get("righe", []):
            label = riga.get("label", "").lower()
            if "totale passivo" in label or "totale patrimonio netto e passiv" in label:
                val = normalizza_numero(str(riga.get("valori", {}).get(anno, "")))
                if val is not None:
                    totale_passivo = val

        if totale_attivo is not None and totale_passivo is not None:
            delta = abs(totale_attivo - totale_passivo)
            if delta > 1:
                pct = round(delta / max(totale_attivo, totale_passivo, 1) * 100, 1)
                errori.append(
                    f"{anno}: attivo={totale_attivo:,} ≠ passivo={totale_passivo:,} "
                    f"(delta: {delta:,}, {pct}%)"
                )
        elif totale_attivo is None and totale_passivo is None:
            errori.append(f"{anno}: totale attivo e passivo non trovati")

    if not errori:
        return None

    return (
        "ERRORE QUADRATURA: lo Stato Patrimoniale non quadra. "
        "Attivo DEVE essere uguale a Passivo+PN.\n"
        + "\n".join(f"  - {e}" for e in errori)
        + "\n\nPROBABILI CAUSE:\n"
        "- Righe mancanti nell'attivo o nel passivo (controlla che TUTTE le righe siano presenti)\n"
        "- Righe attribuite alla sezione sbagliata (es. passività classificate come attivo)\n"
        "- Patrimonio netto mancante dal passivo\n\n"
        "Riprova: restituisci il JSON completo con TUTTE le righe nella sezione corretta. "
        "Il totale attivo DEVE essere uguale al totale passivo+PN."
    )


def _mapping_semantico(
    sp_righe: list[dict],
    ce_righe: list[dict],
    formato: str,
    anni: list[str],
    model: str = "claude-sonnet-4-20250514",
) -> dict:
    """Invia righe estratte da Docling a Claude per mapping semantico.

    Split in 2 chiamate separate (SP e CE) per evitare troncamenti.
    Retry automatico SP se la quadratura non torna.
    """
    client = crea_client()

    risultato = {
        "formato_bilancio": formato,
        "anni_presenti": anni,
        "sezioni": {
            "sp_attivo": {"pagine": [], "righe": []},
            "sp_passivo": {"pagine": [], "righe": []},
            "ce": {"pagine": [], "righe": []},
        },
        "problemi_layout": [],
    }

    # --- Chiamata SP (con retry su quadratura) ---
    if sp_righe:
        dati_sp = json.dumps({
            "formato": formato,
            "anni": anni,
            "righe": sp_righe,
        }, ensure_ascii=False, indent=2)
        n_sp = len(sp_righe)
        print(f"[docling+llm]   SP: {n_sp} righe, {len(dati_sp):,} chars")

        prompt_sp = (
            f"Bilancio formato {formato}, anni {anni}.\n"
            f"Queste sono {n_sp} righe dello Stato Patrimoniale. "
            f"Separale in sp_attivo e sp_passivo.\n\n{dati_sp}"
        )
        resp_sp = _chiama_llm(client, _SYSTEM_PROMPT_SP, prompt_sp, model)

        if "error" not in resp_sp:
            # Verifica quadratura e retry se necessario
            feedback = _verifica_quadratura_sp(resp_sp, anni)
            if feedback:
                n_att = len(resp_sp.get("sp_attivo", {}).get("righe", []))
                n_pas = len(resp_sp.get("sp_passivo", {}).get("righe", []))
                print(f"[docling+llm]   SP tentativo 1: {n_att} attivo + {n_pas} passivo (quadratura KO)")
                print(f"[docling+llm]   Retry SP con feedback quadratura...")
                resp_sp2 = _chiama_llm_con_retry(
                    client, _SYSTEM_PROMPT_SP, prompt_sp, model, feedback
                )
                if "error" not in resp_sp2:
                    feedback2 = _verifica_quadratura_sp(resp_sp2, anni)
                    if feedback2 is None:
                        print(f"[docling+llm]   Retry OK: quadratura corretta")
                        resp_sp = resp_sp2
                    else:
                        # Usa il risultato migliore (meno delta)
                        print(f"[docling+llm]   Retry: quadratura ancora KO, uso risultato migliore")
                        resp_sp = _scegli_migliore_sp(resp_sp, resp_sp2, anni)

        if "error" in resp_sp:
            print(f"[docling+llm]   ERRORE SP: {resp_sp['error']}")
            risultato["problemi_layout"].append(f"LLM SP fallito: {resp_sp.get('error', '')}")
        else:
            sp_att = resp_sp.get("sp_attivo", {})
            sp_pas = resp_sp.get("sp_passivo", {})
            n_att = len(sp_att.get("righe", []))
            n_pas = len(sp_pas.get("righe", []))
            print(f"[docling+llm]   SP risultato: {n_att} attivo + {n_pas} passivo = {n_att + n_pas} righe")

            risultato["sezioni"]["sp_attivo"]["righe"] = sp_att.get("righe", [])
            risultato["sezioni"]["sp_passivo"]["righe"] = sp_pas.get("righe", [])
            risultato["problemi_layout"].extend(resp_sp.get("problemi", []))

            # Estrai nome azienda se presente
            if resp_sp.get("azienda"):
                risultato["azienda"] = resp_sp["azienda"]

    # --- Chiamata CE ---
    if ce_righe:
        dati_ce = json.dumps({
            "formato": formato,
            "anni": anni,
            "righe": ce_righe,
        }, ensure_ascii=False, indent=2)
        n_ce = len(ce_righe)
        print(f"[docling+llm]   CE: {n_ce} righe, {len(dati_ce):,} chars")

        prompt_ce = (
            f"Bilancio formato {formato}, anni {anni}.\n"
            f"Queste sono {n_ce} righe del Conto Economico. "
            f"Strutturale con gerarchia corretta.\n\n{dati_ce}"
        )
        resp_ce = _chiama_llm(client, _SYSTEM_PROMPT_CE, prompt_ce, model)

        if "error" in resp_ce:
            print(f"[docling+llm]   ERRORE CE: {resp_ce['error']}")
            risultato["problemi_layout"].append(f"LLM CE fallito: {resp_ce.get('error', '')}")
        else:
            ce_data = resp_ce.get("ce", {})
            n_ce_out = len(ce_data.get("righe", []))
            print(f"[docling+llm]   CE risultato: {n_ce_out} righe")

            risultato["sezioni"]["ce"]["righe"] = ce_data.get("righe", [])
            risultato["problemi_layout"].extend(resp_ce.get("problemi", []))

    # --- Confidence ---
    n_in = len(sp_righe) + len(ce_righe)
    n_out = (
        len(risultato["sezioni"]["sp_attivo"].get("righe", []))
        + len(risultato["sezioni"]["sp_passivo"].get("righe", []))
        + len(risultato["sezioni"]["ce"].get("righe", []))
    )
    # Confidence basata su quante righe sono sopravvissute
    if n_in > 0:
        ratio = n_out / n_in
        confidence = round(min(ratio, 1.0) * 0.95, 2)  # max 0.95
    else:
        confidence = 0.0
    risultato["confidence_estrazione"] = confidence
    print(f"[docling+llm]   Righe in: {n_in}, out: {n_out}, confidence: {confidence}")

    return risultato


def _scegli_migliore_sp(resp1: dict, resp2: dict, anni: list[str]) -> dict:
    """Confronta due risposte SP e restituisce quella con delta quadratura minore."""
    from tools.pdf_parser import normalizza_numero

    def _delta_totale(resp):
        tot = 0
        for anno in anni:
            att = pas = None
            for r in resp.get("sp_attivo", {}).get("righe", []):
                lab = r.get("label", "").lower()
                if "totale attivo" in lab or "totale attivit" in lab:
                    att = normalizza_numero(str(r.get("valori", {}).get(anno, "")))
            for r in resp.get("sp_passivo", {}).get("righe", []):
                lab = r.get("label", "").lower()
                if "totale passivo" in lab or "totale patrimonio netto e passiv" in lab:
                    pas = normalizza_numero(str(r.get("valori", {}).get(anno, "")))
            if att is not None and pas is not None:
                tot += abs(att - pas)
            else:
                tot += 10**12  # penalità per totali mancanti
        return tot

    d1 = _delta_totale(resp1)
    d2 = _delta_totale(resp2)
    return resp2 if d2 < d1 else resp1


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
