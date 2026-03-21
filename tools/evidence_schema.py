"""Typed dataclass definitions for the extraction pipeline's data contracts.

These are plain data containers with no validation logic — just structured
schemas and a few helper functions for serialization and lookup.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


# ---------------------------------------------------------------------------
# 1. DocumentProfile — document-level metadata
# ---------------------------------------------------------------------------
@dataclass
class DocumentProfile:
    company_name: str
    years_present: list[str]
    accounting_standard: str  # "OIC" | "IFRS" | "unknown"
    scope: str  # "separato" | "consolidato" | "unknown"
    format_type: str  # "ordinario" | "abbreviato" | "micro" | "unknown"
    page_map: dict[str, list[int]]  # keys: sp, ce, nota_integrativa, relazione_gestione, other
    language: str = "it"
    n_pages: int = 0


# ---------------------------------------------------------------------------
# 2. ExtractedRow — single row from a financial statement
# ---------------------------------------------------------------------------
@dataclass
class ExtractedRow:
    section: str  # "sp_attivo" | "sp_passivo" | "ce"
    label_raw: str
    label_normalized: str = ""
    values_by_year: dict[str, str] = field(default_factory=dict)
    row_type: str = "detail"  # "detail" | "subtotal" | "total" | "header" | "di_cui" | "sezione"
    parent_label: str | None = None
    note_refs: list[str] = field(default_factory=list)
    source_page: int | None = None
    extraction_method: str = "docling"  # "docling" | "pdfplumber" | "llm"
    confidence: float = 0.9
    row_id: str = ""


# ---------------------------------------------------------------------------
# 3. SemanticEvidence — structured evidence from notes/narrative
# ---------------------------------------------------------------------------
@dataclass
class SemanticEvidence:
    evidence_type: str  # "debt" | "receivable" | "payable" | "lease" | "tax" | "fund" |
                        # "related_party" | "non_recurring" | "minority_interest" |
                        # "accounting_policy" | "going_concern"
    target_scope: str  # "document" | "line_item"
    related_row_ids: list[str] = field(default_factory=list)
    years: list[str] = field(default_factory=list)
    normalized_hint: dict = field(default_factory=dict)
    source_page: int | None = None
    source_section: str = ""
    snippet: str = ""
    confidence: float = 0.7


# ---------------------------------------------------------------------------
# 4. ClassificationHint — suggestion for reclassification
# ---------------------------------------------------------------------------
@dataclass
class ClassificationHint:
    target_row_id: str = ""
    label_pattern: str = ""
    suggested_classification: str = ""  # e.g. "debiti_finanziari_lungo", "debiti_operativi"
    rationale_type: str = ""  # e.g. "note_evidence", "label_match", "maturity_split"
    evidence_ids: list[int] = field(default_factory=list)
    confidence: float = 0.7


# ---------------------------------------------------------------------------
# 5. QualityReport — extraction quality metrics
# ---------------------------------------------------------------------------
@dataclass
class QualityReport:
    page_map_confidence: float = 0.0
    rows_with_values_pct: float = 0.0
    totals_found: dict[str, bool] = field(default_factory=dict)
    quadratura_delta: dict[str, float] = field(default_factory=dict)
    section_completeness: dict[str, float] = field(default_factory=dict)
    semantic_coverage: dict[str, bool] = field(default_factory=dict)
    unresolved_count: int = 0
    note_link_coverage: float = 0.0
    severity: str = "unknown"


# ---------------------------------------------------------------------------
# 6. ExtractionBundle — top-level container
# ---------------------------------------------------------------------------
@dataclass
class ExtractionBundle:
    document_profile: DocumentProfile
    extracted_rows: list[ExtractedRow] = field(default_factory=list)
    semantic_evidence: list[SemanticEvidence] = field(default_factory=list)
    classification_hints: list[ClassificationHint] = field(default_factory=list)
    quality_report: QualityReport | None = None
    unresolved_ambiguities: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def bundle_to_dict(bundle: ExtractionBundle) -> dict:
    """Serialize an ExtractionBundle to a plain dict."""
    return asdict(bundle)


def bundle_from_dict(d: dict) -> ExtractionBundle:
    """Deserialize a dict into an ExtractionBundle."""
    profile = DocumentProfile(**d["document_profile"])
    rows = [ExtractedRow(**r) for r in d.get("extracted_rows", [])]
    evidence = [SemanticEvidence(**e) for e in d.get("semantic_evidence", [])]
    hints = [ClassificationHint(**h) for h in d.get("classification_hints", [])]
    qr_data = d.get("quality_report")
    quality_report = QualityReport(**qr_data) if qr_data is not None else None
    return ExtractionBundle(
        document_profile=profile,
        extracted_rows=rows,
        semantic_evidence=evidence,
        classification_hints=hints,
        quality_report=quality_report,
        unresolved_ambiguities=d.get("unresolved_ambiguities", []),
    )


def rows_by_section(bundle: ExtractionBundle, section: str) -> list[ExtractedRow]:
    """Return rows matching the given section (e.g. 'sp_attivo', 'ce')."""
    return [r for r in bundle.extracted_rows if r.section == section]


def evidence_for_row(bundle: ExtractionBundle, row_id: str) -> list[SemanticEvidence]:
    """Return semantic evidence entries linked to the given row_id."""
    return [e for e in bundle.semantic_evidence if row_id in e.related_row_ids]


def hints_for_row(bundle: ExtractionBundle, row_id: str) -> list[ClassificationHint]:
    """Return classification hints targeting the given row_id."""
    return [h for h in bundle.classification_hints if h.target_row_id == row_id]
