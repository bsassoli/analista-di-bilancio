"""Estrattore numerico: converte l'output dell'estrattore PDF in schema normalizzato.

Input: output strutturato dell'estrattore PDF (righe con valori stringa)
       oppure ExtractionBundle tipizzato
Output: schema normalizzato JSON (valori interi, ID, aggregati)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from tools.pdf_parser import normalizza_numero, genera_id
from tools.calcolatori import variazione_yoy
from tools.schema import crea_voce
from tools.evidence_schema import (
    ExtractionBundle,
    ExtractedRow,
    ClassificationHint,
)


def _converti_sezione(righe: list[dict], anni: list[str]) -> list[dict]:
    """Converte righe dell'estrattore PDF in voci normalizzate."""
    voci = []
    ids_visti = set()

    for riga in righe:
        label = riga.get("label", "").strip()
        livello_pdf = riga.get("livello", "dettaglio")
        genitore = riga.get("genitore", "") or ""

        # Salta intestazioni di sezione senza valori
        valori_raw = riga.get("valori", {})
        if not valori_raw or all(not v for v in valori_raw.values()):
            if livello_pdf == "sezione":
                continue
            continue

        # Salta "di cui" (informative, non sommabili)
        if livello_pdf == "di_cui":
            continue

        # Converti valori stringa in interi
        valori = {}
        for anno in anni:
            val_raw = valori_raw.get(anno, "")
            if val_raw:
                valori[anno] = normalizza_numero(str(val_raw))
            else:
                valori[anno] = 0

        # Genera ID — per voci OIC generiche (esigibili entro/oltre, totale crediti)
        # componi con il genitore per renderle uniche
        base_id = genera_id(label)
        voce_id = base_id

        if base_id in ids_visti and genitore:
            # Preponi il genitore per disambiguare
            voce_id = genera_id(genitore) + "_" + base_id

        # Se ancora duplicato, aggiungi un suffisso numerico
        if voce_id in ids_visti:
            n = 2
            while f"{voce_id}_{n}" in ids_visti:
                n += 1
            voce_id = f"{voce_id}_{n}"

        ids_visti.add(voce_id)

        # Mappa livello
        if livello_pdf in ("totale",):
            livello = 1
        elif livello_pdf in ("subtotale",):
            livello = 2
        else:
            livello = 3

        # Flags automatici
        flags = []
        anni_vals = [v for v in valori.values() if v is not None and v != 0]
        if len(anni_vals) >= 2:
            vals = list(valori.values())
            if vals[0] is not None and vals[1] is not None and vals[1] != 0:
                var = variazione_yoy(vals[0], vals[1])
                if var is not None and abs(var) > 0.3:
                    flags.append("variazione_significativa_yoy")

        if any(v is None for v in valori.values()):
            flags.append("dato_mancante")

        voce = crea_voce(
            id=voce_id,
            label=label,
            livello=livello,
            aggregato="",
            valore=valori,
            fonte_riga_bilancio=riga.get("nota_ref", ""),
            non_standard=False,
            flags=flags,
            note=genitore,
        )
        voci.append(voce)

    return voci


def normalizza_estrazione(estrazione_pdf: dict) -> dict:
    """Converte l'output dell'estrattore PDF nello schema normalizzato.

    Args:
        estrazione_pdf: Output di estrai_pdf() con sezioni sp_attivo, sp_passivo, ce.

    Returns:
        Schema normalizzato compatibile con il resto della pipeline.
    """
    sezioni = estrazione_pdf.get("sezioni", {})
    anni = estrazione_pdf.get("anni_presenti", [])
    azienda = estrazione_pdf.get("azienda", "")
    formato = estrazione_pdf.get("formato_bilancio", "")

    # Unisci SP attivo e passivo
    righe_sp = (
        sezioni.get("sp_attivo", {}).get("righe", [])
        + sezioni.get("sp_passivo", {}).get("righe", [])
    )
    righe_ce = sezioni.get("ce", {}).get("righe", [])

    voci_sp = _converti_sezione(righe_sp, anni)
    voci_ce = _converti_sezione(righe_ce, anni)

    # Cerca totali
    totale_attivo = {}
    totale_passivo = {}
    utile = {}

    for v in voci_sp:
        label_lower = v["label"].lower()
        if "totale attivo" in label_lower or "totale attivit" in label_lower:
            totale_attivo = v["valore"]
        if "totale passivo" in label_lower or "totale patrimonio netto e passivit" in label_lower:
            totale_passivo = v["valore"]

    # Cerca utile nel CE — fonte più affidabile (include quota terzi per consolidati)
    for v in voci_ce:
        vid = v["id"].lower()
        label_lower = v["label"].lower()
        # Utile consolidato (bilanci consolidati OIC: "21) Utile (perdita) consolidati")
        if "consolidat" in vid and ("utile" in vid or "perdita" in vid):
            utile = v["valore"]
            break
        # IFRS: "RISULTATO NETTO D'ESERCIZIO"
        if "risultato_netto_d_esercizio" in vid and "funzionamento" not in vid and "complessivo" not in vid:
            utile = v["valore"]
            break
        # OIC separato: "21) Utile (perdita) dell'esercizio"
        if ("utile" in label_lower and "esercizio" in label_lower
                and "terzi" not in label_lower and "complessivo" not in label_lower
                and "funzionamento" not in label_lower):
            utile = v["valore"]
            # Non break: potrebbe essercene uno più specifico dopo

    # Fallback: cerca nello SP
    if not utile:
        for v in voci_sp:
            label_lower = v["label"].lower()
            if "utile" in label_lower and "perdita" in label_lower and "terzi" not in label_lower:
                utile = v["valore"]

    # Pagine
    pagine_sp = (
        sezioni.get("sp_attivo", {}).get("pagine", [])
        + sezioni.get("sp_passivo", {}).get("pagine", [])
    )
    pagine_ce = sezioni.get("ce", {}).get("pagine", [])

    schema = {
        "azienda": azienda,
        "anni_estratti": [int(a) for a in anni],
        "tipo_bilancio": "ordinario",
        "sp": voci_sp,
        "ce": voci_ce,
        "metadata": {
            "pagine_sp": sorted(set(pagine_sp)),
            "pagine_ce": sorted(set(pagine_ce)),
            "totale_attivo_dichiarato": totale_attivo,
            "totale_passivo_dichiarato": totale_passivo,
            "utile_dichiarato": utile,
            "formato": formato,
        },
    }

    return schema


# ---------------------------------------------------------------------------
# Bundle-aware normalisation
# ---------------------------------------------------------------------------

def _converti_extracted_rows(
    rows: list[ExtractedRow],
    anni: list[str],
    hints: Optional[list[ClassificationHint]] = None,
) -> tuple[list[dict], list[dict]]:
    """Convert typed ExtractedRow objects into normalised voce dicts.

    Unlike _converti_sezione, this:
    - Preserves di_cui rows as separate metadata entries
    - Attaches classification hints as extra metadata
    - Tracks extraction_method and source_page per voce

    Returns:
        (voci, di_cui_voci) — main rows and informative di_cui rows.
    """
    hints_map: dict[str, list[ClassificationHint]] = {}
    for h in (hints or []):
        hints_map.setdefault(h.target_row_id, []).append(h)

    voci = []
    di_cui_voci = []
    ids_visti: set[str] = set()

    for row in rows:
        label = row.label_raw.strip()
        if not label:
            continue

        # Parse values
        valori_raw = row.values_by_year
        if not valori_raw or all(not v for v in valori_raw.values()):
            if row.row_type in ("sezione", "header"):
                continue
            continue

        valori: dict[str, int | None] = {}
        for anno in anni:
            val_raw = valori_raw.get(anno, "")
            valori[anno] = normalizza_numero(str(val_raw)) if val_raw else 0

        # ID generation with dedup
        base_id = row.row_id or genera_id(label)
        voce_id = base_id
        if voce_id in ids_visti and row.parent_label:
            voce_id = genera_id(row.parent_label) + "_" + base_id
        if voce_id in ids_visti:
            n = 2
            while f"{voce_id}_{n}" in ids_visti:
                n += 1
            voce_id = f"{voce_id}_{n}"
        ids_visti.add(voce_id)

        # Map row_type → livello
        livello_map = {"total": 1, "subtotal": 2, "detail": 3,
                       "di_cui": 3, "sezione": 1, "header": 1}
        livello = livello_map.get(row.row_type, 3)

        # Flags
        flags: list[str] = []
        anni_vals = [v for v in valori.values() if v is not None and v != 0]
        if len(anni_vals) >= 2:
            vals = list(valori.values())
            if vals[0] is not None and vals[1] is not None and vals[1] != 0:
                var = variazione_yoy(vals[0], vals[1])
                if var is not None and abs(var) > 0.3:
                    flags.append("variazione_significativa_yoy")
        if any(v is None for v in valori.values()):
            flags.append("dato_mancante")

        # Attach hint info as flag
        row_hints = hints_map.get(voce_id, [])
        if row_hints:
            flags.append("ha_hint_semantico")

        voce = crea_voce(
            id=voce_id,
            label=label,
            livello=livello,
            aggregato="",
            valore=valori,
            fonte_riga_bilancio=", ".join(row.note_refs) if row.note_refs else "",
            non_standard=False,
            flags=flags,
            note=row.parent_label or "",
        )
        # Extra metadata
        voce["extraction_method"] = row.extraction_method
        voce["source_page"] = row.source_page
        voce["section"] = row.section
        if row_hints:
            voce["classification_hints"] = [
                {"target": h.suggested_classification, "confidence": h.confidence,
                 "rationale": h.rationale_type}
                for h in row_hints
            ]

        if row.row_type == "di_cui":
            di_cui_voci.append(voce)
        else:
            voci.append(voce)

    return voci, di_cui_voci


def normalizza_estrazione_bundle(bundle: ExtractionBundle) -> dict:
    """Convert an ExtractionBundle into the normalised schema.

    This is the evidence-aware version of normalizza_estrazione().
    It uses DocumentProfile for metadata instead of hardcoding,
    preserves di_cui rows, and attaches classification hints.

    Args:
        bundle: ExtractionBundle with extracted_rows, classification_hints,
                and document_profile populated.

    Returns:
        Schema normalizzato compatible with the rest of the pipeline,
        plus extra keys: di_cui_sp, di_cui_ce, extraction_metadata.
    """
    profile = bundle.document_profile
    anni = profile.years_present
    rows = bundle.extracted_rows
    hints = bundle.classification_hints

    # Split rows by SP vs CE
    sp_rows = [r for r in rows if r.section in ("sp_attivo", "sp_passivo")]
    ce_rows = [r for r in rows if r.section == "ce"]

    voci_sp, di_cui_sp = _converti_extracted_rows(sp_rows, anni, hints)
    voci_ce, di_cui_ce = _converti_extracted_rows(ce_rows, anni, hints)

    # Find totals
    totale_attivo: dict[str, int | None] = {}
    totale_passivo: dict[str, int | None] = {}
    utile: dict[str, int | None] = {}

    for v in voci_sp:
        label_lower = v["label"].lower()
        if "totale attivo" in label_lower or "totale attivit" in label_lower:
            totale_attivo = v["valore"]
        if "totale passivo" in label_lower or "totale patrimonio netto e passivit" in label_lower:
            totale_passivo = v["valore"]

    for v in voci_ce:
        vid = v["id"].lower()
        label_lower = v["label"].lower()
        if "consolidat" in vid and ("utile" in vid or "perdita" in vid):
            utile = v["valore"]
            break
        if "risultato_netto_d_esercizio" in vid and "funzionamento" not in vid and "complessivo" not in vid:
            utile = v["valore"]
            break
        if ("utile" in label_lower and "esercizio" in label_lower
                and "terzi" not in label_lower and "complessivo" not in label_lower
                and "funzionamento" not in label_lower):
            utile = v["valore"]

    if not utile:
        for v in voci_sp:
            label_lower = v["label"].lower()
            if "utile" in label_lower and "perdita" in label_lower and "terzi" not in label_lower:
                utile = v["valore"]

    # Infer tipo_bilancio from profile
    tipo = profile.format_type if profile.format_type != "unknown" else "ordinario"

    # Determine scope label
    scope = profile.scope if profile.scope != "unknown" else ""

    schema = {
        "azienda": profile.company_name,
        "anni_estratti": [int(a) for a in anni],
        "tipo_bilancio": tipo,
        "sp": voci_sp,
        "ce": voci_ce,
        "di_cui_sp": di_cui_sp,
        "di_cui_ce": di_cui_ce,
        "metadata": {
            "pagine_sp": sorted(profile.page_map.get("sp", [])),
            "pagine_ce": sorted(profile.page_map.get("ce", [])),
            "totale_attivo_dichiarato": totale_attivo,
            "totale_passivo_dichiarato": totale_passivo,
            "utile_dichiarato": utile,
            "formato": profile.accounting_standard,
            "scope": scope,
        },
        "extraction_metadata": {
            "n_rows_sp": len(voci_sp),
            "n_rows_ce": len(voci_ce),
            "n_di_cui_sp": len(di_cui_sp),
            "n_di_cui_ce": len(di_cui_ce),
            "n_hints": len(hints),
            "n_evidence": len(bundle.semantic_evidence),
            "n_ambiguities": len(bundle.unresolved_ambiguities),
        },
    }

    return schema


if __name__ == "__main__":
    # Test: carica output estrattore PDF e normalizza
    est_path = Path("data/output/estrazione_pdf_result.json")
    if not est_path.exists():
        print("Esegui prima: python -m agents.estrattore_pdf")
        exit(1)

    estrazione = json.loads(est_path.read_text(encoding="utf-8"))
    schema = normalizza_estrazione(estrazione)

    print(f"Azienda: {schema['azienda']}")
    print(f"Voci SP: {len(schema['sp'])}, Voci CE: {len(schema['ce'])}")

    ta = schema["metadata"]["totale_attivo_dichiarato"]
    tp = schema["metadata"]["totale_passivo_dichiarato"]
    u = schema["metadata"]["utile_dichiarato"]
    for anno in schema["anni_estratti"]:
        a = str(anno)
        print(f"\n  {anno}:")
        print(f"    Totale Attivo:  {ta.get(a, 'N/D'):>15,}" if isinstance(ta.get(a), int) else f"    Totale Attivo:  N/D")
        print(f"    Totale Passivo: {tp.get(a, 'N/D'):>15,}" if isinstance(tp.get(a), int) else f"    Totale Passivo: N/D")
        print(f"    Utile:          {u.get(a, 'N/D'):>15,}" if isinstance(u.get(a), int) else f"    Utile:          N/D")

    out = Path("data/output/schema_normalizzato_llm.json")
    out.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSalvato in: {out}")
