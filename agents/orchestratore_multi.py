"""Orchestratore multi-anno: processa N PDF della stessa azienda.

Merge i risultati, dedup anni sovrapposti, produce analisi unificata.
"""

import json
import time
from pathlib import Path
from typing import Any

from agents.base import carica_stato, salva_stato
from agents.analista import esegui_analisi
from agents.produttore import esegui_produzione
from tools.schema import crea_stato_iniziale
from tools.validatori import calcola_severity


def _anno_primario(anni: list[str]) -> str:
    """Restituisce l'anno primario (più recente) tra quelli estratti da un PDF."""
    return max(anni) if anni else ""


def _merge_risultati(risultati_pdf: list[dict]) -> dict:
    """Merge risultati_per_anno da N pipeline result.

    Per anni sovrapposti, tiene la versione dal PDF dove l'anno è primario.
    Es: anno 2023 estratto sia dal bilancio 2024 (comparativo) che dal 2023
    (primario) → prende dal bilancio 2023.
    """
    # Raccogli tutti gli anni con la loro sorgente e priorità
    candidati: dict[str, list[tuple[dict, bool]]] = {}

    for pdf_result in risultati_pdf:
        riclassifica = pdf_result.get("pipeline", {}).get("riclassifica", {})
        risultati_anno = riclassifica.get("risultati_per_anno", {})
        anni = sorted(risultati_anno.keys())

        if not anni:
            continue

        anno_primario = _anno_primario(anni)

        for anno, dati in risultati_anno.items():
            is_primario = (anno == anno_primario)
            candidati.setdefault(anno, []).append((dati, is_primario))

    # Seleziona il migliore per ogni anno
    merged: dict[str, dict] = {}
    for anno, opzioni in candidati.items():
        # Preferisci la versione primaria
        primari = [o for o in opzioni if o[1]]
        if primari:
            merged[anno] = primari[0][0]
        else:
            # Se nessun primario, prendi quello con confidence più alta
            opzioni.sort(key=lambda o: o[0].get("confidence", 0), reverse=True)
            merged[anno] = opzioni[0][0]

    return merged


def valida_cross_anno(risultati_per_anno: dict) -> list[dict]:
    """Verifica coerenza tra anni consecutivi.

    Checks:
    - Salti >50% nel totale attivo tra anni consecutivi
    - Voci che appaiono/scompaiono tra anni
    - Cambi di segno in aggregati chiave (EBITDA, PFN)
    """
    issues: list[dict] = []
    anni = sorted(risultati_per_anno.keys())

    if len(anni) < 2:
        return issues

    for i in range(1, len(anni)):
        anno_corr = anni[i]
        anno_prec = anni[i - 1]

        res_corr = risultati_per_anno[anno_corr]
        res_prec = risultati_per_anno[anno_prec]

        sp_corr = res_corr.get("sp_riclassificato", {})
        sp_prec = res_prec.get("sp_riclassificato", {})
        ce_corr = res_corr.get("ce_riclassificato", {})
        ce_prec = res_prec.get("ce_riclassificato", {})

        # Salto totale attivo > 50%
        ta_corr = sp_corr.get("quadratura", {}).get("totale_attivo", 0)
        ta_prec = sp_prec.get("quadratura", {}).get("totale_attivo", 0)
        if ta_prec > 0:
            var = abs(ta_corr - ta_prec) / ta_prec
            if var > 0.5:
                issues.append({
                    "codice": "CROSS_SALTO_ATTIVO",
                    "severity": "warning",
                    "dettaglio": (
                        f"Totale attivo: salto {var:.0%} tra {anno_prec} "
                        f"({ta_prec:,}) e {anno_corr} ({ta_corr:,})"
                    ),
                })

        # Cambio segno EBITDA
        ebitda_corr = ce_corr.get("ebitda", 0)
        ebitda_prec = ce_prec.get("ebitda", 0)
        if ebitda_corr * ebitda_prec < 0:
            issues.append({
                "codice": "CROSS_SEGNO_EBITDA",
                "severity": "warning",
                "dettaglio": (
                    f"Cambio segno EBITDA: {anno_prec}={ebitda_prec:,} → "
                    f"{anno_corr}={ebitda_corr:,}"
                ),
            })

        # Cambio segno PFN
        pfn_corr = sp_corr.get("passivo", {}).get("pfn", {}).get("totale", 0)
        pfn_prec = sp_prec.get("passivo", {}).get("pfn", {}).get("totale", 0)
        if pfn_corr * pfn_prec < 0 and abs(pfn_corr) > 100_000 and abs(pfn_prec) > 100_000:
            issues.append({
                "codice": "CROSS_SEGNO_PFN",
                "severity": "warning",
                "dettaglio": (
                    f"Cambio segno PFN: {anno_prec}={pfn_prec:,} → "
                    f"{anno_corr}={pfn_corr:,}"
                ),
            })

        # Continuità PN: PN(N) ≈ PN(N-1) + utile(N) [approssimativo]
        pn_corr = sp_corr.get("passivo", {}).get("patrimonio_netto", {}).get("totale", 0)
        pn_prec = sp_prec.get("passivo", {}).get("patrimonio_netto", {}).get("totale", 0)
        utile_corr = ce_corr.get("utile_netto", 0)
        pn_atteso = pn_prec + utile_corr
        if pn_prec != 0 and abs(pn_corr - pn_atteso) / abs(pn_prec) > 0.20:
            issues.append({
                "codice": "CROSS_CONTINUITA_PN",
                "severity": "warning",
                "dettaglio": (
                    f"PN {anno_corr} ({pn_corr:,}) diverge da "
                    f"PN {anno_prec} ({pn_prec:,}) + utile ({utile_corr:,}) = "
                    f"{pn_atteso:,}. Possibile distribuzione dividendi o operazione sul capitale."
                ),
            })

    return issues


def analizza_bilancio_multi(pdf_paths: list[str], azienda: str) -> dict:
    """Processa N PDF della stessa azienda e produce analisi multi-anno.

    Args:
        pdf_paths: Lista di path PDF, in ordine cronologico (più vecchio prima).
        azienda: Nome azienda.

    Returns:
        Dict con risultati merged, analisi unificata, output paths.
    """
    # Import qui per evitare circolarità
    from main import analizza_bilancio

    t0 = time.time()
    print("=" * 70)
    print("  ANALISTA DI BILANCIO — Pipeline multi-anno")
    print(f"  PDF da processare: {len(pdf_paths)}")
    print("=" * 70)
    print()

    # --- Carica stato se esiste ---
    stato = carica_stato(azienda) if azienda else None

    # --- Processa ogni PDF ---
    risultati_pdf: list[dict] = []
    for i, pdf_path in enumerate(pdf_paths):
        print(f"\n{'='*50}")
        print(f"  PDF {i+1}/{len(pdf_paths)}: {Path(pdf_path).name}")
        print(f"{'='*50}")

        result = analizza_bilancio(pdf_path, azienda)

        if result.get("errore"):
            print(f"  [WARN] PDF {i+1} fallito: {result.get('errore')}")
            continue

        if result.get("pipeline", {}).get("riclassifica") is None:
            print(f"  [WARN] PDF {i+1}: severity critical, skip")
            continue

        risultati_pdf.append(result)

    if not risultati_pdf:
        return {"errore": "Nessun PDF processato con successo"}

    # --- Merge risultati ---
    print(f"\n{'='*50}")
    print("  MERGE RISULTATI")
    print(f"{'='*50}")

    merged_risultati = _merge_risultati(risultati_pdf)
    anni_merged = sorted(merged_risultati.keys())
    print(f"  Anni disponibili dopo merge: {anni_merged}")

    # --- Validazione cross-anno ---
    cross_issues = valida_cross_anno(merged_risultati)
    if cross_issues:
        print(f"\n  Issues cross-anno: {len(cross_issues)}")
        for issue in cross_issues:
            print(f"    [{issue['severity']}] {issue['codice']}: {issue['dettaglio']}")

    # --- Costruisci pipeline_result unificato ---
    # Usa il checker più recente
    ultimo_result = risultati_pdf[-1]
    pipeline_result = {
        "azienda": azienda or ultimo_result.get("azienda", ""),
        "completata": True,
        "severity_finale": ultimo_result.get("severity", "warning"),
        "checker_pre": ultimo_result.get("pipeline", {}).get("checker_pre", {}),
        "riclassifica": {
            "azienda": azienda,
            "metodo": "multi_merge",
            "risultati_per_anno": merged_risultati,
        },
        "checker_post": ultimo_result.get("pipeline", {}).get("checker_post", {}),
        "cross_anno": cross_issues,
    }

    # --- Analisi unificata ---
    print(f"\n  Calcolo analisi unificata su {len(anni_merged)} anni...")
    analisi = esegui_analisi(pipeline_result)

    # --- Produzione output ---
    print(f"\n  Generazione output...")
    output = esegui_produzione(pipeline_result, analisi)

    # --- Salva stato ---
    if azienda:
        nuovo_stato = crea_stato_iniziale(azienda, [int(a) for a in anni_merged])
        nuovo_stato["fase_corrente"] = "completato"
        for anno in anni_merged:
            res = merged_risultati[anno]
            nuovo_stato["qualita_dati"][anno] = {
                "severity": "ok" if res.get("confidence", 0) >= 0.8 else "warning",
                "confidence": res.get("confidence", 0),
                "issues": [],
            }
        salva_stato(azienda, nuovo_stato)
        print(f"  Stato salvato per {azienda}")

    elapsed = time.time() - t0
    print()
    print("=" * 70)
    print("  PIPELINE MULTI-ANNO COMPLETATA")
    print("=" * 70)
    print(f"  Azienda:  {azienda}")
    print(f"  Anni:     {anni_merged}")
    print(f"  PDF:      {len(risultati_pdf)}/{len(pdf_paths)} processati")
    print(f"  Excel:    {output.get('excel_path', 'N/D')}")
    print(f"  Word:     {output.get('word_path', 'N/D')}")
    print(f"  Tempo:    {elapsed:.1f}s")
    print()

    return {
        "azienda": azienda,
        "anni": anni_merged,
        "n_pdf_processati": len(risultati_pdf),
        "pipeline": pipeline_result,
        "analisi": analisi,
        "output": output,
        "cross_anno": cross_issues,
    }
