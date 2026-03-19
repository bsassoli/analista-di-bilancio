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
    # Sezioni specifiche spesso su pagine senza keyword "nota integrativa"
    "numero medio",
    "totale dipendenti",
    "organico medio",
    "scadenza dei debiti",
    "debiti per scadenza",
    "quota oltre 12 mesi",
    "rapporti con parti correlate",
    "operazioni con parti correlate",
    "compensi amministratori",
    "fatti di rilievo dopo la chiusura",
    "proposta di destinazione",
    "proposta di distribuzione",
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

    Strategia a 2 livelli:
    1. Trova la prima pagina con "nota integrativa" o "criteri di valutazione"
    2. Da lì in poi, include tutte le pagine fino alla fine del documento
       (la NI è tipicamente un blocco continuo fino alla fine)
    3. Escludi pagine che sono chiaramente prospetti (alta densità numerica tabellare)
    """
    # Fase 1: trova inizio NI
    inizio_ni = None
    for item in testi:
        testo_lower = item["testo"].lower()
        pagina_0based = item["pagina"] - 1
        if any(kw in testo_lower for kw in [
            "nota integrativa", "criteri di valutazione",
            "principi contabili applicati",
        ]):
            densita = _densita_numerica(item["testo"])
            if densita < 0.3:
                inizio_ni = pagina_0based
                break

    if inizio_ni is None:
        # Fallback: keyword-based puro
        pagine_ni = []
        for item in testi:
            testo_lower = item["testo"].lower()
            pagina_0based = item["pagina"] - 1
            keyword_hits = sum(1 for kw in _KEYWORDS_NI if kw in testo_lower)
            if keyword_hits >= 1:
                densita = _densita_numerica(item["testo"])
                if densita < 0.3 or keyword_hits >= 2:
                    pagine_ni.append(pagina_0based)
        return pagine_ni

    # Fase 2: da inizio NI, includi tutte le pagine non-prospetto
    pagine_ni = []
    for item in testi:
        pagina_0based = item["pagina"] - 1
        if pagina_0based < inizio_ni:
            continue

        # Escludi pagine con alta densità numerica tabellare (sono prospetti, non NI)
        densita = _densita_numerica(item["testo"])
        lines = item["testo"].strip().split("\n")
        righe_prospetto = 0
        for line in lines:
            import re as _re
            if _re.search(r'[\w\s]{10,}\s+[\d.()\-]+\s+[\d.()\-]+', line):
                righe_prospetto += 1
        densita_righe = righe_prospetto / max(len(lines), 1)

        # Se è chiaramente un prospetto contabile, skip
        if densita > 0.5 and densita_righe > 0.4:
            continue

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

_SYSTEM_PROMPT = """Sei un analista finanziario esperto di bilanci italiani (OIC e IFRS). Analizza il testo della nota integrativa e della relazione sulla gestione e produci un output JSON strutturato e completo.

OBIETTIVO: estrarre TUTTE le informazioni utili per riclassificare il bilancio e analizzare l'azienda.

## COSA CERCARE (in ordine di priorità)

### PRIORITÀ 1 — Impattano la riclassifica
- **Scadenze debiti**: CERCA SEMPRE la tabella "debiti per scadenza" o "analisi debiti per scadenza". Estrai i totali entro/oltre esercizio e oltre 5 anni, dettagliati per tipo (banche, fornitori, tributari, ecc.)
- **Split voci ambigue**: "altri debiti" o "altri crediti" che includono componenti finanziarie (es. finanziamento soci). Estrai importo e natura
- **Natura fondi rischi**: per ciascun fondo, indica se è operativo (garanzie prodotti, cause legali) o finanziario (derivati, coperture)
- **Leasing**: importi IFRS 16 (diritti d'uso, passività per leasing) o leasing operativo pre-IFRS16. Estrai il valore lordo e netto
- **Rapporti infragruppo**: crediti/debiti verso controllate, collegate, controllanti — distingui commerciali da finanziari con importi

### PRIORITÀ 2 — Flags strutturali
- **Rivalutazioni**: ex D.L. 104/2020 o precedenti, con importo e voci impattate
- **Operazioni straordinarie**: acquisizioni (PPA, avviamento), fusioni, scissioni, conferimenti — con importo e data
- **Cambi di perimetro**: nuove società consolidate, variazioni % partecipazione
- **Svalutazioni/impairment**: importo, voce, motivazione

### PRIORITÀ 3 — Contesto per l'analista
- **Criteri di valutazione**: per OGNI voce principale (rimanenze, crediti, immobilizzazioni, TFR, ricavi). Indica il metodo specifico e i parametri chiave (es. aliquote ammortamento, tassi attualizzazione)
- **Composizione ricavi**: per canale, area geografica, linea di prodotto. Usa percentuali e importi quando disponibili
- **Dipendenti**: numero medio annuo e dettaglio per categoria (dirigenti, quadri, impiegati, operai). CERCA "organico", "personale", "numero medio dipendenti"
- **Investimenti**: capex dell'esercizio, principali investimenti per tipo
- **Rischi e contenziosi**: cause in corso con stima passività, rischi fiscali
- **Dividendi**: distribuzione deliberata o proposta, importo per azione
- **Fatti dopo chiusura**: eventi post-closing rilevanti
- **Covenant bancari**: se menzionati, estrai i parametri e se sono rispettati

## REGOLE
1. Restituisci SOLO JSON valido, nessun testo prima o dopo
2. Ogni elemento DEVE avere fonte_pagina (numero pagina del PDF)
3. NON inventare: se un dato non è nel testo, omettilo. "dipendenti": {} è meglio di dati inventati
4. Usa importi in euro INTERI (no migliaia abbreviate: scrivi 1500000, non "1.500k")
5. Per le scadenze debiti, se trovi la tabella, riportala COMPLETA

## FORMATO OUTPUT
{
  "flags": [
    {"tipo": "flags_strutturali|flags_contabili|flags_operazioni", "codice": "RIVALUTAZIONE|ACQUISIZIONE|IFRS16|IMPAIRMENT|CAMBIO_PERIMETRO|CONTENZIOSO|...", "dettaglio": "descrizione precisa con importi", "impatto_voci": ["voce_id_1"], "importo": 0, "fonte_pagina": 0}
  ],
  "annotazioni_voci": [
    {"voce_id": "id_normalizzato", "nota": "descrizione con importi", "suggerimento_riclassifica": "azione specifica per il riclassificatore", "importo": 0, "fonte_pagina": 0}
  ],
  "scadenze_debiti": {
    "entro_esercizio": {"totale": 0, "verso_banche": 0, "verso_fornitori": 0, "tributari": 0, "previdenziali": 0, "altri": 0},
    "oltre_esercizio_entro_5": {"totale": 0, "verso_banche": 0, "altri": 0},
    "oltre_5_anni": {"totale": 0},
    "fonte_pagina": 0
  },
  "criteri_valutazione": {
    "rimanenze": "metodo e dettagli",
    "crediti": "metodo e dettagli",
    "immobilizzazioni_materiali": "metodo, aliquote principali",
    "immobilizzazioni_immateriali": "metodo",
    "avviamento": "metodo impairment",
    "tfr": "metodo, tasso attualizzazione, tasso inflazione",
    "ricavi": "criterio di riconoscimento",
    "fonte_pagina": 0
  },
  "eventi_rilevanti": [
    {"evento": "descrizione", "data": "YYYY-MM o YYYY", "impatto": "effetto sulle voci", "importo": 0, "fonte_pagina": 0}
  ],
  "composizione_ricavi": {
    "per_area": {"italia": 0, "estero": 0, "dettaglio_estero": {}},
    "per_canale": {},
    "per_prodotto": {},
    "totale": 0,
    "fonte_pagina": 0
  },
  "dipendenti": {
    "media_annua": 0,
    "fine_esercizio": 0,
    "dettaglio": {"dirigenti": 0, "quadri": 0, "impiegati": 0, "operai": 0},
    "costo_totale": 0,
    "fonte_pagina": 0
  },
  "investimenti": {
    "capex_totale": 0,
    "dettaglio": {},
    "fonte_pagina": 0
  },
  "dividendi": {
    "proposta": "descrizione",
    "importo_totale": 0,
    "per_azione": 0,
    "fonte_pagina": 0
  },
  "rapporti_infragruppo": {
    "crediti_commerciali": 0,
    "crediti_finanziari": 0,
    "debiti_commerciali": 0,
    "debiti_finanziari": 0,
    "ricavi": 0,
    "costi": 0,
    "fonte_pagina": 0
  }
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

    # Leggi tutte le pagine NI (max 30) + relazione (max 10)
    # Le info su scadenze debiti, dipendenti, investimenti sono spesso nelle ultime pagine
    pagine_da_leggere = sorted(set(ni_pagine[:30] + rel_pagine[:10]))

    if not pagine_da_leggere:
        return {"flags": [], "annotazioni_voci": []}

    testi = estrai_testo_pdf(pdf_path, pagine_da_leggere)

    parti = []
    for item in testi:
        parti.append(f"\n--- PAGINA {item['pagina']} ---")
        parti.append(item["testo"])
    testo_completo = "\n".join(parti)

    # Limita lunghezza per non eccedere context
    if len(testo_completo) > 80_000:
        testo_completo = testo_completo[:80_000] + "\n\n[...TESTO TRONCATO...]"

    # Contesto voci dallo schema per guidare l'estrazione
    voci_interessanti = []
    for sez in ("sp", "ce"):
        for v in schema.get(sez, []):
            vid = v.get("id", "")
            label = v.get("label", "")
            valori = v.get("valore", {})
            # Voci ambigue o rilevanti per la riclassifica
            keywords_rilevanti = (
                "altri_debiti", "altri_crediti", "fondi_rischi", "fondi_per_rischi",
                "debiti_verso_banche", "finanziamenti", "leasing", "diritti_uso",
                "partecipazioni", "avviamento", "tfr", "benefici",
            )
            if any(kw in vid for kw in keywords_rilevanti):
                vals = ", ".join(f"{a}: {v:,}€" for a, v in valori.items() if isinstance(v, int))
                voci_interessanti.append(f"- {label} (id: {vid}) → {vals}")

    contesto_voci = ""
    if voci_interessanti:
        contesto_voci = (
            "\n\nVOCI DA APPROFONDIRE (cercane il dettaglio nella NI):\n"
            + "\n".join(voci_interessanti[:20])
        )

    formato = schema.get("metadata", {}).get("formato", "")
    user_msg = f"""Analizza questa nota integrativa e relazione sulla gestione.
Azienda: {schema.get('azienda', 'N/D')}
Anni: {schema.get('anni_estratti', [])}
Formato bilancio: {formato}

ISTRUZIONI SPECIFICHE:
1. Cerca SEMPRE la tabella scadenze debiti (entro/oltre esercizio). Di solito è nella sezione "Debiti" o "Passività correnti/non correnti".
2. Cerca il numero medio dipendenti e il dettaglio per categoria. Di solito è nella sezione "Personale" o "Costi del personale".
3. Per i criteri di valutazione, estrai parametri numerici specifici (aliquote, tassi, vite utili).
4. Per le operazioni straordinarie, includi date e importi precisi.
5. Per i rapporti infragruppo, distingui crediti/debiti commerciali da finanziari.
{contesto_voci}

TESTO ESTRATTO DAL PDF:
{testo_completo}"""

    response = client.messages.create(
        model=model,
        max_tokens=16384,
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
        "scadenze_debiti": risultato.get("scadenze_debiti", {}),
        "criteri_valutazione": risultato.get("criteri_valutazione", {}),
        "eventi_rilevanti": risultato.get("eventi_rilevanti", []),
        "composizione_ricavi": risultato.get("composizione_ricavi", {}),
        "dipendenti": risultato.get("dipendenti", {}),
        "investimenti": risultato.get("investimenti", {}),
        "dividendi": risultato.get("dividendi", {}),
        "rapporti_infragruppo": risultato.get("rapporti_infragruppo", {}),
    }

    n_flags = len(output["flags"])
    n_ann = len(output["annotazioni_voci"])
    has_scadenze = bool(output["scadenze_debiti"])
    has_dipendenti = bool(output["dipendenti"].get("media_annua") or output["dipendenti"].get("fine_esercizio"))
    print(f"[qualitativo]   Completato: {n_flags} flags, {n_ann} annotazioni, "
          f"scadenze={'sì' if has_scadenze else 'no'}, dipendenti={'sì' if has_dipendenti else 'no'}")

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
