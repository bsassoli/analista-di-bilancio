"""Quick eval script: runs pipeline on a single PDF and evaluates quality."""

import json
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(override=True)

from main import analizza_bilancio
from tools.valutatore_qualita import valuta_qualita, stampa_valutazione


def main():
    pdf = sys.argv[1] if len(sys.argv) > 1 else "data/input/enervit/2024.pdf"
    azienda = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"=== PIPELINE su {pdf} ===\n")
    result = analizza_bilancio(pdf, azienda)

    if result.get("errore") or "pipeline" not in result:
        print(f"Pipeline fallita: {result.get('errore', 'severity critical')}")
        print("Retrying is recommended (LLM mapping is non-deterministic).")
        sys.exit(1)

    pipeline_result = result["pipeline"]
    analisi = result["analisi"]

    # Save intermediates for debugging
    azienda_nome = result.get("azienda", azienda or "azienda")
    slug = azienda_nome.lower().replace(" ", "_").replace(".", "").replace(",", "")
    out = Path("data/output") / slug
    out.mkdir(parents=True, exist_ok=True)
    (out / "eval_pipeline.json").write_text(
        json.dumps(pipeline_result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    (out / "eval_analisi.json").write_text(
        json.dumps(analisi, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    print("\n=== VALUTAZIONE QUALITÀ ===\n")
    val = valuta_qualita(pipeline_result, analisi)

    (out / "eval_valutazione.json").write_text(
        json.dumps(val, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    stampa_valutazione(val)
    print(f"\nFile salvati in {out}/eval_*.json")


if __name__ == "__main__":
    main()
