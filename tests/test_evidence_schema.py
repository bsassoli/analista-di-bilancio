"""Tests for tools.evidence_schema — data contracts and helpers."""

import json

from tools.evidence_schema import (
    ClassificationHint,
    DocumentProfile,
    ExtractedRow,
    ExtractionBundle,
    QualityReport,
    SemanticEvidence,
    bundle_from_dict,
    bundle_to_dict,
    evidence_for_row,
    hints_for_row,
    rows_by_section,
)


def _make_profile():
    return DocumentProfile(
        company_name="Test S.p.A.",
        years_present=["2024", "2023"],
        accounting_standard="IFRS",
        scope="consolidato",
        format_type="ordinario",
        page_map={"sp": [52, 53], "ce": [54], "nota_integrativa": [], "relazione_gestione": [], "other": []},
        n_pages=120,
    )


def _make_bundle():
    return ExtractionBundle(
        document_profile=_make_profile(),
        extracted_rows=[
            ExtractedRow(section="sp_attivo", label_raw="Immobilizzazioni", row_id="immobilizzazioni"),
            ExtractedRow(section="sp_passivo", label_raw="Patrimonio netto", row_id="patrimonio_netto"),
            ExtractedRow(section="ce", label_raw="Ricavi", row_id="ricavi"),
            ExtractedRow(section="ce", label_raw="Costi", row_id="costi"),
        ],
        semantic_evidence=[
            SemanticEvidence(
                evidence_type="lease",
                target_scope="line_item",
                related_row_ids=["immobilizzazioni"],
                snippet="IFRS 16 diritti d'uso",
            ),
            SemanticEvidence(
                evidence_type="debt",
                target_scope="document",
                snippet="Debito bancario a lungo termine",
            ),
        ],
        classification_hints=[
            ClassificationHint(
                target_row_id="immobilizzazioni",
                suggested_classification="immobilizzazioni_materiali",
            ),
        ],
    )


class TestDocumentProfile:
    def test_creation(self):
        p = _make_profile()
        assert p.company_name == "Test S.p.A."
        assert p.accounting_standard == "IFRS"
        assert p.n_pages == 120

    def test_defaults(self):
        p = DocumentProfile(
            company_name="", years_present=[], accounting_standard="unknown",
            scope="unknown", format_type="unknown", page_map={},
        )
        assert p.language == "it"
        assert p.n_pages == 0


class TestExtractedRow:
    def test_defaults(self):
        r = ExtractedRow(section="ce", label_raw="Ricavi")
        assert r.row_type == "detail"
        assert r.values_by_year == {}
        assert r.note_refs == []
        assert r.confidence == 0.9

    def test_all_fields(self):
        r = ExtractedRow(
            section="sp_attivo", label_raw="Immobilizzazioni",
            values_by_year={"2024": "1.000", "2023": "900"},
            row_type="subtotal", note_refs=["3"],
            source_page=52, extraction_method="docling",
            row_id="immobilizzazioni",
        )
        assert r.note_refs == ["3"]
        assert r.source_page == 52


class TestSemanticEvidence:
    def test_defaults(self):
        e = SemanticEvidence(evidence_type="debt", target_scope="document")
        assert e.related_row_ids == []
        assert e.confidence == 0.7


class TestBundleSerialization:
    def test_round_trip(self):
        bundle = _make_bundle()
        d = bundle_to_dict(bundle)
        assert isinstance(d, dict)
        assert d["document_profile"]["company_name"] == "Test S.p.A."

        restored = bundle_from_dict(d)
        assert restored.document_profile.company_name == "Test S.p.A."
        assert len(restored.extracted_rows) == 4
        assert len(restored.semantic_evidence) == 2
        assert len(restored.classification_hints) == 1

    def test_json_serializable(self):
        bundle = _make_bundle()
        d = bundle_to_dict(bundle)
        text = json.dumps(d, ensure_ascii=False)
        assert "Test S.p.A." in text

    def test_empty_bundle(self):
        bundle = ExtractionBundle(document_profile=_make_profile())
        d = bundle_to_dict(bundle)
        restored = bundle_from_dict(d)
        assert len(restored.extracted_rows) == 0
        assert restored.quality_report is None

    def test_with_quality_report(self):
        bundle = ExtractionBundle(
            document_profile=_make_profile(),
            quality_report=QualityReport(severity="ok", rows_with_values_pct=0.95),
        )
        d = bundle_to_dict(bundle)
        restored = bundle_from_dict(d)
        assert restored.quality_report is not None
        assert restored.quality_report.severity == "ok"


class TestHelpers:
    def test_rows_by_section(self):
        bundle = _make_bundle()
        ce_rows = rows_by_section(bundle, "ce")
        assert len(ce_rows) == 2
        assert all(r.section == "ce" for r in ce_rows)

        sp_att = rows_by_section(bundle, "sp_attivo")
        assert len(sp_att) == 1

    def test_evidence_for_row(self):
        bundle = _make_bundle()
        ev = evidence_for_row(bundle, "immobilizzazioni")
        assert len(ev) == 1
        assert ev[0].evidence_type == "lease"

        ev_none = evidence_for_row(bundle, "ricavi")
        assert len(ev_none) == 0

    def test_hints_for_row(self):
        bundle = _make_bundle()
        h = hints_for_row(bundle, "immobilizzazioni")
        assert len(h) == 1

        h_none = hints_for_row(bundle, "ricavi")
        assert len(h_none) == 0
