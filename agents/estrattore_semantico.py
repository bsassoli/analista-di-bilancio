"""Agente estrattore semantico: estrae evidenze strutturate dalla nota integrativa.

Approccio ibrido deterministico + LLM mirato:
  Fase 1: estrae testo dalle pagine NI (pdfplumber).
  Fase 2: estrazione deterministica via tools.semantic_parser.
  Fase 3: identifica gap (tipi di evidenza non trovati).
  Fase 4: chiamate LLM mirate per colmare i gap (max 4 chiamate).
  Fase 5: merge e dedup dei risultati.
"""

import json
import re
import sys
from pathlib import Path

import pdfplumber
from dotenv import load_dotenv

load_dotenv(override=True)

from agents.base import crea_client
from tools.evidence_schema import DocumentProfile, SemanticEvidence

# Import deterministico — il modulo potrebbe non esistere ancora
try:
    from tools.semantic_parser import estrai_evidenze_deterministiche
except ImportError:
    estrai_evidenze_deterministiche = None


# ---------------------------------------------------------------------------
# Keywords per la ricerca di pagine rilevanti per tipo di evidenza
# ---------------------------------------------------------------------------

_KEYWORDS_PER_TIPO: dict[str, list[str]] = {
    "debt": [
        "scadenza dei debiti",
        "debiti per scadenza",
        "analisi debiti",
        "quota oltre",
        "entro l'esercizio successivo",
        "oltre l'esercizio successivo",
        "oltre 5 anni",
        "debiti verso banche",
        "finanziamenti",
        "mutui",
    ],
    "lease": [
        "leasing",
        "ifrs 16",
        "diritti d'uso",
        "right-of-use",
        "passività per leasing",
        "canoni di locazione",
        "lease liabilit",
    ],
    "related_party": [
        "parti correlate",
        "rapporti infragruppo",
        "operazioni con parti correlate",
        "società controllante",
        "controllate",
        "collegate",
        "crediti verso controllate",
        "debiti verso controllate",
    ],
    "fund": [
        "fondi per rischi",
        "fondi rischi e oneri",
        "fondo garanzia",
        "fondo ristrutturazione",
        "accantonamenti",
        "fondo imposte",
        "fondo svalutazione",
        "trattamento di fine rapporto",
    ],
}


# ---------------------------------------------------------------------------
# Mini-prompt LLM per ciascun tipo di evidenza
# ---------------------------------------------------------------------------

_PROMPTS_PER_TIPO: dict[str, str] = {
    "debt": (
        "Analizza questo testo dalla nota integrativa e estrai informazioni "
        "sulla scadenza dei debiti.\n\n"
        "Restituisci SOLO JSON valido:\n"
        "{\n"
        '  "trovato": true/false,\n'
        '  "scadenze": {\n'
        '    "entro_esercizio": 0,\n'
        '    "oltre_esercizio_entro_5": 0,\n'
        '    "oltre_5_anni": 0\n'
        "  },\n"
        '  "dettaglio": {\n'
        '    "verso_banche_breve": 0,\n'
        '    "verso_banche_lungo": 0,\n'
        '    "verso_fornitori": 0,\n'
        '    "tributari": 0,\n'
        '    "previdenziali": 0,\n'
        '    "altri": 0\n'
        "  },\n"
        '  "snippet": "testo rilevante estratto",\n'
        '  "pagina": 0\n'
        "}\n\n"
        "Importi in euro INTERI. Se non trovi dati, metti trovato: false."
    ),
    "lease": (
        "Analizza questo testo dalla nota integrativa e estrai informazioni "
        "su leasing e diritti d'uso (IFRS 16 o leasing operativi).\n\n"
        "Restituisci SOLO JSON valido:\n"
        "{\n"
        '  "trovato": true/false,\n'
        '  "diritti_uso_lordo": 0,\n'
        '  "diritti_uso_netto": 0,\n'
        '  "passivita_leasing_breve": 0,\n'
        '  "passivita_leasing_lungo": 0,\n'
        '  "canoni_esercizio": 0,\n'
        '  "snippet": "testo rilevante estratto",\n'
        '  "pagina": 0\n'
        "}\n\n"
        "Importi in euro INTERI. Se non trovi dati, metti trovato: false."
    ),
    "related_party": (
        "Analizza questo testo dalla nota integrativa e estrai informazioni "
        "su rapporti con parti correlate e operazioni infragruppo.\n\n"
        "Restituisci SOLO JSON valido:\n"
        "{\n"
        '  "trovato": true/false,\n'
        '  "crediti_commerciali": 0,\n'
        '  "crediti_finanziari": 0,\n'
        '  "debiti_commerciali": 0,\n'
        '  "debiti_finanziari": 0,\n'
        '  "ricavi_infragruppo": 0,\n'
        '  "costi_infragruppo": 0,\n'
        '  "controparte_principale": "",\n'
        '  "snippet": "testo rilevante estratto",\n'
        '  "pagina": 0\n'
        "}\n\n"
        "Importi in euro INTERI. Se non trovi dati, metti trovato: false."
    ),
    "fund": (
        "Analizza questo testo dalla nota integrativa e estrai informazioni "
        "su fondi per rischi e oneri, accantonamenti e TFR.\n\n"
        "Restituisci SOLO JSON valido:\n"
        "{\n"
        '  "trovato": true/false,\n'
        '  "fondi": [\n'
        "    {\n"
        '      "nome": "nome fondo",\n'
        '      "natura": "operativo|finanziario",\n'
        '      "saldo_iniziale": 0,\n'
        '      "accantonamento": 0,\n'
        '      "utilizzo": 0,\n'
        '      "saldo_finale": 0\n'
        "    }\n"
        "  ],\n"
        '  "tfr_saldo": 0,\n'
        '  "snippet": "testo rilevante estratto",\n'
        '  "pagina": 0\n'
        "}\n\n"
        "Importi in euro INTERI. Se non trovi dati, metti trovato: false."
    ),
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _estrai_testi_pagine(pdf_path: str, pagine: list[int]) -> list[dict]:
    """Estrae testo da pagine specifiche usando pdfplumber.

    Args:
        pdf_path: Path al file PDF.
        pagine: Lista di numeri pagina 0-based.

    Returns:
        Lista di dict con chiavi 'pagina' (1-based) e 'testo'.
    """
    risultati = []
    with pdfplumber.open(pdf_path) as pdf:
        for p in pagine:
            if 0 <= p < len(pdf.pages):
                testo = pdf.pages[p].extract_text() or ""
                if testo.strip():
                    risultati.append({"pagina": p + 1, "testo": testo})
    return risultati


def _trova_pagine_rilevanti(
    testi: list[dict], keywords: list[str], max_pages: int = 3
) -> list[dict]:
    """Trova le N pagine piu rilevanti per le keywords date.

    Ordina per numero di keyword hit e restituisce le top N.
    """
    scored = []
    for item in testi:
        testo_lower = item["testo"].lower()
        hits = sum(1 for kw in keywords if kw in testo_lower)
        if hits > 0:
            scored.append((hits, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:max_pages]]


def _chunka_testo(testi: list[dict], max_chars: int = 3000) -> list[str]:
    """Concatena testi di pagine in chunk di massimo max_chars caratteri.

    Ogni chunk include i riferimenti di pagina nel testo.
    """
    chunks = []
    current = ""
    for item in testi:
        header = f"\n--- Pagina {item['pagina']} ---\n"
        blocco = header + item["testo"]
        if len(current) + len(blocco) > max_chars and current:
            chunks.append(current)
            current = blocco
        else:
            current += blocco
    if current.strip():
        chunks.append(current)
    return chunks


def _llm_estrai_evidenza(
    client, chunk: str, evidence_type: str, model: str
) -> list[SemanticEvidence]:
    """Invia un prompt LLM mirato per un tipo di evidenza specifico.

    Returns:
        Lista di SemanticEvidence estratte (vuota se nulla trovato).
    """
    prompt_template = _PROMPTS_PER_TIPO.get(evidence_type)
    if not prompt_template:
        return []

    user_msg = f"{prompt_template}\n\n---\nTESTO:\n{chunk}\n---"

    try:
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()

        # Estrai JSON dal testo (a volte il modello aggiunge markdown)
        json_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not json_match:
            return []
        data = json.loads(json_match.group())

        if not data.get("trovato", False):
            return []

        # Costruisci SemanticEvidence dal risultato
        pagina = data.get("pagina")
        snippet = data.get("snippet", "")

        # Rimuovi campi non-hint
        hint_data = {
            k: v
            for k, v in data.items()
            if k not in ("trovato", "snippet", "pagina")
        }

        return [
            SemanticEvidence(
                evidence_type=evidence_type,
                target_scope="document",
                normalized_hint=hint_data,
                source_page=pagina if isinstance(pagina, int) else None,
                source_section="nota_integrativa",
                snippet=snippet[:500] if snippet else "",
                confidence=0.7,
            )
        ]
    except (json.JSONDecodeError, IndexError, KeyError) as exc:
        print(f"[semantico] WARN: LLM parsing fallito per {evidence_type}: {exc}")
        return []
    except Exception as exc:
        print(f"[semantico] WARN: LLM call fallita per {evidence_type}: {exc}")
        return []


# ---------------------------------------------------------------------------
# Funzione principale
# ---------------------------------------------------------------------------


def estrai_semantica(
    pdf_path: str,
    profile: DocumentProfile,
    model: str = "claude-sonnet-4-20250514",
) -> list[SemanticEvidence]:
    """Estrae evidenze semantiche dalla nota integrativa.

    Pipeline ibrida: deterministico prima, poi LLM mirato per i gap.

    Args:
        pdf_path: Path al file PDF del bilancio.
        profile: DocumentProfile con page_map (contiene 'nota_integrativa').
        model: Modello Claude da usare per le chiamate LLM.

    Returns:
        Lista di SemanticEvidence estratte.
    """
    pagine_ni = profile.page_map.get("nota_integrativa", [])
    if not pagine_ni:
        print("[semantico] Nessuna pagina NI nel profile, skip.")
        return []

    # --- Fase 1: Estrai testo dalle pagine NI ---
    print(f"[semantico] Fase 1: estrazione testo da {len(pagine_ni)} pagine NI...")
    testi_pagine = _estrai_testi_pagine(pdf_path, pagine_ni)
    if not testi_pagine:
        print("[semantico] Nessun testo estratto dalle pagine NI.")
        return []
    print(f"[semantico] Fase 1 completata: {len(testi_pagine)} pagine con testo.")

    # --- Fase 2: Estrazione deterministica ---
    print("[semantico] Fase 2: estrazione deterministica...")
    evidenze_det: list[SemanticEvidence] = []
    if estrai_evidenze_deterministiche is not None:
        try:
            evidenze_det = estrai_evidenze_deterministiche(testi_pagine, pagine_ni)
            print(
                f"[semantico] Fase 2 completata: {len(evidenze_det)} evidenze deterministiche."
            )
        except Exception as exc:
            print(f"[semantico] WARN: estrazione deterministica fallita: {exc}")
    else:
        print("[semantico] Fase 2: tools.semantic_parser non disponibile, skip.")

    # --- Fase 3: Identifica gap ---
    print("[semantico] Fase 3: identificazione gap...")
    tipi_trovati = {e.evidence_type for e in evidenze_det}

    gap_types: list[str] = []
    # Debt: sempre interessante se NI presente
    if "debt" not in tipi_trovati:
        gap_types.append("debt")
    # Lease: solo per IFRS (dove IFRS 16 e obbligatorio)
    if "lease" not in tipi_trovati and profile.accounting_standard == "IFRS":
        gap_types.append("lease")
    # Related party: sempre interessante
    if "related_party" not in tipi_trovati:
        gap_types.append("related_party")
    # Fund: sempre interessante
    if "fund" not in tipi_trovati:
        gap_types.append("fund")

    if not gap_types:
        print("[semantico] Fase 3: nessun gap, skip LLM.")
        return evidenze_det

    print(f"[semantico] Fase 3 completata: gap da colmare = {gap_types}")

    # --- Fase 4: LLM mirato per ciascun gap ---
    print(f"[semantico] Fase 4: {len(gap_types)} chiamate LLM mirate...")
    client = crea_client()
    evidenze_llm: list[SemanticEvidence] = []

    for gap_type in gap_types:
        keywords = _KEYWORDS_PER_TIPO.get(gap_type, [])
        pagine_rilevanti = _trova_pagine_rilevanti(testi_pagine, keywords, max_pages=3)

        if not pagine_rilevanti:
            # Fallback: usa le prime 3 pagine NI
            pagine_rilevanti = testi_pagine[:3]

        chunks = _chunka_testo(pagine_rilevanti, max_chars=3000)
        if not chunks:
            continue

        # Usa solo il primo chunk (il piu rilevante) per restare focalizzati
        print(f"[semantico]   -> LLM per '{gap_type}' ({len(chunks[0])} chars)...")
        nuove = _llm_estrai_evidenza(client, chunks[0], gap_type, model)
        evidenze_llm.extend(nuove)
        if nuove:
            print(f"[semantico]   -> '{gap_type}': {len(nuove)} evidenze trovate.")
        else:
            print(f"[semantico]   -> '{gap_type}': nessuna evidenza.")

    print(
        f"[semantico] Fase 4 completata: {len(evidenze_llm)} evidenze LLM."
    )

    # --- Fase 5: Merge e dedup ---
    print("[semantico] Fase 5: merge e deduplicazione...")
    tutte = evidenze_det + evidenze_llm

    # Dedup per (evidence_type, source_page): tieni la prima occorrenza
    seen: set[tuple[str, int | None]] = set()
    risultato: list[SemanticEvidence] = []
    for ev in tutte:
        key = (ev.evidence_type, ev.source_page)
        if key not in seen:
            seen.add(key)
            risultato.append(ev)

    print(
        f"[semantico] Fase 5 completata: {len(risultato)} evidenze totali "
        f"(da {len(tutte)} pre-dedup)."
    )
    return risultato


# ---------------------------------------------------------------------------
# Entrypoint CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json
    from dataclasses import asdict

    if len(sys.argv) < 2:
        print("Uso: python -m agents.estrattore_semantico <path_pdf>")
        sys.exit(1)

    pdf_path = sys.argv[1]
    if not Path(pdf_path).exists():
        print(f"File non trovato: {pdf_path}")
        sys.exit(1)

    # Costruisci un profile minimale usando la ricognizione del qualitativo
    from tools.pdf_parser import estrai_testo_pdf

    testi = estrai_testo_pdf(pdf_path)

    # Identifica pagine NI con euristica semplice
    ni_pages: list[int] = []
    kw_ni = ["nota integrativa", "criteri di valutazione", "principi contabili"]
    inizio = None
    for item in testi:
        testo_lower = item["testo"].lower()
        p_0based = item["pagina"] - 1
        if any(kw in testo_lower for kw in kw_ni):
            inizio = p_0based
            break
    if inizio is not None:
        ni_pages = list(range(inizio, len(testi)))
    else:
        # Fallback: keyword scan
        for item in testi:
            testo_lower = item["testo"].lower()
            p_0based = item["pagina"] - 1
            if any(kw in testo_lower for kw in kw_ni):
                ni_pages.append(p_0based)

    # Rileva standard contabile
    full_text = " ".join(item["testo"].lower() for item in testi[:10])
    standard = "IFRS" if "ifrs" in full_text or "ias" in full_text else "OIC"

    profile = DocumentProfile(
        company_name="(da CLI)",
        years_present=[],
        accounting_standard=standard,
        scope="unknown",
        format_type="unknown",
        page_map={
            "sp": [],
            "ce": [],
            "nota_integrativa": ni_pages,
            "relazione_gestione": [],
            "other": [],
        },
        n_pages=len(testi),
    )

    print(f"Profile: {len(ni_pages)} pagine NI, standard={standard}")
    print(f"Pagine NI (0-based): {ni_pages}\n")

    evidenze = estrai_semantica(pdf_path, profile)

    print(f"\n=== {len(evidenze)} evidenze estratte ===\n")
    for i, ev in enumerate(evidenze):
        d = asdict(ev)
        print(f"[{i + 1}] {_json.dumps(d, indent=2, ensure_ascii=False)}\n")
