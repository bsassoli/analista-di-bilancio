"""Deterministic pattern extraction for financial note text (nota integrativa).

Extracts structured SemanticEvidence objects from raw page text using regex
patterns and keyword heuristics. No LLM or external API calls — everything
is purely deterministic.
"""
from __future__ import annotations

import re
from tools.evidence_schema import SemanticEvidence


# ---------------------------------------------------------------------------
# Number parsing (Italian format: 1.234.567 or 1.234.567,89)
# ---------------------------------------------------------------------------
_RE_ITALIAN_NUMBER = re.compile(
    r"(?<!\w)"                          # not preceded by word char
    r"-?\s*"                            # optional minus + space
    r"(\d{1,3}(?:\.\d{3})*)"           # integer part with dot-thousands
    r"(?:,\d{1,2})?"                    # optional decimal comma
    r"(?!\w)",                          # not followed by word char
)


def _parse_italian_number(s: str) -> int | None:
    """Parse an Italian-formatted number string to int, or None."""
    s = s.strip().replace(" ", "")
    m = _RE_ITALIAN_NUMBER.search(s)
    if not m:
        return None
    # rebuild: strip dots, drop comma-decimals, handle minus
    raw = m.group(0).replace(" ", "")
    neg = raw.startswith("-")
    raw = raw.lstrip("- ")
    # remove dots (thousand sep), truncate comma-decimals
    if "," in raw:
        raw = raw.split(",")[0]
    raw = raw.replace(".", "")
    try:
        val = int(raw)
        return -val if neg else val
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _cerca_importo_vicino(testo: str, posizione: int, raggio: int = 200) -> int | None:
    """Search for an Italian-formatted number near *posizione* in *testo*.

    Returns the closest number as an integer, or None.
    """
    start = max(0, posizione - raggio)
    end = min(len(testo), posizione + raggio)
    window = testo[start:end]

    best_val: int | None = None
    best_dist = raggio + 1

    for m in _RE_ITALIAN_NUMBER.finditer(window):
        val = _parse_italian_number(m.group(0))
        if val is None or val == 0:
            continue
        match_center = m.start() + (m.end() - m.start()) // 2
        # posizione relative to window
        rel_pos = posizione - start
        dist = abs(match_center - rel_pos)
        if dist < best_dist:
            best_dist = dist
            best_val = val

    return best_val


def _estrai_snippet(testo: str, posizione: int, raggio: int = 150) -> str:
    """Extract a text snippet of up to *2*raggio* chars around *posizione*."""
    start = max(0, posizione - raggio)
    end = min(len(testo), posizione + raggio)
    snippet = testo[start:end].strip()
    # collapse whitespace
    snippet = re.sub(r"\s+", " ", snippet)
    if len(snippet) > 300:
        snippet = snippet[:300]
    return snippet


def _cerca_pattern(testo: str, patterns: list[str]) -> list[tuple[int, str]]:
    """Find all pattern matches in *testo*.

    Returns list of (position, matched_keyword) sorted by position.
    """
    results: list[tuple[int, str]] = []
    for pat in patterns:
        for m in re.finditer(pat, testo, re.IGNORECASE):
            results.append((m.start(), m.group(0)))
    results.sort(key=lambda x: x[0])
    return results


# ---------------------------------------------------------------------------
# Amount extraction helpers for debt maturity tables
# ---------------------------------------------------------------------------

def _estrai_importi_scadenza(testo: str, posizione: int) -> dict[str, int | None]:
    """Try to extract debt maturity buckets from text near *posizione*."""
    window_start = max(0, posizione - 50)
    window_end = min(len(testo), posizione + 800)
    window = testo[window_start:window_end]

    hint: dict[str, int | None] = {
        "entro_esercizio": None,
        "oltre_esercizio_entro_5": None,
        "oltre_5_anni": None,
    }

    # "entro l'esercizio" / "entro 12 mesi" / "entro un anno"
    entro = re.search(
        r"entro\s+(?:l['\u2019]?\s*esercizio|12\s*mesi|un\s*anno|1\s*anno)",
        window, re.IGNORECASE,
    )
    if entro:
        hint["entro_esercizio"] = _cerca_importo_vicino(
            window, entro.start(), raggio=150,
        )

    # "oltre l'esercizio" / "da 1 a 5 anni" / "oltre 12 mesi entro 5"
    oltre5_inner = re.search(
        r"(?:oltre\s+(?:l['\u2019]?\s*esercizio|12\s*mesi|un\s*anno)"
        r"(?:\s+(?:ed\s+)?entro\s+(?:cinque|5)\s+anni)?|da\s+1\s+a\s+5\s+anni)",
        window, re.IGNORECASE,
    )
    if oltre5_inner:
        hint["oltre_esercizio_entro_5"] = _cerca_importo_vicino(
            window, oltre5_inner.start(), raggio=150,
        )

    # "oltre 5 anni" / "oltre cinque anni"
    oltre5 = re.search(r"oltre\s+(?:cinque|5)\s+anni", window, re.IGNORECASE)
    if oltre5:
        hint["oltre_5_anni"] = _cerca_importo_vicino(
            window, oltre5.start(), raggio=150,
        )

    return hint


# ---------------------------------------------------------------------------
# Signal extractors — one per evidence_type
# ---------------------------------------------------------------------------

def _extract_debt(testo: str, pagina: int) -> list[SemanticEvidence]:
    """Debt maturity signals."""
    patterns = [
        r"scadenza\s+dei\s+debiti",
        r"debiti\s+per\s+scadenza",
        r"analisi\s+per\s+scadenza",
        r"ripartizione\s+dei\s+debiti",
        r"suddivisione\s+dei\s+debiti",
    ]
    evidenze: list[SemanticEvidence] = []
    for pos, kw in _cerca_pattern(testo, patterns):
        hint = _estrai_importi_scadenza(testo, pos)
        has_amounts = any(v is not None for v in hint.values())
        # clean None values from hint
        clean_hint = {k: v for k, v in hint.items() if v is not None}
        evidenze.append(SemanticEvidence(
            evidence_type="debt",
            target_scope="document",
            normalized_hint=clean_hint,
            source_page=pagina,
            source_section="nota_integrativa",
            snippet=_estrai_snippet(testo, pos),
            confidence=0.9 if has_amounts else 0.7,
        ))
    return evidenze


def _extract_lease(testo: str, pagina: int) -> list[SemanticEvidence]:
    """Lease / IFRS 16 signals."""
    patterns = [
        r"diritti\s+d['\u2019]uso",
        r"IFRS\s*16",
        r"right[\s-]*of[\s-]*use",
        r"passivit[àa]\s+per\s+leasing",
        r"contratti\s+di\s+leasing",
        r"leasing\s+finanziari[eo]?",
        r"leasing\s+operativ[oi]",
    ]
    evidenze: list[SemanticEvidence] = []
    seen_positions: set[int] = set()
    for pos, kw in _cerca_pattern(testo, patterns):
        # deduplicate overlapping matches (within 100 chars)
        bucket = pos // 100
        if bucket in seen_positions:
            continue
        seen_positions.add(bucket)

        hint: dict = {}
        amt = _cerca_importo_vicino(testo, pos, raggio=200)
        if amt is not None:
            # guess which bucket based on keyword
            kw_lower = kw.lower()
            if "passivit" in kw_lower:
                hint["passivita_leasing"] = amt
            elif "diritti" in kw_lower or "right" in kw_lower:
                hint["diritti_uso"] = amt
            else:
                hint["importo"] = amt

        evidenze.append(SemanticEvidence(
            evidence_type="lease",
            target_scope="document",
            normalized_hint=hint,
            source_page=pagina,
            source_section="nota_integrativa",
            snippet=_estrai_snippet(testo, pos),
            confidence=0.9 if hint else 0.7,
        ))
    return evidenze


def _extract_related_party(testo: str, pagina: int) -> list[SemanticEvidence]:
    """Related party transaction signals."""
    patterns = [
        r"parti\s+correlate",
        r"rapporti\s+infragruppo",
        r"operazioni\s+con\s+parti\s+correlate",
        r"transazioni\s+con\s+parti\s+correlate",
        r"societ[àa]\s+controllante",
        r"societ[àa]\s+controllat[ea]",
        r"related\s+part(?:y|ies)",
    ]
    evidenze: list[SemanticEvidence] = []
    seen_positions: set[int] = set()
    for pos, kw in _cerca_pattern(testo, patterns):
        bucket = pos // 200
        if bucket in seen_positions:
            continue
        seen_positions.add(bucket)

        kw_lower = kw.lower()
        if "infragruppo" in kw_lower:
            tipo = "infragruppo"
        else:
            tipo = "correlate"

        evidenze.append(SemanticEvidence(
            evidence_type="related_party",
            target_scope="document",
            normalized_hint={"tipo": tipo},
            source_page=pagina,
            source_section="nota_integrativa",
            snippet=_estrai_snippet(testo, pos),
            confidence=0.7,
        ))
    return evidenze


def _extract_fund(testo: str, pagina: int) -> list[SemanticEvidence]:
    """Provisions and funds signals."""
    patterns = [
        r"fondi?\s+per\s+rischi",
        r"fondo\s+rischi",
        r"fondi?\s+oneri",
        r"accantonament[oi]",
        r"fondo\s+garanzia",
        r"fondo\s+ristrutturazione",
        r"fondi?\s+per\s+rischi\s+e\s+oneri",
    ]
    evidenze: list[SemanticEvidence] = []
    seen_positions: set[int] = set()
    for pos, kw in _cerca_pattern(testo, patterns):
        bucket = pos // 150
        if bucket in seen_positions:
            continue
        seen_positions.add(bucket)

        # determine natura
        snippet = _estrai_snippet(testo, pos, raggio=250)
        snippet_lower = snippet.lower()
        if any(w in snippet_lower for w in ("garanzia", "cause", "contenzios", "legale", "giudizi")):
            natura = "operativo"
        elif any(w in snippet_lower for w in ("derivat", "copertura", "finanziari")):
            natura = "finanziario"
        else:
            natura = "sconosciuto"

        amt = _cerca_importo_vicino(testo, pos, raggio=200)
        hint: dict = {"natura": natura}
        if amt is not None:
            hint["importo"] = amt

        evidenze.append(SemanticEvidence(
            evidence_type="fund",
            target_scope="document",
            normalized_hint=hint,
            source_page=pagina,
            source_section="nota_integrativa",
            snippet=_estrai_snippet(testo, pos),
            confidence=0.9 if amt is not None else 0.7,
        ))
    return evidenze


def _extract_non_recurring(testo: str, pagina: int) -> list[SemanticEvidence]:
    """Non-recurring items signals."""
    patterns = [
        r"componenti\s+straordinari[eo]?",
        r"(?:proventi|oneri)\s+non\s+ricorrenti",
        r"sopravvenien[zt][ea]",
        r"plusvalen[zt][ea]",
        r"minusvalen[zt][ea]",
        r"svalutazione\s+crediti",
        r"impairment",
        r"write[\s-]*off",
        r"cessione\s+(?:di\s+)?(?:attivit|ramo|partecipazion)",
    ]
    evidenze: list[SemanticEvidence] = []
    seen_positions: set[int] = set()
    for pos, kw in _cerca_pattern(testo, patterns):
        bucket = pos // 150
        if bucket in seen_positions:
            continue
        seen_positions.add(bucket)

        amt = _cerca_importo_vicino(testo, pos, raggio=200)
        hint: dict = {}
        if amt is not None:
            hint["importo"] = amt

        evidenze.append(SemanticEvidence(
            evidence_type="non_recurring",
            target_scope="document",
            normalized_hint=hint,
            source_page=pagina,
            source_section="nota_integrativa",
            snippet=_estrai_snippet(testo, pos),
            confidence=0.9 if amt is not None else 0.7,
        ))
    return evidenze


def _extract_tax(testo: str, pagina: int) -> list[SemanticEvidence]:
    """Tax assets/liabilities signals."""
    patterns = [
        r"imposte\s+anticipate",
        r"imposte\s+differite",
        r"attivit[àa]\s+per\s+imposte",
        r"passivit[àa]\s+per\s+imposte",
        r"fiscalit[àa]\s+differita",
        r"deferred\s+tax",
    ]
    evidenze: list[SemanticEvidence] = []
    seen_positions: set[int] = set()
    for pos, kw in _cerca_pattern(testo, patterns):
        bucket = pos // 150
        if bucket in seen_positions:
            continue
        seen_positions.add(bucket)

        amt = _cerca_importo_vicino(testo, pos, raggio=200)
        hint: dict = {}
        if amt is not None:
            hint["importo"] = amt

        evidenze.append(SemanticEvidence(
            evidence_type="tax",
            target_scope="document",
            normalized_hint=hint,
            source_page=pagina,
            source_section="nota_integrativa",
            snippet=_estrai_snippet(testo, pos),
            confidence=0.9 if amt is not None else 0.7,
        ))
    return evidenze


def _extract_receivable(testo: str, pagina: int) -> list[SemanticEvidence]:
    """Factoring / securitization signals."""
    patterns = [
        r"factoring",
        r"cessione\s+(?:di\s+)?crediti",
        r"pro[\s-]*soluto",
        r"pro[\s-]*solvendo",
        r"cartolarizzazione",
        r"reverse\s+factoring",
        r"securiti[sz]ation",
    ]
    evidenze: list[SemanticEvidence] = []
    seen_positions: set[int] = set()
    for pos, kw in _cerca_pattern(testo, patterns):
        bucket = pos // 200
        if bucket in seen_positions:
            continue
        seen_positions.add(bucket)

        kw_lower = kw.lower().replace(" ", "").replace("-", "")
        if "prosoluto" in kw_lower:
            tipo = "pro_soluto"
        elif "prosolvendo" in kw_lower:
            tipo = "pro_solvendo"
        elif "reverse" in kw_lower:
            tipo = "reverse_factoring"
        else:
            tipo = "sconosciuto"

        amt = _cerca_importo_vicino(testo, pos, raggio=200)
        hint: dict = {"tipo": tipo}
        if amt is not None:
            hint["importo"] = amt

        evidenze.append(SemanticEvidence(
            evidence_type="receivable",
            target_scope="document",
            normalized_hint=hint,
            source_page=pagina,
            source_section="nota_integrativa",
            snippet=_estrai_snippet(testo, pos),
            confidence=0.9 if amt is not None else 0.7,
        ))
    return evidenze


def _extract_minority_interest(testo: str, pagina: int) -> list[SemanticEvidence]:
    """Minority interests signals."""
    patterns = [
        r"interessenz[ea]\s+di\s+terzi",
        r"quota\s+di\s+terzi",
        r"azionisti\s+di\s+minoranza",
        r"soci\s+di\s+minoranza",
        r"non[\s-]*controlling\s+interest",
        r"patrimonio\s+(?:netto\s+)?di\s+terzi",
        r"capitale\s+(?:e\s+riserve\s+)?di\s+terzi",
    ]
    evidenze: list[SemanticEvidence] = []
    seen_positions: set[int] = set()
    for pos, kw in _cerca_pattern(testo, patterns):
        bucket = pos // 200
        if bucket in seen_positions:
            continue
        seen_positions.add(bucket)

        amt = _cerca_importo_vicino(testo, pos, raggio=200)
        hint: dict = {}
        if amt is not None:
            hint["importo"] = amt

        evidenze.append(SemanticEvidence(
            evidence_type="minority_interest",
            target_scope="document",
            normalized_hint=hint,
            source_page=pagina,
            source_section="nota_integrativa",
            snippet=_estrai_snippet(testo, pos),
            confidence=0.9 if amt is not None else 0.7,
        ))
    return evidenze


def _extract_going_concern(testo: str, pagina: int) -> list[SemanticEvidence]:
    """Going concern signals — high priority."""
    patterns = [
        r"continuit[àa]\s+aziendale",
        r"going\s+concern",
        r"dubbi\s+sulla\s+continuit[àa]",
        r"incertezza\s+significativa",
        r"presupposto\s+della\s+continuit[àa]",
    ]
    evidenze: list[SemanticEvidence] = []
    seen_positions: set[int] = set()
    for pos, kw in _cerca_pattern(testo, patterns):
        bucket = pos // 200
        if bucket in seen_positions:
            continue
        seen_positions.add(bucket)

        evidenze.append(SemanticEvidence(
            evidence_type="going_concern",
            target_scope="document",
            normalized_hint={},
            source_page=pagina,
            source_section="nota_integrativa",
            snippet=_estrai_snippet(testo, pos, raggio=200),
            confidence=0.95,
        ))
    return evidenze


def _extract_accounting_policy(testo: str, pagina: int) -> list[SemanticEvidence]:
    """Accounting policy signals from 'criteri di valutazione' sections."""
    evidenze: list[SemanticEvidence] = []

    # Look for "criteri di valutazione" as section entry point
    criteri_matches = _cerca_pattern(testo, [r"criteri\s+di\s+valutazione"])

    # Also directly look for specific policy signals anywhere
    # 1. Inventory valuation
    inv_patterns = [
        r"rimanenz[ea].*?(?:LIFO|FIFO|costo\s+medio|media\s+ponderata)",
        r"(?:LIFO|FIFO|costo\s+medio|media\s+ponderata).*?rimanenz[ea]",
    ]
    for pos, kw in _cerca_pattern(testo, inv_patterns):
        method = "sconosciuto"
        kw_lower = kw.lower()
        if "lifo" in kw_lower:
            method = "LIFO"
        elif "fifo" in kw_lower:
            method = "FIFO"
        elif "costo medio" in kw_lower or "media ponderata" in kw_lower:
            method = "costo_medio"

        evidenze.append(SemanticEvidence(
            evidence_type="accounting_policy",
            target_scope="document",
            normalized_hint={"voce": "rimanenze", "metodo": method},
            source_page=pagina,
            source_section="criteri_di_valutazione",
            snippet=_estrai_snippet(testo, pos),
            confidence=0.9,
        ))

    # 2. Depreciation rates
    ammort_patterns = [
        r"ammortament[oi].*?(?:\d{1,2}[,\.]\d{1,2}\s*%|\d{1,2}\s*%)",
    ]
    for pos, kw in _cerca_pattern(testo, ammort_patterns):
        # extract percentage
        pct_match = re.search(r"(\d{1,2}[,\.]\d{1,2}|\d{1,2})\s*%", kw)
        hint: dict = {"voce": "ammortamento"}
        if pct_match:
            hint["aliquota"] = pct_match.group(0)

        evidenze.append(SemanticEvidence(
            evidence_type="accounting_policy",
            target_scope="document",
            normalized_hint=hint,
            source_page=pagina,
            source_section="criteri_di_valutazione",
            snippet=_estrai_snippet(testo, pos),
            confidence=0.9,
        ))

    # 3. Bad debt provisions with percentages
    sval_patterns = [
        r"svalutazione\s+crediti.*?(?:\d{1,2}[,\.]\d{1,2}\s*%|\d{1,2}\s*%)",
    ]
    for pos, kw in _cerca_pattern(testo, sval_patterns):
        pct_match = re.search(r"(\d{1,2}[,\.]\d{1,2}|\d{1,2})\s*%", kw)
        hint2: dict = {"voce": "svalutazione_crediti"}
        if pct_match:
            hint2["percentuale"] = pct_match.group(0)

        evidenze.append(SemanticEvidence(
            evidence_type="accounting_policy",
            target_scope="document",
            normalized_hint=hint2,
            source_page=pagina,
            source_section="criteri_di_valutazione",
            snippet=_estrai_snippet(testo, pos),
            confidence=0.9,
        ))

    # If we found "criteri di valutazione" header but no specific sub-signals,
    # emit a generic evidence
    if criteri_matches and not evidenze:
        pos0 = criteri_matches[0][0]
        evidenze.append(SemanticEvidence(
            evidence_type="accounting_policy",
            target_scope="document",
            normalized_hint={"voce": "generico"},
            source_page=pagina,
            source_section="criteri_di_valutazione",
            snippet=_estrai_snippet(testo, pos0),
            confidence=0.5,
        ))

    return evidenze


# ---------------------------------------------------------------------------
# Dispatcher — maps evidence types to their extractors
# ---------------------------------------------------------------------------
_EXTRACTORS = [
    _extract_debt,
    _extract_lease,
    _extract_related_party,
    _extract_fund,
    _extract_non_recurring,
    _extract_tax,
    _extract_receivable,
    _extract_minority_interest,
    _extract_going_concern,
    _extract_accounting_policy,
]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def estrai_evidenze_deterministiche(
    testi_pagine: list[dict],   # [{"pagina": 1, "testo": "..."}]
    pagine_ni: list[int],       # 1-based page numbers of nota integrativa
) -> list[SemanticEvidence]:
    """Extract structured SemanticEvidence from nota integrativa pages.

    Parameters
    ----------
    testi_pagine : list[dict]
        Each dict has keys ``"pagina"`` (1-based int) and ``"testo"`` (str).
    pagine_ni : list[int]
        1-based page numbers belonging to the nota integrativa.  Only pages
        in this list are scanned.

    Returns
    -------
    list[SemanticEvidence]
        Deduplicated evidence items, sorted by page number then evidence type.
    """
    pagine_ni_set = set(pagine_ni)
    all_evidence: list[SemanticEvidence] = []

    for entry in testi_pagine:
        pagina = entry.get("pagina", 0)
        if pagina not in pagine_ni_set:
            continue
        testo = entry.get("testo", "")
        if not testo or not testo.strip():
            continue

        for extractor in _EXTRACTORS:
            all_evidence.extend(extractor(testo, pagina))

    # Sort by page, then evidence type
    all_evidence.sort(key=lambda e: (e.source_page or 0, e.evidence_type))

    return all_evidence
