"""Agente estrattore PDF: estrae dati strutturati da un PDF di bilancio italiano.

Approccio a due fasi:
  Fase 1 (deterministica): usa pdfplumber per estrarre testo/tabelle grezzi
           e identifica le pagine esatte dei prospetti (SP, CE).
  Fase 2 (LLM): invia SOLO le pagine dei prospetti a Claude per
           pulizia e strutturazione.
"""

import json
import re
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
load_dotenv(override=True)

from agents.base import (
    crea_client,
    definisci_tools_per_agente,
    esegui_tool,
)
from tools.pdf_parser import (
    estrai_tabelle_pdf,
    estrai_testo_pdf,
    identifica_sezione,
)


# ---------------------------------------------------------------------------
# Fase 1 — Ricognizione intelligente del documento
# ---------------------------------------------------------------------------

def _conta_pagine(pdf_path: str) -> int:
    import pdfplumber
    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)


def _pagina_e_prospetto(testo: str) -> dict:
    """Analizza una pagina e determina se contiene un prospetto contabile.

    Un prospetto si distingue dal testo discorsivo per la presenza di:
    - Intestazioni specifiche ("ATTIVITA'", "PASSIVO", etc.)
    - Colonne di anni nelle intestazioni
    - Alta densità di numeri formattati (1.234.567)
    """
    if not testo:
        return {"tipo": None, "score": 0}

    testo_lower = testo.lower()
    lines = testo.strip().split("\n")

    score = 0
    tipo = None

    # Pattern che indicano un PROSPETTO (non una menzione testuale)
    # SP Attivo
    sp_attivo_patterns = [
        r"(?:totale\s+)?attivit[àa][\s']+non\s+correnti",  # IFRS
        r"totale\s+attivo\b",
        r"totale\s+immobilizzazioni",
        r"totale\s+attivit[àa]\s+correnti",
        r"^attivo\b",  # OIC - inizio riga
    ]
    # SP Passivo
    sp_passivo_patterns = [
        r"totale\s+patrimonio\s+netto",
        r"totale\s+passiv",
        r"passivit[àa]\s+non\s+correnti",
        r"passivit[àa]\s+correnti",
    ]
    # CE
    ce_patterns = [
        r"conto\s+economico",
        r"risultato\s+operativo",
        r"ebitda",
        r"risultato\s+prima\s+delle\s+imposte",
        r"risultato\s+netto\s+d.esercizio",
        r"valore\s+della\s+produzione",  # OIC
        r"costi\s+della\s+produzione",  # OIC
    ]

    # Conta match
    sp_attivo_score = sum(1 for p in sp_attivo_patterns if re.search(p, testo_lower))
    sp_passivo_score = sum(1 for p in sp_passivo_patterns if re.search(p, testo_lower))
    ce_score = sum(1 for p in ce_patterns if re.search(p, testo_lower))

    # Conta numeri formattati (indicano tabella contabile, non testo discorsivo)
    numeri = re.findall(r'\b\d{1,3}(?:\.\d{3})+\b', testo)
    densita_numeri = len(numeri) / max(len(lines), 1)

    # Conta righe con pattern "label  numero  numero" (tipico di un prospetto)
    righe_prospetto = 0
    for line in lines:
        if re.search(r'[\w\s]{10,}\s+[\d.()\-]+\s+[\d.()\-]+', line):
            righe_prospetto += 1
    densita_righe_prospetto = righe_prospetto / max(len(lines), 1)

    # Un prospetto ha alta densità di numeri E pattern specifici
    if densita_numeri > 0.3 and densita_righe_prospetto > 0.2:
        if sp_attivo_score >= 2:
            return {"tipo": "sp_attivo", "score": sp_attivo_score + densita_numeri * 3}
        if sp_passivo_score >= 2:
            return {"tipo": "sp_passivo", "score": sp_passivo_score + densita_numeri * 3}
        if ce_score >= 2:
            return {"tipo": "ce", "score": ce_score + densita_numeri * 3}
        # Match singolo ma alta densità = probabile prospetto
        if sp_attivo_score >= 1:
            return {"tipo": "sp_attivo", "score": sp_attivo_score + densita_numeri * 2}
        if sp_passivo_score >= 1:
            return {"tipo": "sp_passivo", "score": sp_passivo_score + densita_numeri * 2}
        if ce_score >= 1:
            return {"tipo": "ce", "score": ce_score + densita_numeri * 2}

    return {"tipo": None, "score": 0}


def _rileva_formato(testi: list[dict]) -> str:
    """Rileva se il bilancio è IFRS o OIC dal testo complessivo."""
    segnali_ifrs = 0
    segnali_oic = 0

    for item in testi:
        testo_lower = item["testo"].lower()
        if any(kw in testo_lower for kw in [
            "attività non correnti", "attività correnti",
            "passività non correnti", "ifrs", "ias ",
        ]):
            segnali_ifrs += 1
        if any(kw in testo_lower for kw in [
            "valore della produzione", "costi della produzione",
            "b) immobilizzazioni", "a) crediti verso soci",
        ]):
            segnali_oic += 1

    return "IFRS" if segnali_ifrs > segnali_oic else "OIC_ordinario"


def _ricognizione_documento(pdf_path: str, tipo_bilancio: str = "separato") -> dict:
    """Identifica le pagine esatte dei prospetti SP e CE.

    Strategia:
    1. Scansiona tutte le pagine con identifica_sezione (veloce)
    2. Per le candidate, calcola score con _pagina_e_prospetto
    3. Seleziona le pagine col punteggio più alto
    4. Per bilanci con consolidato+separato, distingui i due set
    """
    n_pagine = _conta_pagine(pdf_path)
    testi = estrai_testo_pdf(pdf_path)

    formato = _rileva_formato(testi)

    # Score ogni pagina
    candidati = []
    for item in testi:
        pagina_0based = item["pagina"] - 1
        analisi = _pagina_e_prospetto(item["testo"])
        if analisi["tipo"]:
            candidati.append({
                "pagina": pagina_0based,
                "tipo": analisi["tipo"],
                "score": analisi["score"],
            })

    # Se bilancio "separato" e ci sono sia consolidato che separato,
    # il separato è tipicamente dopo il consolidato nel PDF.
    # Euristica: raggruppa per prossimità e prendi il gruppo più alto in pagine.
    # Per "consolidato", prendi il primo gruppo.

    # Raggruppa pagine contigue per tipo
    sp_pagine = [c for c in candidati if c["tipo"].startswith("sp")]
    ce_pagine = [c for c in candidati if c["tipo"] == "ce"]

    # Se ci sono più gruppi di SP (consolidato + separato), seleziona quello giusto
    sp_selezionate = _seleziona_gruppo_prospetto(sp_pagine, tipo_bilancio, n_pagine)
    ce_selezionate = _seleziona_gruppo_prospetto(ce_pagine, tipo_bilancio, n_pagine)

    return {
        "n_pagine": n_pagine,
        "formato_rilevato": formato,
        "tipo_bilancio": tipo_bilancio,
        "sp_pagine": sp_selezionate,
        "ce_pagine": ce_selezionate,
        "tutti_candidati": candidati,
    }


def _seleziona_gruppo_prospetto(
    candidati: list[dict],
    tipo_bilancio: str,
    n_pagine: int,
) -> list[int]:
    """Seleziona il gruppo di pagine giusto tra i candidati.

    Per bilancio separato: prende le pagine nella seconda metà del PDF.
    Per consolidato: prende le pagine nella prima metà.
    Se c'è un solo gruppo, lo prende comunque.
    """
    if not candidati:
        return []

    # Ordina per pagina
    candidati_ordinati = sorted(candidati, key=lambda c: c["pagina"])

    # Raggruppa pagine contigue (gap max 2 pagine)
    gruppi = []
    gruppo_corrente = [candidati_ordinati[0]]

    for c in candidati_ordinati[1:]:
        if c["pagina"] - gruppo_corrente[-1]["pagina"] <= 3:
            gruppo_corrente.append(c)
        else:
            gruppi.append(gruppo_corrente)
            gruppo_corrente = [c]
    gruppi.append(gruppo_corrente)

    if len(gruppi) == 1:
        return [c["pagina"] for c in gruppi[0]]

    # Più gruppi: seleziona in base al tipo bilancio
    # Calcola score totale per gruppo e filtra gruppi con score basso
    for g in gruppi:
        g_score = sum(c["score"] for c in g)
        g[0]["_group_score"] = g_score
        g[0]["_group_size"] = len(g)

    # Filtra gruppi con singola pagina a basso score (probabilmente falsi positivi)
    gruppi_validi = [g for g in gruppi if len(g) >= 2 or g[0]["score"] > 5]
    if not gruppi_validi:
        gruppi_validi = gruppi  # fallback

    if tipo_bilancio == "separato":
        # Preferisci il gruppo con pagine più alte tra quelli validi
        gruppi_validi.sort(key=lambda g: g[0]["pagina"], reverse=True)
    else:
        # Consolidato: preferisci il primo gruppo
        gruppi_validi.sort(key=lambda g: g[0]["pagina"])

    return [c["pagina"] for c in gruppi_validi[0]]


# ---------------------------------------------------------------------------
# Fase 2 — Parsing intelligente con Claude (solo pagine rilevanti)
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """Sei un esperto di bilanci italiani. Analizza il testo e le tabelle grezze estratti da un PDF di bilancio e produci un output JSON pulito e strutturato.

REGOLE:
1. Restituisci SOLO JSON valido, nessun testo prima o dopo.
2. Ricomponi label spezzate su più righe in un'unica stringa.
3. Espandi celle multi-riga (con \\n) in righe separate, associando label e valori.
4. Marca righe "di cui" con livello "di_cui", collegale al genitore. NON sono addendi.
5. Riferimenti note (numeri 1-2 cifre tra label e valori) vanno in "nota_ref", NON nei valori.
6. I valori restano STRINGHE grezze (es. "1.250.000", "(350.000)") — non convertire.
7. Identifica la gerarchia: sezione > subtotale > dettaglio.
8. Ogni totale/subtotale va marcato come "totale" o "subtotale".
9. Se trovi problemi di layout, documentali in "problemi_layout".

FORMATO OUTPUT:
{
  "azienda": "...",
  "formato_bilancio": "IFRS|OIC_ordinario|OIC_abbreviato|OIC_micro",
  "anni_presenti": ["2024", "2023"],
  "sezioni": {
    "sp_attivo": {
      "pagine": [52],
      "righe": [
        {"label": "...", "valori": {"2024": "...", "2023": "..."}, "livello": "dettaglio|subtotale|totale|di_cui|sezione", "genitore": "...|null", "nota_ref": "...|null"}
      ]
    },
    "sp_passivo": {"pagine": [], "righe": []},
    "ce": {"pagine": [], "righe": []},
    "rendiconto_finanziario": {"pagine": [], "righe": []}
  },
  "problemi_layout": [],
  "confidence_estrazione": 0.95
}"""


def _prepara_prompt_pagine(pdf_path: str, pagine: list[int], sezione: str) -> str:
    """Prepara i dati grezzi di specifiche pagine per Claude."""
    if not pagine:
        return ""

    parti = [f"\n{'=' * 50}", f"{sezione.upper()} — DATI GREZZI", "=" * 50]

    testi = estrai_testo_pdf(pdf_path, pagine)
    tabelle = estrai_tabelle_pdf(pdf_path, pagine)

    for item in testi:
        parti.append(f"\n--- TESTO PAGINA {item['pagina']} ---")
        parti.append(item["testo"])

    for item in tabelle:
        parti.append(f"\n--- TABELLA PAGINA {item['pagina']} ---")
        for i, riga in enumerate(item["righe"]):
            parti.append(f"  Riga {i}: {json.dumps(riga, ensure_ascii=False)}")

    return "\n".join(parti)


def _parsing_con_claude(
    pdf_path: str,
    sp_pagine: list[int],
    ce_pagine: list[int],
    formato: str,
    tipo_bilancio: str,
    model: str = "claude-sonnet-4-20250514",
    max_turns: int = 10,
) -> dict:
    """Invia solo le pagine dei prospetti a Claude."""
    client = crea_client()
    tools = definisci_tools_per_agente("skill_estrazione_pdf")

    # Prepara dati solo per le pagine rilevanti
    dati_sp = _prepara_prompt_pagine(pdf_path, sp_pagine, "stato patrimoniale")
    dati_ce = _prepara_prompt_pagine(pdf_path, ce_pagine, "conto economico")
    dati = dati_sp + "\n" + dati_ce

    n_chars = len(dati)
    print(f"[estrattore_pdf]   Dati per Claude: {n_chars:,} caratteri "
          f"({len(sp_pagine)} pag SP + {len(ce_pagine)} pag CE)")

    user_msg = f"""Bilancio {tipo_bilancio}, formato {formato}.
Path PDF: {pdf_path}
Pagine SP: {[p + 1 for p in sp_pagine]} (1-based).
Pagine CE: {[p + 1 for p in ce_pagine]} (1-based).

Analizza i dati qui sotto e produci il JSON strutturato.
Se servono pagine aggiuntive, usa i tool con il path PDF indicato sopra.

{dati}"""

    messages = [{"role": "user", "content": user_msg}]

    for turn in range(max_turns):
        response = client.messages.create(
            model=model,
            max_tokens=16384,
            system=_SYSTEM_PROMPT,
            messages=messages,
            tools=tools if tools else [],
        )

        text_parts = []
        tool_uses = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(block)

        if not tool_uses:
            testo = "\n".join(text_parts)
            return _estrai_json_da_risposta(testo)

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tu in tool_uses:
            result = esegui_tool(tu.name, tu.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result,
            })
        messages.append({"role": "user", "content": tool_results})

    return {"error": "Max turns raggiunto", "max_turns": max_turns}


def _estrai_json_da_risposta(testo: str) -> dict:
    """Estrae JSON dalla risposta di Claude."""
    testo = testo.strip()

    # Parsing diretto
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

    return {"error": "JSON non parsabile", "raw": testo[:500]}


# ---------------------------------------------------------------------------
# API pubblica
# ---------------------------------------------------------------------------

def estrai_pdf(
    pdf_path: str,
    tipo_bilancio: str = "separato",
    model: str = "claude-sonnet-4-20250514",
) -> dict:
    """Estrae dati strutturati da un PDF di bilancio italiano.

    Fase 1: Ricognizione deterministica (identifica pagine esatte dei prospetti)
    Fase 2: Parsing LLM (solo sulle pagine dei prospetti, ~3-4 pagine)
    """
    pdf_path = str(Path(pdf_path).resolve())
    print(f"[estrattore_pdf] Estrazione da: {Path(pdf_path).name}")
    print(f"[estrattore_pdf] Tipo: {tipo_bilancio}")

    # --- Fase 1: Ricognizione ---
    print("[estrattore_pdf] Fase 1: Ricognizione pagine prospetti...")
    ricognizione = _ricognizione_documento(pdf_path, tipo_bilancio)

    sp_pagine = ricognizione["sp_pagine"]
    ce_pagine = ricognizione["ce_pagine"]
    formato = ricognizione["formato_rilevato"]

    print(f"[estrattore_pdf]   {ricognizione['n_pagine']} pagine totali, formato {formato}")
    print(f"[estrattore_pdf]   SP: pagine {[p+1 for p in sp_pagine]} (1-based)")
    print(f"[estrattore_pdf]   CE: pagine {[p+1 for p in ce_pagine]} (1-based)")

    if not sp_pagine and not ce_pagine:
        return {"error": "Nessun prospetto trovato nel PDF"}

    # --- Fase 2: Parsing con Claude ---
    print("[estrattore_pdf] Fase 2: Parsing con Claude...")
    risultato = _parsing_con_claude(
        pdf_path=pdf_path,
        sp_pagine=sp_pagine,
        ce_pagine=ce_pagine,
        formato=formato,
        tipo_bilancio=tipo_bilancio,
        model=model,
    )

    # Post-processing
    if "sezioni" in risultato:
        for sez_key, pagine in [("sp_attivo", sp_pagine), ("sp_passivo", sp_pagine), ("ce", ce_pagine)]:
            if sez_key in risultato["sezioni"]:
                if not risultato["sezioni"][sez_key].get("pagine"):
                    risultato["sezioni"][sez_key]["pagine"] = [p + 1 for p in pagine]

    if "error" in risultato:
        print(f"[estrattore_pdf]   ERRORE: {risultato['error']}")
    else:
        conf = risultato.get("confidence_estrazione", "?")
        print(f"[estrattore_pdf]   Completato (confidence: {conf})")

    return risultato


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    pdf = sys.argv[1] if len(sys.argv) > 1 else (
        "data/input/Relazione_finanziaria_al_bilancio_d_esercizio_al_31_dicembre_2024"
        "_e_al_Bilancio_consolidato_al_31_dicembre_2024.pdf"
    )
    tipo = sys.argv[2] if len(sys.argv) > 2 else "separato"

    result = estrai_pdf(pdf, tipo)

    out_path = Path("data/output/estrazione_pdf_result.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nRisultato salvato in: {out_path}")

    if "sezioni" in result:
        for sez, data in result["sezioni"].items():
            n_righe = len(data.get("righe", []))
            if n_righe:
                print(f"  {sez}: {n_righe} righe")
