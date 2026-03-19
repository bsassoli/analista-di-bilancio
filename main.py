"""Runner principale — pipeline completa PDF → Excel + Word.

Uso:
    python main.py data/input/bilancio.pdf "Nome Azienda"
    python main.py data/input/bilancio.pdf  # usa nome dal PDF
"""

import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(override=True)

from agents.estrattore_pdf import estrai_pdf
from agents.estrattore_numerico import normalizza_estrazione
from agents.pipeline import esegui_pipeline, esegui_checker
from agents.analista import esegui_analisi
from agents.produttore import esegui_produzione


def analizza_bilancio(pdf_path: str, azienda: str | None = None) -> dict:
    """Esegue la pipeline completa di analisi bilancio.

    Args:
        pdf_path: Path al file PDF del bilancio.
        azienda: Nome azienda (opzionale, estratto dal PDF se omesso).

    Returns:
        Dict con tutti i risultati e path dei file generati.
    """
    t0 = time.time()
    print("=" * 70)
    print("  ANALISTA DI BILANCIO — Pipeline completa")
    print("=" * 70)
    print()

    # --- Fase 1: Estrazione PDF (LLM) ---
    print("[1/5] Estrazione dal PDF...")
    azienda_nome = azienda or "azienda"

    estrazione_pdf = estrai_pdf(pdf_path)
    if azienda:
        estrazione_pdf["azienda"] = azienda
    azienda_nome = estrazione_pdf.get("azienda", azienda_nome)

    if "error" in estrazione_pdf:
        print(f"      ERRORE: {estrazione_pdf['error']}")
        return {"errore": "estrazione_fallita", "dettaglio": estrazione_pdf}

    # --- Fase 2: Normalizzazione numerica ---
    print("[2/5] Normalizzazione numerica...")
    schema = normalizza_estrazione(estrazione_pdf)
    schema["azienda"] = azienda_nome

    print(f"      Azienda: {azienda_nome}")
    print(f"      Formato: {schema.get('metadata', {}).get('formato', '?')}")
    print(f"      Voci SP: {len(schema.get('sp', []))}, Voci CE: {len(schema.get('ce', []))}")
    print()

    # --- Fase 3: Checker + Riclassifica ---
    print("[3/5] Checker e riclassifica...")
    pipeline_result = esegui_pipeline(schema)

    severity = pipeline_result.get("severity_finale", "?")
    print(f"      Severity finale: {severity}")

    if severity == "critical" or pipeline_result.get("riclassifica") is None:
        print("      STOP — severity critica, analisi interrotta")
        elapsed = time.time() - t0
        print(f"\n  Tempo: {elapsed:.1f}s")
        return pipeline_result
    print()

    # --- Fase 4: Analisi ---
    print("[4/5] Calcolo indici e analisi...")
    analisi = esegui_analisi(pipeline_result)

    n_alert = len(analisi.get("alert", []))
    print(f"      Alert: {n_alert}")
    print()

    # --- Fase 5: Produzione output ---
    print("[5/5] Generazione Excel e Word...")
    output = esegui_produzione(pipeline_result, analisi)

    elapsed = time.time() - t0
    print()
    print("=" * 70)
    print("  PIPELINE COMPLETATA")
    print("=" * 70)
    print(f"  Azienda:  {azienda_nome}")
    print(f"  Severity: {severity}")
    print(f"  Excel:    {output.get('excel_path', output.get('excel', 'N/D'))}")
    print(f"  Word:     {output.get('word_path', output.get('word', 'N/D'))}")
    print(f"  Tempo:    {elapsed:.1f}s")
    print()

    return {
        "azienda": azienda_nome,
        "severity": severity,
        "pipeline": pipeline_result,
        "analisi": analisi,
        "output": output,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        # Default: Enervit
        pdf = "data/input/Relazione_finanziaria_al_bilancio_d_esercizio_al_31_dicembre_2024_e_al_Bilancio_consolidato_al_31_dicembre_2024.pdf"
        nome = "Enervit S.p.A."
    else:
        pdf = sys.argv[1]
        nome = sys.argv[2] if len(sys.argv) > 2 else None

    result = analizza_bilancio(pdf, nome)
