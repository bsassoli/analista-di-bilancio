"""Evidence linking: connect semantic evidence to extracted rows.

Takes an ExtractionBundle (with rows and semantic evidence already populated)
and produces ClassificationHints that guide the reclassification stage.

Matching methods:
  - explicit note references on rows
  - normalized label similarity
  - section-aware matching
  - evidence-type → classification-target mapping
"""
from __future__ import annotations

import re
from tools.evidence_schema import (
    ClassificationHint,
    ExtractionBundle,
    ExtractedRow,
    SemanticEvidence,
)


# ---------------------------------------------------------------------------
# Label matching helpers
# ---------------------------------------------------------------------------

def _normalizza_label(label: str) -> str:
    """Lowercase, strip accents-ish, collapse whitespace."""
    return re.sub(r"\s+", " ", label.lower().strip())


def _label_contiene(label_norm: str, keywords: list[str]) -> bool:
    """Check if normalized label contains any of the keywords."""
    return any(kw in label_norm for kw in keywords)


# ---------------------------------------------------------------------------
# Evidence-type → row matching rules
# ---------------------------------------------------------------------------

_DEBT_ROW_KEYWORDS = [
    "debiti verso banche", "debiti finanziari", "finanziamenti",
    "mutui", "obbligazioni", "prestiti", "linee di credito",
    "debiti verso istituti", "debiti bancari",
]

_LEASE_ROW_KEYWORDS = [
    "diritti d'uso", "diritti d uso", "right of use", "leasing",
    "passività per leasing", "passivita per leasing",
    "ifrs 16", "ifrs16",
]

_RELATED_PARTY_ROW_KEYWORDS = [
    "parti correlate", "correlate", "controllante", "controllat",
    "collegate", "infragruppo", "intercompany",
]

_FUND_ROW_KEYWORDS = [
    "fondi", "fondo rischi", "fondo oneri", "accantonament",
    "fondo garanzia", "fondo ristrutturazione",
]

_TAX_ROW_KEYWORDS = [
    "imposte anticipate", "imposte differite", "fiscalità differita",
    "attività per imposte", "passività per imposte",
    "crediti tributari", "debiti tributari",
]

_FACTORING_ROW_KEYWORDS = [
    "factoring", "cessione crediti", "pro soluto", "pro solvendo",
    "cartolarizzazione", "securitization",
]

_MINORITY_ROW_KEYWORDS = [
    "terzi", "minoranza", "non controlling", "interessenze",
    "quota di pertinenza", "capitale e riserve di terzi",
]

_NON_RECURRING_ROW_KEYWORDS = [
    "sopravvenienz", "plusvalenz", "minusvalenz", "svalutazione",
    "impairment", "write-off", "oneri straordinari", "proventi straordinari",
    "componenti non ricorrenti", "oneri non ricorrenti",
    "cessione", "ristrutturazione",
]


# ---------------------------------------------------------------------------
# Classification target mapping
# ---------------------------------------------------------------------------

# Maps (evidence_type, sub-signal) → suggested reclassification bucket
_CLASSIFICATION_MAP: dict[str, dict[str, str]] = {
    "debt": {
        "lungo": "debiti_finanziari_lungo",
        "breve": "debiti_finanziari_breve",
        "default": "debiti_finanziari_lungo",
    },
    "lease": {
        "attivo": "immobilizzazioni_materiali_nette",  # diritti d'uso
        "passivo": "debiti_finanziari_lungo",  # passività leasing
        "default": "immobilizzazioni_materiali_nette",
    },
    "fund": {
        "operativo": "debiti_operativi",
        "finanziario": "debiti_finanziari_lungo",
        "default": "debiti_operativi",
    },
    "tax": {
        "attivo": "altre_attivita_non_operative",
        "passivo": "debiti_operativi",
        "default": "debiti_operativi",
    },
    "receivable": {
        "pro_soluto": "crediti_commerciali",  # derecognized
        "pro_solvendo": "crediti_commerciali",  # still on balance sheet
        "default": "crediti_commerciali",
    },
    "related_party": {
        "crediti_commerciali": "crediti_commerciali",
        "crediti_finanziari": "crediti_finanziari",
        "debiti_commerciali": "debiti_operativi",
        "debiti_finanziari": "debiti_finanziari_lungo",
        "default": "debiti_operativi",
    },
    "minority_interest": {
        "default": "patrimonio_netto",
    },
    "non_recurring": {
        "provento": "proventi_oneri_straordinari",
        "onere": "proventi_oneri_straordinari",
        "default": "proventi_oneri_straordinari",
    },
}


# ---------------------------------------------------------------------------
# Core linking logic
# ---------------------------------------------------------------------------

def _trova_righe_per_keywords(
    rows: list[ExtractedRow],
    keywords: list[str],
) -> list[ExtractedRow]:
    """Find rows whose normalized label matches any keyword."""
    risultati = []
    for row in rows:
        label = _normalizza_label(row.label_raw)
        if _label_contiene(label, keywords):
            risultati.append(row)
    return risultati


def _trova_righe_per_nota(
    rows: list[ExtractedRow],
    nota_refs: list[str],
) -> list[ExtractedRow]:
    """Find rows that reference the same note numbers."""
    if not nota_refs:
        return []
    nota_set = set(nota_refs)
    return [r for r in rows if nota_set.intersection(r.note_refs)]


def _genera_hint_da_evidenza(
    evidence: SemanticEvidence,
    evidence_idx: int,
    matching_rows: list[ExtractedRow],
    sub_signal: str = "default",
) -> list[ClassificationHint]:
    """Generate ClassificationHints from an evidence + matched rows."""
    hints = []
    ev_type = evidence.evidence_type
    class_map = _CLASSIFICATION_MAP.get(ev_type, {})
    suggested = class_map.get(sub_signal, class_map.get("default", ""))

    if not suggested:
        return hints

    for row in matching_rows:
        if not row.row_id:
            continue
        hints.append(ClassificationHint(
            target_row_id=row.row_id,
            label_pattern=_normalizza_label(row.label_raw),
            suggested_classification=suggested,
            rationale_type="note_evidence" if row.note_refs else "label_match",
            evidence_ids=[evidence_idx],
            confidence=min(evidence.confidence, 0.9),
        ))

    return hints


def _determina_sub_signal(evidence: SemanticEvidence, row: ExtractedRow) -> str:
    """Determine the sub-signal based on evidence hint + row section."""
    hint = evidence.normalized_hint
    ev_type = evidence.evidence_type

    if ev_type == "fund":
        return hint.get("natura", "default")

    if ev_type == "lease":
        if row.section in ("sp_attivo",):
            return "attivo"
        elif row.section in ("sp_passivo",):
            return "passivo"

    if ev_type == "tax":
        label = _normalizza_label(row.label_raw)
        if "anticipat" in label or "attività" in label or "crediti" in label:
            return "attivo"
        elif "differit" in label or "passività" in label or "debiti" in label:
            return "passivo"

    if ev_type == "debt":
        hint_data = evidence.normalized_hint
        if hint_data.get("oltre_5_anni") or hint_data.get("oltre_esercizio_entro_5"):
            return "lungo"
        if hint_data.get("entro_esercizio"):
            return "breve"

    if ev_type == "receivable":
        return hint.get("tipo", "default")

    return "default"


# ---------------------------------------------------------------------------
# Keyword map per evidence type
# ---------------------------------------------------------------------------

_EVIDENCE_KEYWORDS: dict[str, list[str]] = {
    "debt": _DEBT_ROW_KEYWORDS,
    "lease": _LEASE_ROW_KEYWORDS,
    "related_party": _RELATED_PARTY_ROW_KEYWORDS,
    "fund": _FUND_ROW_KEYWORDS,
    "tax": _TAX_ROW_KEYWORDS,
    "receivable": _FACTORING_ROW_KEYWORDS,
    "minority_interest": _MINORITY_ROW_KEYWORDS,
    "non_recurring": _NON_RECURRING_ROW_KEYWORDS,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collega_evidenze(bundle: ExtractionBundle) -> ExtractionBundle:
    """Link semantic evidence to extracted rows and produce hints.

    Modifies the bundle in place: populates classification_hints and
    updates semantic_evidence related_row_ids.

    Returns the same bundle for chaining.
    """
    rows = bundle.extracted_rows
    hints: list[ClassificationHint] = []
    ambiguities: list[str] = []

    for ev_idx, evidence in enumerate(bundle.semantic_evidence):
        ev_type = evidence.evidence_type

        # Skip document-level evidence without row-linking potential
        if ev_type in ("going_concern", "accounting_policy"):
            continue

        # Strategy 1: match by note reference
        # Extract note refs from the evidence snippet
        nota_refs_in_snippet = re.findall(r"nota\s+(\d+)", evidence.snippet, re.IGNORECASE)
        matched_by_note = _trova_righe_per_nota(rows, nota_refs_in_snippet)

        # Strategy 2: match by keyword
        keywords = _EVIDENCE_KEYWORDS.get(ev_type, [])
        matched_by_keyword = _trova_righe_per_keywords(rows, keywords)

        # Merge, prioritizing note matches
        all_matched = {r.row_id: r for r in matched_by_note}
        for r in matched_by_keyword:
            if r.row_id not in all_matched:
                all_matched[r.row_id] = r

        if not all_matched:
            ambiguities.append(
                f"[{ev_type}] p.{evidence.source_page}: nessuna riga corrispondente trovata"
            )
            continue

        # Update evidence with linked row IDs
        evidence.related_row_ids = list(all_matched.keys())

        # Generate hints for each matched row
        for row in all_matched.values():
            sub = _determina_sub_signal(evidence, row)
            row_hints = _genera_hint_da_evidenza(evidence, ev_idx, [row], sub)
            hints.extend(row_hints)

    # Deduplicate hints by (target_row_id, suggested_classification)
    seen: set[tuple[str, str]] = set()
    unique_hints = []
    for h in hints:
        key = (h.target_row_id, h.suggested_classification)
        if key not in seen:
            seen.add(key)
            unique_hints.append(h)

    bundle.classification_hints = unique_hints
    bundle.unresolved_ambiguities.extend(ambiguities)
    return bundle


def riepilogo_linking(bundle: ExtractionBundle) -> str:
    """Print a summary of the evidence linking results."""
    lines = []
    lines.append(f"Evidenze totali: {len(bundle.semantic_evidence)}")
    linked = sum(1 for e in bundle.semantic_evidence if e.related_row_ids)
    lines.append(f"Evidenze collegate a righe: {linked}")
    lines.append(f"Hint generati: {len(bundle.classification_hints)}")
    lines.append(f"Ambiguità irrisolte: {len(bundle.unresolved_ambiguities)}")

    if bundle.classification_hints:
        lines.append("\nHint per tipo:")
        by_class: dict[str, int] = {}
        for h in bundle.classification_hints:
            by_class[h.suggested_classification] = by_class.get(h.suggested_classification, 0) + 1
        for cls, count in sorted(by_class.items()):
            lines.append(f"  {cls}: {count}")

    return "\n".join(lines)
