"""Tests for tools.reconciliation — evidence linking."""

from tools.evidence_schema import (
    ClassificationHint,
    DocumentProfile,
    ExtractedRow,
    ExtractionBundle,
    SemanticEvidence,
)
from tools.reconciliation import collega_evidenze, riepilogo_linking


def _profile():
    return DocumentProfile(
        company_name="Test", years_present=["2024"],
        accounting_standard="IFRS", scope="unknown",
        format_type="ordinario", page_map={"sp": [], "ce": [],
            "nota_integrativa": [], "relazione_gestione": [], "other": []},
    )


class TestCollegaEvidenze:
    def test_debt_links_to_debiti_rows(self):
        bundle = ExtractionBundle(
            document_profile=_profile(),
            extracted_rows=[
                ExtractedRow(section="sp_passivo", label_raw="Debiti verso banche",
                             row_id="debiti_verso_banche"),
                ExtractedRow(section="sp_attivo", label_raw="Immobilizzazioni",
                             row_id="immobilizzazioni"),
            ],
            semantic_evidence=[
                SemanticEvidence(
                    evidence_type="debt", target_scope="document",
                    normalized_hint={"entro_esercizio": 5000000},
                    source_page=72, snippet="Scadenza dei debiti...",
                ),
            ],
        )

        result = collega_evidenze(bundle)
        assert len(result.classification_hints) >= 1
        hint = result.classification_hints[0]
        assert hint.target_row_id == "debiti_verso_banche"
        assert "debiti_finanziari" in hint.suggested_classification

    def test_lease_links_to_attivo_and_passivo(self):
        bundle = ExtractionBundle(
            document_profile=_profile(),
            extracted_rows=[
                ExtractedRow(section="sp_attivo", label_raw="Diritti d'uso",
                             row_id="diritti_d_uso"),
                ExtractedRow(section="sp_passivo", label_raw="Passività per leasing",
                             row_id="passivita_per_leasing"),
            ],
            semantic_evidence=[
                SemanticEvidence(
                    evidence_type="lease", target_scope="line_item",
                    source_page=80, snippet="IFRS 16 diritti d'uso...",
                    confidence=0.9,
                ),
            ],
        )

        result = collega_evidenze(bundle)
        hints_by_row = {h.target_row_id: h for h in result.classification_hints}
        assert "diritti_d_uso" in hints_by_row
        assert hints_by_row["diritti_d_uso"].suggested_classification == "immobilizzazioni_materiali_nette"
        assert "passivita_per_leasing" in hints_by_row
        assert hints_by_row["passivita_per_leasing"].suggested_classification == "debiti_finanziari_lungo"

    def test_fund_operativo_goes_to_debiti_operativi(self):
        bundle = ExtractionBundle(
            document_profile=_profile(),
            extracted_rows=[
                ExtractedRow(section="sp_passivo", label_raw="Fondi rischi e oneri",
                             row_id="fondi_rischi_e_oneri"),
            ],
            semantic_evidence=[
                SemanticEvidence(
                    evidence_type="fund", target_scope="line_item",
                    normalized_hint={"natura": "operativo"},
                    source_page=75, snippet="Fondo garanzia prodotti...",
                ),
            ],
        )

        result = collega_evidenze(bundle)
        assert len(result.classification_hints) >= 1
        assert result.classification_hints[0].suggested_classification == "debiti_operativi"

    def test_fund_finanziario_goes_to_debiti_finanziari(self):
        bundle = ExtractionBundle(
            document_profile=_profile(),
            extracted_rows=[
                ExtractedRow(section="sp_passivo", label_raw="Fondo rischi finanziari",
                             row_id="fondo_rischi_finanziari"),
            ],
            semantic_evidence=[
                SemanticEvidence(
                    evidence_type="fund", target_scope="line_item",
                    normalized_hint={"natura": "finanziario"},
                    source_page=75, snippet="Fondo derivati...",
                ),
            ],
        )

        result = collega_evidenze(bundle)
        assert result.classification_hints[0].suggested_classification == "debiti_finanziari_lungo"

    def test_no_match_creates_ambiguity(self):
        bundle = ExtractionBundle(
            document_profile=_profile(),
            extracted_rows=[
                ExtractedRow(section="sp_attivo", label_raw="Terreni",
                             row_id="terreni"),
            ],
            semantic_evidence=[
                SemanticEvidence(
                    evidence_type="debt", target_scope="document",
                    source_page=72, snippet="Scadenza dei debiti...",
                ),
            ],
        )

        result = collega_evidenze(bundle)
        assert len(result.classification_hints) == 0
        assert any("nessuna riga" in a for a in result.unresolved_ambiguities)

    def test_going_concern_not_linked(self):
        """Going concern is document-level, should not generate row hints."""
        bundle = ExtractionBundle(
            document_profile=_profile(),
            extracted_rows=[
                ExtractedRow(section="sp_attivo", label_raw="Attivo",
                             row_id="attivo"),
            ],
            semantic_evidence=[
                SemanticEvidence(
                    evidence_type="going_concern", target_scope="document",
                    source_page=10, snippet="Continuità aziendale...",
                ),
            ],
        )

        result = collega_evidenze(bundle)
        assert len(result.classification_hints) == 0

    def test_deduplicates_hints(self):
        bundle = ExtractionBundle(
            document_profile=_profile(),
            extracted_rows=[
                ExtractedRow(section="sp_passivo", label_raw="Debiti verso banche",
                             row_id="debiti_verso_banche"),
            ],
            semantic_evidence=[
                SemanticEvidence(evidence_type="debt", target_scope="document",
                                source_page=72, snippet="Debiti..."),
                SemanticEvidence(evidence_type="debt", target_scope="document",
                                source_page=73, snippet="Debiti..."),
            ],
        )

        result = collega_evidenze(bundle)
        # Should deduplicate to 1 hint for same row+classification
        row_hints = [h for h in result.classification_hints
                     if h.target_row_id == "debiti_verso_banche"]
        assert len(row_hints) == 1

    def test_empty_bundle(self):
        bundle = ExtractionBundle(document_profile=_profile())
        result = collega_evidenze(bundle)
        assert len(result.classification_hints) == 0


class TestRiepilogo:
    def test_prints_summary(self):
        bundle = ExtractionBundle(
            document_profile=_profile(),
            extracted_rows=[
                ExtractedRow(section="sp_passivo", label_raw="Debiti verso banche",
                             row_id="debiti_verso_banche"),
            ],
            semantic_evidence=[
                SemanticEvidence(evidence_type="debt", target_scope="document",
                                source_page=72, snippet="Debiti..."),
            ],
        )
        collega_evidenze(bundle)
        summary = riepilogo_linking(bundle)
        assert "Evidenze totali: 1" in summary
        assert "Hint generati:" in summary
