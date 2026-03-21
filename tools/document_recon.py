"""Deterministic page classification and document reconnaissance.

Scans every page of a PDF with pdfplumber and produces a DocumentProfile
without any LLM call.  The profile includes:
  - page-level classification (SP, CE, nota integrativa, relazione gestione,
    rendiconto finanziario, other)
  - accounting standard detection (IFRS vs OIC)
  - scope detection (consolidato vs separato)
  - format type (ordinario, abbreviato, micro)
  - years present in statement pages
  - company name (best-effort, from first pages)

This module is meant to run *before* any extraction step so that downstream
agents already know which pages to look at.
"""

import re
from pathlib import Path
from typing import Optional

import pdfplumber

from tools.evidence_schema import DocumentProfile


# ---------------------------------------------------------------------------
# Keyword lists
# ---------------------------------------------------------------------------

_KW_SP = [
    "stato patrimoniale",
    "totale attivo",
    "totale attività",
    "totale passivo",
    "patrimonio netto e passività",
    "attività non correnti",
    "attività correnti",
    "passività non correnti",
    "passività correnti",
    "immobilizzazioni",
    "attivo circolante",
]

_KW_CE = [
    "conto economico",
    "valore della produzione",
    "costi della produzione",
    "risultato operativo",
    "risultato netto",
    "ricavi",
    "risultato prima delle imposte",
    "utile dell'esercizio",
    "risultato d'esercizio",
]

_KW_NI = [
    "nota integrativa",
    "criteri di valutazione",
    "principi contabili",
    "immobilizzazioni materiali",
    "crediti verso",
    "debiti verso",
    "composizione",
]

_KW_RELAZIONE = [
    "relazione sulla gestione",
    "andamento della gestione",
    "fatti di rilievo",
    "evoluzione prevedibile",
    "rischi e incertezze",
]

_KW_RENDICONTO = [
    "rendiconto finanziario",
    "flusso di cassa",
    "cash flow",
    "flussi finanziari",
    "disponibilità liquide",
]

_KW_IFRS = [
    "attività non correnti",
    "attività correnti",
    "passività non correnti",
    "ifrs",
    "ias ",
]

_KW_OIC = [
    "valore della produzione",
    "costi della produzione",
    "a) crediti verso soci",
    "immobilizzazioni",
]

_KW_CONSOLIDATO = [
    "consolidato",
    "bilancio consolidato",
    "gruppo",
]

_KW_SEPARATO = [
    "bilancio d'esercizio",
    "bilancio separato",
]

# Threshold: a page with numeric_density above this is considered "high"
_HIGH_NUMERIC_DENSITY = 0.15
# A page with more chars than this is considered "long text"
_LONG_TEXT_THRESHOLD = 800

# Regex for number-like tokens
_RE_NUMBER = re.compile(r"\d[\d.,]*\d|\d")
# Regex for fiscal years — require context to avoid matching page numbers.
# Matches: "31.12.2024", "31 dicembre 2024", "esercizio 2024", "anno 2024",
#           "2024" when preceded by date-like context or column headers.
_RE_YEAR_CONTEXTUAL = re.compile(
    r"(?:"
    r"\d{1,2}[./]\d{1,2}[./](20[0-3]\d)"  # 31.12.2024, 31/12/2024
    r"|(?:dicembre|gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre)\s+(20[0-3]\d)"
    r"|(?:esercizio|anno|bilancio)\s+(?:al\s+)?(20[0-3]\d)"
    r")",
    re.IGNORECASE,
)
# Fallback: bare 4-digit year, used only on statement pages with high numeric density
_RE_YEAR_BARE = re.compile(r"\b(20[12]\d)\b")
# Regex for tab/multi-space aligned columns (at least two groups of spaces)
_RE_ALIGNED = re.compile(r"\S+\s{2,}\S+\s{2,}\S+")


# ---------------------------------------------------------------------------
# Helper: text extraction
# ---------------------------------------------------------------------------

def _estrai_testo_pagine(pdf_path: str) -> list[str]:
    """Extract text from every page using pdfplumber.

    Returns a list where index ``i`` holds the text of page ``i+1``
    (0-based index, 1-based page number).
    """
    testi: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            testi.append(page.extract_text() or "")
    return testi


# ---------------------------------------------------------------------------
# Helper: per-page scoring
# ---------------------------------------------------------------------------

def _keyword_score(testo_lower: str, keywords: list[str]) -> int:
    """Count how many keywords appear in *testo_lower*."""
    return sum(1 for kw in keywords if kw in testo_lower)


def _punteggio_pagina(testo: str) -> dict:
    """Compute classification scores for a single page.

    Returns a dict with keys:
      numeric_density, table_likeness,
      sp_score, ce_score, ni_score, relazione_score, rendiconto_score
    """
    if not testo or not testo.strip():
        return {
            "numeric_density": 0.0,
            "table_likeness": 0,
            "sp_score": 0,
            "ce_score": 0,
            "ni_score": 0,
            "relazione_score": 0,
            "rendiconto_score": 0,
        }

    tokens = testo.split()
    n_tokens = max(len(tokens), 1)
    n_numeric = sum(1 for t in tokens if _RE_NUMBER.fullmatch(t))
    numeric_density = n_numeric / n_tokens

    lines = testo.strip().split("\n")
    table_likeness = sum(1 for ln in lines if _RE_ALIGNED.search(ln))

    testo_lower = testo.lower()

    sp_score = _keyword_score(testo_lower, _KW_SP)
    ce_score = _keyword_score(testo_lower, _KW_CE)
    ni_score = _keyword_score(testo_lower, _KW_NI)
    relazione_score = _keyword_score(testo_lower, _KW_RELAZIONE)
    rendiconto_score = _keyword_score(testo_lower, _KW_RENDICONTO)

    return {
        "numeric_density": numeric_density,
        "table_likeness": table_likeness,
        "sp_score": sp_score,
        "ce_score": ce_score,
        "ni_score": ni_score,
        "relazione_score": relazione_score,
        "rendiconto_score": rendiconto_score,
    }


# ---------------------------------------------------------------------------
# Helper: year detection
# ---------------------------------------------------------------------------

def _rileva_anni(testi: list[str], pagine_statement: list[int]) -> list[str]:
    """Detect fiscal years mentioned on statement pages.

    Uses contextual regex first (date patterns, "esercizio 2024" etc.)
    to avoid picking up page numbers.  Falls back to bare 4-digit years
    on statement pages only.

    Args:
        testi: full list of page texts (0-based index).
        pagine_statement: 1-based page numbers of SP/CE pages.

    Returns:
        Sorted list of unique year strings (e.g. ["2023", "2024"]).
    """
    anni: set[str] = set()

    # Pass 1: contextual patterns across all provided pages
    for pag in pagine_statement:
        idx = pag - 1
        if 0 <= idx < len(testi):
            for m in _RE_YEAR_CONTEXTUAL.finditer(testi[idx]):
                # The year may be in group 1, 2, or 3 depending on which branch matched
                for g in m.groups():
                    if g and len(g) == 4:
                        anni.add(g)

    # Pass 2: if contextual didn't find enough, try bare years on statement pages
    if len(anni) < 2:
        for pag in pagine_statement:
            idx = pag - 1
            if 0 <= idx < len(testi):
                for m in _RE_YEAR_BARE.finditer(testi[idx]):
                    anni.add(m.group(1))

    return sorted(anni)


# ---------------------------------------------------------------------------
# Helper: company name extraction
# ---------------------------------------------------------------------------

def _rileva_nome_azienda(testi: list[str], max_pages: int = 3) -> str:
    """Best-effort company name detection from the first pages.

    Heuristic: look for patterns like "NOME S.p.A.", "NOME S.r.l.",
    "NOME S.p.A. a socio unico", etc. in the first few pages.
    """
    pattern = re.compile(
        r"([A-ZÀ-Ú][A-Za-zÀ-ú0-9 &'.,-]{2,50}"
        r"\s+(?:S\.p\.A\.|S\.r\.l\.|S\.r\.l\.s\.|S\.a\.s\.|S\.n\.c\.|S\.c\.a\.r\.l\.|"
        r"s\.p\.a\.|s\.r\.l\.)(?:\s+[a-z ]*)?)",
        re.UNICODE,
    )
    for i in range(min(max_pages, len(testi))):
        m = pattern.search(testi[i])
        if m:
            return m.group(0).strip()
    return ""


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def classifica_pagine(pdf_path: str) -> DocumentProfile:
    """Classify every page of a PDF and return a DocumentProfile.

    This is fully deterministic — no LLM calls.  Uses pdfplumber for text
    extraction and keyword/numeric heuristics for classification.

    Args:
        pdf_path: path to a PDF file.

    Returns:
        A ``DocumentProfile`` dataclass (from ``tools.evidence_schema``).
    """
    pdf_path = str(Path(pdf_path).resolve())
    testi = _estrai_testo_pagine(pdf_path)
    n_pages = len(testi)

    # ------------------------------------------------------------------
    # 1. Score every page
    # ------------------------------------------------------------------
    scores = [_punteggio_pagina(t) for t in testi]

    # ------------------------------------------------------------------
    # 2. Classify pages
    # ------------------------------------------------------------------
    page_map: dict[str, list[int]] = {
        "sp": [],
        "ce": [],
        "nota_integrativa": [],
        "relazione_gestione": [],
        "rendiconto_finanziario": [],
        "other": [],
    }

    for idx, (sc, txt) in enumerate(zip(scores, testi)):
        pag_1based = idx + 1
        nd = sc["numeric_density"]
        tl = sc["table_likeness"]
        # A page is "high numeric" if density is above threshold.
        # table_likeness is a bonus signal but not required — pdfplumber
        # often extracts table text without preserving column alignment.
        high_numeric = nd >= _HIGH_NUMERIC_DENSITY
        text_len = len(txt.strip())

        # Rendiconto finanziario (check first — some keywords overlap with CE)
        if sc["rendiconto_score"] >= 2 and high_numeric:
            page_map["rendiconto_finanziario"].append(pag_1based)
            continue

        # SP: high numeric + SP keywords
        if high_numeric and sc["sp_score"] >= 2:
            page_map["sp"].append(pag_1based)
            continue

        # CE: high numeric + CE keywords, but NOT rendiconto
        if high_numeric and sc["ce_score"] >= 2 and sc["rendiconto_score"] < 2:
            page_map["ce"].append(pag_1based)
            continue

        # Slightly relaxed: single keyword match but very high numeric density
        if nd >= 0.25 and tl >= 3:
            if sc["sp_score"] >= 1 and sc["ce_score"] == 0:
                page_map["sp"].append(pag_1based)
                continue
            if sc["ce_score"] >= 1 and sc["sp_score"] == 0 and sc["rendiconto_score"] < 2:
                page_map["ce"].append(pag_1based)
                continue
            if sc["rendiconto_score"] >= 1:
                page_map["rendiconto_finanziario"].append(pag_1based)
                continue

        # Relazione sulla gestione: low numeric, relazione keywords
        if sc["relazione_score"] >= 1 and nd < _HIGH_NUMERIC_DENSITY:
            page_map["relazione_gestione"].append(pag_1based)
            continue

        # Nota integrativa: low numeric density, long text, NI keywords
        # For NI we accept pages with some numbers (tables inside prose)
        if sc["ni_score"] >= 1 and text_len >= _LONG_TEXT_THRESHOLD and nd < 0.30:
            page_map["nota_integrativa"].append(pag_1based)
            continue

        # Nota integrativa — weaker signal: long prose page after we already
        # found an NI start (contiguous block heuristic handled below)
        page_map["other"].append(pag_1based)

    # ------------------------------------------------------------------
    # 2b. Expand nota integrativa as a contiguous block
    # ------------------------------------------------------------------
    # The NI is typically one continuous section from its first page to the
    # end of the document (minus pages already classified as statements).
    if page_map["nota_integrativa"]:
        ni_start = min(page_map["nota_integrativa"])
        classified_elsewhere = set(
            page_map["sp"]
            + page_map["ce"]
            + page_map["rendiconto_finanziario"]
            + page_map["relazione_gestione"]
        )
        expanded_ni: list[int] = []
        for pag in range(ni_start, n_pages + 1):
            if pag in classified_elsewhere:
                continue
            # Skip pages that are clearly numeric statement pages
            idx = pag - 1
            if idx < len(scores) and scores[idx]["numeric_density"] >= 0.35 and scores[idx]["table_likeness"] >= 5:
                continue
            expanded_ni.append(pag)

        page_map["nota_integrativa"] = sorted(set(expanded_ni))
        # Remove NI pages from "other"
        ni_set = set(page_map["nota_integrativa"])
        page_map["other"] = [p for p in page_map["other"] if p not in ni_set]

    # ------------------------------------------------------------------
    # 3. Detect accounting standard
    # ------------------------------------------------------------------
    segnali_ifrs = 0
    segnali_oic = 0
    for txt in testi:
        tl = txt.lower()
        segnali_ifrs += sum(1 for kw in _KW_IFRS if kw in tl)
        segnali_oic += sum(1 for kw in _KW_OIC if kw in tl)

    if segnali_ifrs > segnali_oic:
        accounting_standard = "IFRS"
    elif segnali_oic > 0:
        accounting_standard = "OIC"
    else:
        accounting_standard = "unknown"

    # ------------------------------------------------------------------
    # 4. Detect scope
    # ------------------------------------------------------------------
    segnali_cons = 0
    segnali_sep = 0
    for txt in testi:
        tl = txt.lower()
        segnali_cons += sum(1 for kw in _KW_CONSOLIDATO if kw in tl)
        segnali_sep += sum(1 for kw in _KW_SEPARATO if kw in tl)

    if segnali_cons > segnali_sep:
        scope = "consolidato"
    elif segnali_sep > 0:
        scope = "separato"
    else:
        scope = "unknown"

    # ------------------------------------------------------------------
    # 5. Detect format type
    # ------------------------------------------------------------------
    format_type = "ordinario"  # default
    full_text_lower = " ".join(t.lower() for t in testi)
    if "bilancio micro" in full_text_lower or "micro-imprese" in full_text_lower:
        format_type = "micro"
    elif "bilancio abbreviato" in full_text_lower or "forma abbreviata" in full_text_lower:
        format_type = "abbreviato"

    # ------------------------------------------------------------------
    # 6. Detect years from statement pages
    # ------------------------------------------------------------------
    statement_pages = page_map["sp"] + page_map["ce"]
    years_present = _rileva_anni(testi, statement_pages)

    # Fallback: if no years found on statement pages, scan all pages
    if not years_present:
        years_present = _rileva_anni(testi, list(range(1, n_pages + 1)))
        # Keep only the two most recent to avoid noise
        if len(years_present) > 2:
            years_present = years_present[-2:]

    # ------------------------------------------------------------------
    # 7. Extract company name
    # ------------------------------------------------------------------
    company_name = _rileva_nome_azienda(testi)

    # ------------------------------------------------------------------
    # 8. Build and return DocumentProfile
    # ------------------------------------------------------------------
    return DocumentProfile(
        company_name=company_name,
        years_present=years_present,
        accounting_standard=accounting_standard,
        scope=scope,
        format_type=format_type,
        page_map=page_map,
        n_pages=n_pages,
    )
