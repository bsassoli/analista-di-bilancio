"""Tests for evidence-aware reclassification in pipeline.py."""

from agents.pipeline import _riclassifica_con_evidenze, _riclassifica_deterministico
from tools.evidence_schema import ClassificationHint


def _schema_minimo():
    """Minimal schema with SP and CE voci."""
    return {
        "azienda": "Test",
        "anni_estratti": [2024],
        "tipo_bilancio": "ordinario",
        "sp": [
            {"id": "immobilizzazioni_materiali", "label": "Immobilizzazioni materiali",
             "livello": 3, "valore": {"2024": 3000000}, "flags": [], "note": ""},
            {"id": "crediti_commerciali", "label": "Crediti commerciali",
             "livello": 3, "valore": {"2024": 2000000}, "flags": [], "note": ""},
            {"id": "rimanenze", "label": "Rimanenze",
             "livello": 3, "valore": {"2024": 1500000}, "flags": [], "note": ""},
            {"id": "disponibilita_liquide", "label": "Disponibilità liquide",
             "livello": 3, "valore": {"2024": 500000}, "flags": [], "note": ""},
            {"id": "totale_attivo", "label": "Totale attivo",
             "livello": 1, "valore": {"2024": 7000000}, "flags": [], "note": ""},
            {"id": "patrimonio_netto", "label": "Patrimonio netto",
             "livello": 2, "valore": {"2024": 4000000}, "flags": [], "note": ""},
            {"id": "debiti_verso_banche", "label": "Debiti verso banche",
             "livello": 3, "valore": {"2024": 1500000}, "flags": [], "note": ""},
            {"id": "debiti_verso_fornitori", "label": "Debiti verso fornitori",
             "livello": 3, "valore": {"2024": 1000000}, "flags": [], "note": ""},
            {"id": "fondi_rischi", "label": "Fondi rischi e oneri",
             "livello": 3, "valore": {"2024": 500000}, "flags": [], "note": ""},
        ],
        "ce": [
            {"id": "ricavi", "label": "Ricavi",
             "livello": 3, "valore": {"2024": 10000000}, "flags": [], "note": ""},
        ],
        "metadata": {
            "pagine_sp": [52], "pagine_ce": [54],
            "totale_attivo_dichiarato": {"2024": 7000000},
            "totale_passivo_dichiarato": {"2024": 7000000},
            "utile_dichiarato": {},
            "formato": "IFRS",
        },
    }


class TestRiclassificaConEvidenze:
    def test_without_hints_same_as_deterministic(self):
        schema = _schema_minimo()
        det = _riclassifica_deterministico(schema, "2024")
        evi = _riclassifica_con_evidenze(schema, "2024", [])

        # Same SP totals
        assert (det["sp_riclassificato"]["attivo"]["capitale_fisso_netto"]["totale"]
                == evi["sp_riclassificato"]["attivo"]["capitale_fisso_netto"]["totale"])

    def test_with_hints_adds_deviations(self):
        schema = _schema_minimo()
        hints = [
            ClassificationHint(
                target_row_id="debiti_verso_banche",
                suggested_classification="debiti_finanziari_lungo",
                rationale_type="note_evidence",
                confidence=0.9,
            ),
            ClassificationHint(
                target_row_id="fondi_rischi",
                suggested_classification="debiti_operativi",
                rationale_type="label_match",
                confidence=0.8,
            ),
        ]

        result = _riclassifica_con_evidenze(schema, "2024", hints)

        # Should have hint deviations
        assert result["n_hints_applied"] > 0
        assert len(result["supported_buckets"]) > 0

    def test_confidence_boosted_with_evidence(self):
        schema = _schema_minimo()
        det = _riclassifica_deterministico(schema, "2024")

        hints = [
            ClassificationHint(
                target_row_id="debiti_verso_banche",
                suggested_classification="debiti_finanziari_lungo",
                rationale_type="note_evidence", confidence=0.9,
            ),
        ]
        evi = _riclassifica_con_evidenze(schema, "2024", hints)

        # Confidence should be >= deterministic
        assert evi["confidence"] >= det["confidence"]
