"""Tests for tools.quality_scorer — extraction quality scoring."""

from tools.evidence_schema import (
    DocumentProfile,
    ExtractedRow,
    ExtractionBundle,
    QualityReport,
    SemanticEvidence,
)
from tools.quality_scorer import calcola_quality_report, stampa_quality_report


def _profile(**overrides):
    defaults = dict(
        company_name="Test", years_present=["2024", "2023"],
        accounting_standard="IFRS", scope="unknown",
        format_type="ordinario",
        page_map={"sp": [52, 53], "ce": [54], "nota_integrativa": [60, 61],
                  "relazione_gestione": [], "other": []},
        n_pages=120,
    )
    defaults.update(overrides)
    return DocumentProfile(**defaults)


def _good_bundle():
    """Bundle with good extraction — should get severity ok."""
    rows = [
        ExtractedRow(section="sp_attivo", label_raw="Immobilizzazioni",
                     values_by_year={"2024": "3.000.000", "2023": "2.800.000"},
                     row_type="detail", row_id="immobilizzazioni", note_refs=["1"]),
        ExtractedRow(section="sp_attivo", label_raw="Crediti commerciali",
                     values_by_year={"2024": "2.000.000", "2023": "1.700.000"},
                     row_type="detail", row_id="crediti_comm", note_refs=["5"]),
        ExtractedRow(section="sp_attivo", label_raw="Rimanenze",
                     values_by_year={"2024": "1.500.000", "2023": "1.200.000"},
                     row_type="detail", row_id="rimanenze"),
        ExtractedRow(section="sp_attivo", label_raw="Totale attivo",
                     values_by_year={"2024": "10.000.000", "2023": "9.000.000"},
                     row_type="total", row_id="totale_attivo"),
        ExtractedRow(section="sp_passivo", label_raw="Patrimonio netto",
                     values_by_year={"2024": "5.000.000", "2023": "4.500.000"},
                     row_type="detail", row_id="pn"),
        ExtractedRow(section="sp_passivo", label_raw="Debiti verso banche",
                     values_by_year={"2024": "3.000.000", "2023": "2.500.000"},
                     row_type="detail", row_id="debiti_banche"),
        ExtractedRow(section="sp_passivo", label_raw="Debiti operativi",
                     values_by_year={"2024": "2.000.000", "2023": "2.000.000"},
                     row_type="detail", row_id="debiti_op"),
        ExtractedRow(section="sp_passivo", label_raw="Totale passivo e patrimonio netto",
                     values_by_year={"2024": "10.000.000", "2023": "9.000.000"},
                     row_type="total", row_id="totale_passivo"),
        ExtractedRow(section="ce", label_raw="Ricavi netti",
                     values_by_year={"2024": "15.000.000", "2023": "13.000.000"},
                     row_type="detail", row_id="ricavi"),
        ExtractedRow(section="ce", label_raw="Costi operativi",
                     values_by_year={"2024": "10.000.000", "2023": "9.000.000"},
                     row_type="detail", row_id="costi_op"),
        ExtractedRow(section="ce", label_raw="EBITDA",
                     values_by_year={"2024": "5.000.000", "2023": "4.000.000"},
                     row_type="subtotal", row_id="ebitda"),
        ExtractedRow(section="ce", label_raw="Ammortamenti",
                     values_by_year={"2024": "1.000.000", "2023": "900.000"},
                     row_type="detail", row_id="ammortamenti"),
        ExtractedRow(section="ce", label_raw="Imposte",
                     values_by_year={"2024": "1.500.000", "2023": "1.200.000"},
                     row_type="detail", row_id="imposte"),
        ExtractedRow(section="ce", label_raw="Risultato netto dell'esercizio",
                     values_by_year={"2024": "2.500.000", "2023": "1.900.000"},
                     row_type="total", row_id="risultato_netto"),
    ]
    evidence = [
        SemanticEvidence(evidence_type="debt", target_scope="document",
                         source_page=72, snippet="..."),
        SemanticEvidence(evidence_type="lease", target_scope="line_item",
                         source_page=80, snippet="..."),
        SemanticEvidence(evidence_type="fund", target_scope="line_item",
                         source_page=75, snippet="..."),
    ]
    return ExtractionBundle(
        document_profile=_profile(),
        extracted_rows=rows,
        semantic_evidence=evidence,
    )


class TestCalcolaQualityReport:
    def test_good_bundle_is_ok(self):
        qr = calcola_quality_report(_good_bundle())
        assert qr.severity == "ok"
        assert qr.page_map_confidence == 1.0
        assert qr.rows_with_values_pct > 0.9
        assert qr.totals_found["sp_attivo"] is True
        assert qr.totals_found["sp_passivo"] is True
        assert qr.totals_found["ce"] is True

    def test_quadratura_perfect(self):
        qr = calcola_quality_report(_good_bundle())
        assert qr.quadratura_delta.get("2024") == 0
        assert qr.quadratura_delta.get("2023") == 0

    def test_section_completeness(self):
        qr = calcola_quality_report(_good_bundle())
        assert qr.section_completeness["sp_attivo"] == 1.0
        assert qr.section_completeness["ce"] == 1.0

    def test_semantic_coverage(self):
        qr = calcola_quality_report(_good_bundle())
        assert qr.semantic_coverage["debt"] is True
        assert qr.semantic_coverage["lease"] is True
        assert qr.semantic_coverage["related_party"] is False

    def test_note_link_coverage(self):
        qr = calcola_quality_report(_good_bundle())
        # 2 out of 14 rows have note_refs
        assert 0 < qr.note_link_coverage < 1

    def test_empty_bundle_is_critical(self):
        bundle = ExtractionBundle(document_profile=_profile(
            page_map={"sp": [], "ce": [], "nota_integrativa": [],
                      "relazione_gestione": [], "other": []}
        ))
        qr = calcola_quality_report(bundle)
        assert qr.severity == "critical"

    def test_no_totals_is_critical(self):
        rows = [
            ExtractedRow(section="sp_attivo", label_raw="Crediti",
                         values_by_year={"2024": "1.000"}, row_type="detail",
                         row_id="crediti"),
        ]
        bundle = ExtractionBundle(
            document_profile=_profile(),
            extracted_rows=rows,
        )
        qr = calcola_quality_report(bundle)
        assert qr.severity == "critical"

    def test_few_rows_is_warning(self):
        """Only 1 row per section — below minimum."""
        rows = [
            ExtractedRow(section="sp_attivo", label_raw="Totale attivo",
                         values_by_year={"2024": "1.000.000"},
                         row_type="total", row_id="totale_attivo"),
            ExtractedRow(section="sp_passivo", label_raw="Totale passivo e patrimonio netto",
                         values_by_year={"2024": "1.000.000"},
                         row_type="total", row_id="totale_passivo"),
            ExtractedRow(section="ce", label_raw="Risultato netto dell'esercizio",
                         values_by_year={"2024": "100.000"},
                         row_type="total", row_id="risultato_netto"),
        ]
        bundle = ExtractionBundle(
            document_profile=_profile(),
            extracted_rows=rows,
        )
        qr = calcola_quality_report(bundle)
        assert qr.severity == "warning"


class TestStampaReport:
    def test_formats_without_error(self):
        qr = calcola_quality_report(_good_bundle())
        text = stampa_quality_report(qr)
        assert "EXTRACTION QUALITY REPORT" in text
        assert "ok" in text.lower() or "OK" in text
        assert "sp_attivo" in text
