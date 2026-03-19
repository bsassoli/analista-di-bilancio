"""Runner principale — pipeline completa PDF → Excel + Word.

Uso:
    python main.py data/input/bilancio.pdf "Nome Azienda"
    python main.py data/input/bilancio.pdf  # usa nome dal PDF
    python main.py --multi pdf1.pdf pdf2.pdf -- "Nome Azienda"
"""

import json
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(override=True)

from agents.estrattore_pdf import estrai_pdf
from agents.estrattore_numerico import normalizza_estrazione
from agents.estrattore_qualitativo import estrai_qualitativo
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
    print("[1/6] Estrazione dal PDF...")
    azienda_nome = azienda or "azienda"

    estrazione_pdf = estrai_pdf(pdf_path)
    if azienda:
        estrazione_pdf["azienda"] = azienda
    azienda_nome = estrazione_pdf.get("azienda", azienda_nome)

    if "error" in estrazione_pdf:
        print(f"      ERRORE: {estrazione_pdf['error']}")
        return {"errore": "estrazione_fallita", "dettaglio": estrazione_pdf}

    # --- Fase 2: Normalizzazione numerica ---
    print("[2/6] Normalizzazione numerica...")
    schema = normalizza_estrazione(estrazione_pdf)
    schema["azienda"] = azienda_nome

    print(f"      Azienda: {azienda_nome}")
    print(f"      Formato: {schema.get('metadata', {}).get('formato', '?')}")
    print(f"      Voci SP: {len(schema.get('sp', []))}, Voci CE: {len(schema.get('ce', []))}")
    print()

    # --- Fase 3: Estrazione qualitativa (LLM) ---
    print("[3/6] Estrazione qualitativa (nota integrativa)...")
    try:
        qualitativo = estrai_qualitativo(pdf_path, schema)
        if qualitativo.get("flags"):
            schema["flags_globali"] = qualitativo["flags"]
        if qualitativo.get("annotazioni_voci"):
            schema["annotazioni_voci"] = qualitativo["annotazioni_voci"]
        n_flags = len(qualitativo.get("flags", []))
        n_ann = len(qualitativo.get("annotazioni_voci", []))
        print(f"      Flags: {n_flags}, Annotazioni: {n_ann}")
    except Exception as e:
        print(f"      [WARN] Estrazione qualitativa fallita: {e}")
        qualitativo = {}
    print()

    # --- Fase 4: Checker + Riclassifica ---
    print("[4/6] Checker e riclassifica...")
    pipeline_result = esegui_pipeline(schema)

    severity = pipeline_result.get("severity_finale", "?")
    print(f"      Severity finale: {severity}")

    if severity == "critical" or pipeline_result.get("riclassifica") is None:
        print("      STOP — severity critica, analisi interrotta")
        elapsed = time.time() - t0
        print(f"\n  Tempo: {elapsed:.1f}s")
        return pipeline_result
    print()

    # --- Fase 5: Analisi ---
    print("[5/6] Calcolo indici e analisi...")
    analisi = esegui_analisi(pipeline_result)

    n_alert = len(analisi.get("alert", []))
    print(f"      Alert: {n_alert}")
    print()

    # --- Fase 6: Produzione output ---
    print("[6/6] Generazione Excel e Word...")
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


def analizza_bilancio_multi(pdf_paths: list[str], azienda: str) -> dict:
    """Processa N PDF della stessa azienda e produce analisi multi-anno."""
    from agents.orchestratore_multi import analizza_bilancio_multi as _multi
    return _multi(pdf_paths, azienda)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python main.py <pdf_path> [azienda]")
        print("     python main.py --multi <pdf1> <pdf2> ... -- <azienda>")
        sys.exit(1)

    if sys.argv[1] == "--multi":
        if "--" in sys.argv:
            sep_idx = sys.argv.index("--")
            pdfs = sys.argv[2:sep_idx]
            nome = sys.argv[sep_idx + 1] if sep_idx + 1 < len(sys.argv) else None
        else:
            pdfs = sys.argv[2:]
            nome = None
        if not pdfs:
            print("Errore: specificare almeno un PDF.")
            sys.exit(1)
        result = analizza_bilancio_multi(pdfs, nome)
    else:
        pdf = sys.argv[1]
        nome = sys.argv[2] if len(sys.argv) > 2 else None
        result = analizza_bilancio(pdf, nome)
