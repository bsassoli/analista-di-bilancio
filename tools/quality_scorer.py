"""Extraction quality scoring — measures quality before reclassification.

Takes an ExtractionBundle and produces a QualityReport that acts as
the real gate before reclassification. Deterministic, no LLM calls.

Severity drivers:
  critical — statement pages not found, totals missing, parse failure
  warning  — weak note linkage, missing semantic coverage, ambiguous rows
  ok       — everything looks good
"""
from __future__ import annotations

from tools.pdf_parser import normalizza_numero
from tools.evidence_schema import (
    ExtractionBundle,
    ExtractedRow,
    QualityReport,
)


# Evidence types we consider "high value"
_HIGH_VALUE_EVIDENCE = {"debt", "lease", "fund", "related_party", "tax"}

# Minimum rows expected per section
_MIN_ROWS = {"sp_attivo": 3, "sp_passivo": 3, "ce": 5}


# ---------------------------------------------------------------------------
# Individual scorers
# ---------------------------------------------------------------------------

def _score_page_map(bundle: ExtractionBundle) -> float:
    """Score page map completeness (0-1)."""
    pm = bundle.document_profile.page_map
    found = 0
    total = 3  # sp, ce, nota_integrativa
    if pm.get("sp"):
        found += 1
    if pm.get("ce"):
        found += 1
    if pm.get("nota_integrativa"):
        found += 1
    return found / total


def _score_rows_with_values(bundle: ExtractionBundle) -> float:
    """Fraction of rows that have at least one parsed numeric value."""
    rows = bundle.extracted_rows
    if not rows:
        return 0.0
    anni = bundle.document_profile.years_present

    n_with_values = 0
    for row in rows:
        if row.row_type in ("header", "sezione"):
            continue
        for anno in anni:
            val_raw = row.values_by_year.get(anno, "")
            if val_raw and normalizza_numero(str(val_raw)) is not None:
                n_with_values += 1
                break

    countable = sum(1 for r in rows if r.row_type not in ("header", "sezione"))
    return n_with_values / max(countable, 1)


def _find_totals(bundle: ExtractionBundle) -> dict[str, bool]:
    """Check if key totals are present in extracted rows."""
    found = {"sp_attivo": False, "sp_passivo": False, "ce": False}

    for row in bundle.extracted_rows:
        if row.row_type != "total":
            continue
        label = row.label_raw.lower()
        if row.section == "sp_attivo" and ("totale attivo" in label or "totale attivit" in label):
            found["sp_attivo"] = True
        elif row.section == "sp_passivo" and ("totale passivo" in label or "totale patrimonio" in label):
            found["sp_passivo"] = True
        elif row.section == "ce" and ("risultato netto" in label or ("utile" in label and "esercizio" in label)):
            found["ce"] = True

    return found


def _check_quadratura(bundle: ExtractionBundle) -> dict[str, float]:
    """Check SP balance per year. Returns {year: delta_amount}."""
    anni = bundle.document_profile.years_present
    deltas: dict[str, float] = {}

    for anno in anni:
        totale_attivo = None
        totale_passivo = None

        for row in bundle.extracted_rows:
            if row.row_type != "total":
                continue
            label = row.label_raw.lower()
            val = normalizza_numero(str(row.values_by_year.get(anno, "")))

            if row.section == "sp_attivo" and ("totale attivo" in label or "totale attivit" in label):
                if val is not None:
                    totale_attivo = val
            elif row.section == "sp_passivo" and ("totale passivo" in label or "totale patrimonio" in label):
                if val is not None:
                    totale_passivo = val

        if totale_attivo is not None and totale_passivo is not None:
            deltas[anno] = abs(totale_attivo - totale_passivo)
        elif totale_attivo is None and totale_passivo is None:
            deltas[anno] = -1  # both missing
        else:
            deltas[anno] = -2  # one missing

    return deltas


def _score_section_completeness(bundle: ExtractionBundle) -> dict[str, float]:
    """Score each section by row count vs minimum expected."""
    counts: dict[str, int] = {"sp_attivo": 0, "sp_passivo": 0, "ce": 0}
    for row in bundle.extracted_rows:
        if row.section in counts and row.row_type not in ("header", "sezione"):
            counts[row.section] += 1

    scores: dict[str, float] = {}
    for section, minimum in _MIN_ROWS.items():
        actual = counts.get(section, 0)
        scores[section] = min(actual / maximum, 1.0) if (maximum := max(minimum, 1)) else 0.0

    return scores


def _score_semantic_coverage(bundle: ExtractionBundle) -> dict[str, bool]:
    """Check which high-value evidence types were found."""
    found_types = {e.evidence_type for e in bundle.semantic_evidence}
    return {t: t in found_types for t in sorted(_HIGH_VALUE_EVIDENCE)}


def _score_note_link_coverage(bundle: ExtractionBundle) -> float:
    """Fraction of non-header rows that have at least one note reference."""
    rows = [r for r in bundle.extracted_rows if r.row_type not in ("header", "sezione")]
    if not rows:
        return 0.0
    with_notes = sum(1 for r in rows if r.note_refs)
    return with_notes / len(rows)


# ---------------------------------------------------------------------------
# Severity determination
# ---------------------------------------------------------------------------

def _determine_severity(
    page_map_conf: float,
    rows_pct: float,
    totals: dict[str, bool],
    deltas: dict[str, float],
    section_scores: dict[str, float],
    semantic_cov: dict[str, bool],
    note_link: float,
    unresolved: int,
) -> str:
    """Determine overall severity from individual scores.

    Critical (pipeline should stop):
      - statement pages not found (page_map < 34%)
      - no totals found at all
      - most rows unparseable (< 30%)
      - quadratura delta > 5% of totale attivo

    Warning (proceed with reduced confidence):
      - rows with values < 70%
      - section completeness < 50% for any section
      - semantic coverage missing on >= 3 high-value topics
      - note link coverage < 10%
      - unresolved ambiguities > 5
      - quadratura delta > 0 but <= 5%

    Ok:
      - everything else
    """
    # --- Critical conditions ---
    if page_map_conf < 0.34:
        return "critical"
    if not any(totals.values()):
        return "critical"
    if rows_pct < 0.3:
        return "critical"

    # Quadratura: critical if delta > 5% of total
    for anno, delta in deltas.items():
        if delta == -1:
            return "critical"  # both totals missing
        if delta == -2:
            continue  # one total missing — warning, not critical
        if delta > 0 and totals.get("sp_attivo") and totals.get("sp_passivo"):
            return "critical"  # any non-zero delta is critical at extraction stage

    # --- Warning conditions ---
    warnings = 0

    if rows_pct < 0.7:
        warnings += 1
    if any(s < 0.5 for s in section_scores.values()):
        warnings += 1

    # Semantic coverage: warn if >= 3 high-value types missing
    n_missing_semantic = sum(1 for v in semantic_cov.values() if not v)
    if n_missing_semantic >= 3:
        warnings += 1

    # Note link coverage: warn if very low
    if note_link < 0.1:
        warnings += 1

    # Unresolved ambiguities
    if unresolved > 5:
        warnings += 1

    # One missing total
    for anno, delta in deltas.items():
        if delta == -2:
            warnings += 1
            break

    if warnings > 0:
        return "warning"

    return "ok"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calcola_quality_report(bundle: ExtractionBundle) -> QualityReport:
    """Compute extraction quality metrics for the bundle.

    This is deterministic and should run after extraction + semantic
    + linking, before reclassification.

    Args:
        bundle: ExtractionBundle with rows, evidence, hints populated.

    Returns:
        QualityReport with all metrics filled.
    """
    page_map_conf = _score_page_map(bundle)
    rows_pct = _score_rows_with_values(bundle)
    totals = _find_totals(bundle)
    deltas = _check_quadratura(bundle)
    section_scores = _score_section_completeness(bundle)
    semantic_cov = _score_semantic_coverage(bundle)
    note_link = _score_note_link_coverage(bundle)
    unresolved = len(bundle.unresolved_ambiguities)

    severity = _determine_severity(
        page_map_conf, rows_pct, totals, deltas, section_scores,
        semantic_cov, note_link, unresolved,
    )

    return QualityReport(
        page_map_confidence=round(page_map_conf, 2),
        rows_with_values_pct=round(rows_pct, 2),
        totals_found=totals,
        quadratura_delta=deltas,
        section_completeness=section_scores,
        semantic_coverage=semantic_cov,
        unresolved_count=unresolved,
        note_link_coverage=round(note_link, 2),
        severity=severity,
    )


def stampa_quality_report(qr: QualityReport) -> str:
    """Format quality report as readable string."""
    lines = [
        "=" * 60,
        "  EXTRACTION QUALITY REPORT",
        "=" * 60,
        f"  Severity: {qr.severity.upper()}",
        f"  Page map confidence: {qr.page_map_confidence:.0%}",
        f"  Rows with values: {qr.rows_with_values_pct:.0%}",
        f"  Note link coverage: {qr.note_link_coverage:.0%}",
        f"  Unresolved ambiguities: {qr.unresolved_count}",
        "",
        "  Totals found:",
    ]
    for section, found in qr.totals_found.items():
        marker = "OK" if found else "MISSING"
        lines.append(f"    {section}: {marker}")

    lines.append("")
    lines.append("  Quadratura (delta per anno):")
    for anno, delta in sorted(qr.quadratura_delta.items()):
        if delta < 0:
            lines.append(f"    {anno}: totali mancanti")
        elif delta == 0:
            lines.append(f"    {anno}: perfetta")
        else:
            lines.append(f"    {anno}: delta {delta:,.0f}")

    lines.append("")
    lines.append("  Section completeness:")
    for section, score in qr.section_completeness.items():
        lines.append(f"    {section}: {score:.0%}")

    lines.append("")
    lines.append("  Semantic coverage:")
    for ev_type, found in qr.semantic_coverage.items():
        marker = "found" if found else "missing"
        lines.append(f"    {ev_type}: {marker}")

    return "\n".join(lines)
