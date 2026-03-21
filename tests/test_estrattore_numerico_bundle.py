"""Tests for evidence-aware normalisation in estrattore_numerico."""

from agents.estrattore_numerico import normalizza_estrazione_bundle
from tools.evidence_schema import (
    ClassificationHint,
    DocumentProfile,
    ExtractedRow,
    ExtractionBundle,
    SemanticEvidence,
)


def _profile(**overrides):
    defaults = dict(
        company_name="Test S.p.A.", years_present=["2024", "2023"],
        accounting_standard="IFRS", scope="consolidato",
        format_type="ordinario",
        page_map={"sp": [52, 53], "ce": [54], "nota_integrativa": [],
                  "relazione_gestione": [], "other": []},
        n_pages=120,
    )
    defaults.update(overrides)
    return DocumentProfile(**defaults)


def _bundle_with_rows(rows, hints=None, profile=None):
    return ExtractionBundle(
        document_profile=profile or _profile(),
        extracted_rows=rows,
        classification_hints=hints or [],
    )


class TestNormalizzaEstrazioneBundle:
    def test_basic_conversion(self):
        rows = [
            ExtractedRow(section="sp_attivo", label_raw="Immobilizzazioni materiali",
                         values_by_year={"2024": "1.000.000", "2023": "900.000"},
                         row_type="detail", row_id="immobilizzazioni_materiali"),
            ExtractedRow(section="sp_attivo", label_raw="Totale attivo",
                         values_by_year={"2024": "5.000.000", "2023": "4.500.000"},
                         row_type="total", row_id="totale_attivo"),
            ExtractedRow(section="ce", label_raw="Ricavi netti",
                         values_by_year={"2024": "10.000.000", "2023": "8.000.000"},
                         row_type="detail", row_id="ricavi_netti"),
        ]

        schema = normalizza_estrazione_bundle(_bundle_with_rows(rows))

        assert schema["azienda"] == "Test S.p.A."
        assert schema["tipo_bilancio"] == "ordinario"
        assert len(schema["sp"]) == 2
        assert len(schema["ce"]) == 1
        assert schema["sp"][0]["id"] == "immobilizzazioni_materiali"
        assert schema["sp"][0]["valore"]["2024"] == 1000000

    def test_di_cui_preserved_separately(self):
        rows = [
            ExtractedRow(section="sp_attivo", label_raw="Crediti commerciali",
                         values_by_year={"2024": "3.000.000"},
                         row_type="detail", row_id="crediti_commerciali"),
            ExtractedRow(section="sp_attivo", label_raw="di cui verso controllate",
                         values_by_year={"2024": "500.000"},
                         row_type="di_cui", row_id="di_cui_verso_controllate"),
        ]

        schema = normalizza_estrazione_bundle(_bundle_with_rows(rows))

        assert len(schema["sp"]) == 1  # di_cui excluded from main
        assert len(schema["di_cui_sp"]) == 1
        assert schema["di_cui_sp"][0]["id"] == "di_cui_verso_controllate"

    def test_hints_attached_to_voce(self):
        rows = [
            ExtractedRow(section="sp_passivo", label_raw="Debiti verso banche",
                         values_by_year={"2024": "2.000.000"},
                         row_type="detail", row_id="debiti_verso_banche"),
        ]
        hints = [
            ClassificationHint(
                target_row_id="debiti_verso_banche",
                suggested_classification="debiti_finanziari_lungo",
                rationale_type="note_evidence",
                confidence=0.9,
            ),
        ]

        schema = normalizza_estrazione_bundle(_bundle_with_rows(rows, hints))

        voce = schema["sp"][0]
        assert "ha_hint_semantico" in voce["flags"]
        assert "classification_hints" in voce
        assert voce["classification_hints"][0]["target"] == "debiti_finanziari_lungo"

    def test_extraction_metadata_present(self):
        rows = [
            ExtractedRow(section="sp_attivo", label_raw="A",
                         values_by_year={"2024": "100"}, row_id="a"),
        ]
        bundle = _bundle_with_rows(rows)
        bundle.semantic_evidence = [
            SemanticEvidence(evidence_type="debt", target_scope="document"),
        ]
        bundle.unresolved_ambiguities = ["test ambiguity"]

        schema = normalizza_estrazione_bundle(bundle)

        meta = schema["extraction_metadata"]
        assert meta["n_rows_sp"] == 1
        assert meta["n_evidence"] == 1
        assert meta["n_ambiguities"] == 1

    def test_profile_metadata_used(self):
        profile = _profile(accounting_standard="OIC", scope="separato",
                           format_type="abbreviato")
        rows = [
            ExtractedRow(section="ce", label_raw="Ricavi",
                         values_by_year={"2024": "1.000"}, row_id="ricavi"),
        ]

        schema = normalizza_estrazione_bundle(_bundle_with_rows(rows, profile=profile))

        assert schema["tipo_bilancio"] == "abbreviato"
        assert schema["metadata"]["formato"] == "OIC"
        assert schema["metadata"]["scope"] == "separato"

    def test_source_page_and_method_preserved(self):
        rows = [
            ExtractedRow(section="sp_attivo", label_raw="Terreni",
                         values_by_year={"2024": "500.000"},
                         row_type="detail", row_id="terreni",
                         source_page=52, extraction_method="docling"),
        ]

        schema = normalizza_estrazione_bundle(_bundle_with_rows(rows))

        voce = schema["sp"][0]
        assert voce["source_page"] == 52
        assert voce["extraction_method"] == "docling"

    def test_totale_detection(self):
        rows = [
            ExtractedRow(section="sp_attivo", label_raw="Totale attivo",
                         values_by_year={"2024": "10.000.000"},
                         row_type="total", row_id="totale_attivo"),
            ExtractedRow(section="sp_passivo", label_raw="Totale passivo e patrimonio netto",
                         values_by_year={"2024": "10.000.000"},
                         row_type="total", row_id="totale_passivo"),
        ]

        schema = normalizza_estrazione_bundle(_bundle_with_rows(rows))

        assert schema["metadata"]["totale_attivo_dichiarato"]["2024"] == 10000000
        assert schema["metadata"]["totale_passivo_dichiarato"]["2024"] == 10000000

    def test_empty_bundle(self):
        bundle = ExtractionBundle(document_profile=_profile())
        schema = normalizza_estrazione_bundle(bundle)
        assert schema["sp"] == []
        assert schema["ce"] == []
        assert schema["di_cui_sp"] == []
