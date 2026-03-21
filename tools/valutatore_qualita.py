"""Valutatore qualità analisi — usa la rubric per assegnare un punteggio.

Invia l'output dell'analisi (narrative, indici, alert) a Claude con la rubric
come system prompt e ottiene un punteggio strutturato su 10 criteri.
"""

import json
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(override=True)

import anthropic


ROOT = Path(__file__).parent.parent


def _carica_rubric() -> str:
    """Carica la rubric di valutazione."""
    path = ROOT / "skills" / "skill_valutazione_qualita.md"
    return path.read_text(encoding="utf-8")


def _prepara_analisi_per_valutazione(
    pipeline_result: dict,
    analisi: dict,
    qualitativo: dict | None = None,
) -> str:
    """Prepara il testo dell'analisi da valutare."""
    parti = []

    azienda = analisi.get("azienda", "N/D")
    anni = analisi.get("anni", [])
    parti.append(f"AZIENDA: {azienda}")
    parti.append(f"ANNI ANALIZZATI: {anni}")
    parti.append("")

    # Riclassifica — numeri chiave
    parti.append("=" * 60)
    parti.append("DATI RICLASSIFICATI")
    parti.append("=" * 60)
    risultati = pipeline_result.get("riclassifica", {}).get("risultati_per_anno", {})
    for anno in sorted(risultati.keys()):
        res = risultati[anno]
        sp = res.get("sp_riclassificato", {})
        ce = res.get("ce_riclassificato", {})
        quad = sp.get("quadratura", {})
        parti.append(f"\n--- {anno} ---")
        parti.append(f"Totale attivo: {quad.get('totale_attivo', 0):,}")
        parti.append(f"PN: {sp.get('passivo', {}).get('patrimonio_netto', {}).get('totale', 0):,}")
        parti.append(f"PFN: {sp.get('passivo', {}).get('pfn', {}).get('totale', 0):,}")
        parti.append(f"CFN: {sp.get('attivo', {}).get('capitale_fisso_netto', {}).get('totale', 0):,}")
        parti.append(f"CCON: {sp.get('attivo', {}).get('ccon', {}).get('totale', 0):,}")
        parti.append(f"Ricavi: {ce.get('ricavi_netti', 0):,}")
        parti.append(f"EBITDA: {ce.get('ebitda', 0):,}")
        parti.append(f"EBIT: {ce.get('ebit', 0):,}")
        parti.append(f"Utile netto: {ce.get('utile_netto', 0):,}")
        # Dettaglio WC
        ccon_det = sp.get("attivo", {}).get("ccon", {}).get("dettaglio", {})
        parti.append(f"  Crediti comm.: {ccon_det.get('crediti_commerciali', 0):,}")
        parti.append(f"  Rimanenze: {ccon_det.get('rimanenze', 0):,}")
        parti.append(f"  Debiti op.: {ccon_det.get('debiti_operativi_sottratti', 0):,}")
        # Dettaglio PFN
        pfn_det = sp.get("passivo", {}).get("pfn", {}).get("dettaglio", {})
        parti.append(f"  Deb. fin. lungo: {pfn_det.get('debiti_finanziari_lungo', 0):,}")
        parti.append(f"  Deb. fin. breve: {pfn_det.get('debiti_finanziari_breve', 0):,}")
        parti.append(f"  Liquidità: {pfn_det.get('disponibilita_liquide_sottratte', 0):,}")
        # Deviazioni
        for dev in res.get("deviazioni", []):
            parti.append(f"  [DEV] {dev}")

    # Indici
    parti.append("\n" + "=" * 60)
    parti.append("INDICI")
    parti.append("=" * 60)
    for cat, indici_cat in analisi.get("indici", {}).items():
        parti.append(f"\n{cat.upper()}:")
        for nome, valori in indici_cat.items():
            vals = ", ".join(f"{a}: {v}" for a, v in sorted(valori.items()) if v is not None)
            parti.append(f"  {nome}: {vals}")

    # Trend
    parti.append("\n" + "=" * 60)
    parti.append("TREND SIGNIFICATIVI")
    parti.append("=" * 60)
    for t in analisi.get("trend", []):
        if t.get("significativo"):
            parti.append(f"  {t['indice']}: {t['direzione']} ({t.get('variazione_percentuale', 'n/d')})")

    # Alert
    parti.append("\n" + "=" * 60)
    parti.append("ALERT")
    parti.append("=" * 60)
    for a in analisi.get("alert", []):
        parti.append(f"  [{a['tipo']}] {a['indice']}: {a['messaggio']} (valore: {a['valore']}, soglia: {a['soglia']})")

    # Narrative
    parti.append("\n" + "=" * 60)
    parti.append("NARRATIVE")
    parti.append("=" * 60)
    for sezione, testo in analisi.get("narrative", {}).items():
        parti.append(f"\n[{sezione.upper()}]")
        parti.append(testo)

    # Qualitativo (se disponibile)
    if qualitativo:
        parti.append("\n" + "=" * 60)
        parti.append("DATI QUALITATIVI (dalla nota integrativa)")
        parti.append("=" * 60)
        for k in ("flags", "annotazioni_voci", "scadenze_debiti", "criteri_valutazione",
                   "dipendenti", "investimenti", "composizione_ricavi", "dividendi"):
            v = qualitativo.get(k)
            if v:
                parti.append(f"\n{k}: {json.dumps(v, ensure_ascii=False, indent=2)}")

    # Cross-anno (se disponibile)
    cross = pipeline_result.get("cross_anno", [])
    if cross:
        parti.append("\n" + "=" * 60)
        parti.append("ISSUES CROSS-ANNO")
        parti.append("=" * 60)
        for issue in cross:
            parti.append(f"  [{issue['severity']}] {issue['codice']}: {issue['dettaglio']}")

    return "\n".join(parti)


def valuta_qualita(
    pipeline_result: dict,
    analisi: dict,
    qualitativo: dict | None = None,
    model: str = "claude-sonnet-4-20250514",
) -> dict:
    """Valuta la qualità dell'analisi usando la rubric.

    Args:
        pipeline_result: Output della pipeline di riclassifica.
        analisi: Output dell'agente analista.
        qualitativo: Output dell'estrattore qualitativo (opzionale).
        model: Modello da usare per la valutazione.

    Returns:
        Dict con punteggi per criterio, totale, livello, aree di miglioramento.
    """
    client = anthropic.Anthropic()
    rubric = _carica_rubric()
    testo_analisi = _prepara_analisi_per_valutazione(pipeline_result, analisi, qualitativo)

    system = f"""Sei un revisore esperto di analisi finanziarie. Valuta la qualità dell'analisi
che ti viene presentata usando la rubric seguente. Sii rigoroso e specifico nelle motivazioni.

{rubric}

REGOLE:
1. Restituisci SOLO JSON valido, nessun testo prima o dopo.
2. Per ogni criterio, il punteggio DEVE essere tra 1 e 5.
3. Le motivazioni devono essere specifiche, citando parti dell'analisi.
4. La "risposta_domanda_chiave" deve essere la tua risposta alla domanda, non
   quella dell'analisi — cosa TU consideri la variabile chiave da monitorare.
"""

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system,
        messages=[{
            "role": "user",
            "content": f"Valuta questa analisi di bilancio:\n\n{testo_analisi}",
        }],
    )

    text = response.content[0].text.strip()

    # Parse JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Prova a estrarre JSON da markdown
        match = re.search(r"```(?:json)?\s*\n(.*?)\n\s*```", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        return {"error": "JSON non parsabile", "raw": text[:2000]}


def stampa_valutazione(val: dict) -> None:
    """Stampa la valutazione in formato leggibile."""
    if "error" in val:
        print(f"ERRORE: {val['error']}")
        if "raw" in val:
            print(val["raw"])
        return

    print("=" * 70)
    print("  VALUTAZIONE QUALITÀ ANALISI")
    print("=" * 70)
    print()

    punteggi = val.get("punteggi", {})
    totale = 0
    for nome, dati in punteggi.items():
        score = dati.get("score", 0)
        totale += score
        motiv = dati.get("motivazione", "")
        barra = "█" * score + "░" * (5 - score)
        print(f"  {barra} {score}/5  {nome}")
        print(f"         {motiv[:100]}")
        print()

    totale_dichiarato = val.get("totale", totale)
    livello = val.get("livello", "?")
    print(f"  {'=' * 50}")
    print(f"  TOTALE: {totale_dichiarato}/50 — {livello}")
    print(f"  {'=' * 50}")

    print(f"\n  DOMANDA CHIAVE: {val.get('domanda_chiave', '')}")
    print(f"  RISPOSTA: {val.get('risposta_domanda_chiave', '')}")

    print(f"\n  PUNTI DI FORZA:")
    for p in val.get("punti_forza", []):
        print(f"    + {p}")

    print(f"\n  AREE DI MIGLIORAMENTO:")
    for p in val.get("aree_miglioramento", []):
        print(f"    - {p}")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python -m tools.valutatore_qualita <pipeline_result.json> <analisi.json> [qualitativo.json]")
        sys.exit(1)

    pipeline_path = Path(sys.argv[1])
    analisi_path = Path(sys.argv[2])

    pipeline_result = json.loads(pipeline_path.read_text(encoding="utf-8"))
    analisi = json.loads(analisi_path.read_text(encoding="utf-8"))

    qualitativo = None
    if len(sys.argv) > 3:
        qual_path = Path(sys.argv[3])
        if qual_path.exists():
            qualitativo = json.loads(qual_path.read_text(encoding="utf-8"))

    print("Valutazione in corso...")
    val = valuta_qualita(pipeline_result, analisi, qualitativo)

    # Salva nella sottocartella azienda
    azienda = pipeline_result.get("azienda", "azienda")
    slug = azienda.lower().replace(" ", "_").replace(".", "").replace(",", "")
    out_path = Path("data/output") / slug / "valutazione_qualita.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(val, indent=2, ensure_ascii=False), encoding="utf-8")

    stampa_valutazione(val)
    print(f"\nSalvato in: {out_path}")
