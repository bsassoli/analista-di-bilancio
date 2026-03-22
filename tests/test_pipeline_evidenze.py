"""Tests for evidence-aware reclassification and candidate selection."""

from agents.pipeline import (
    _riclassifica_con_evidenze,
    _riclassifica_deterministico,
    _score_candidate,
    _pick_best_candidate,
)
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

        assert (det["sp_riclassificato"]["attivo"]["capitale_fisso_netto"]["totale"]
                == evi["sp_riclassificato"]["attivo"]["capitale_fisso_netto"]["totale"])

    def test_with_hints_tracks_results(self):
        schema = _schema_minimo()
        hints = [
            ClassificationHint(
                target_row_id="debiti_verso_banche",
                suggested_classification="debiti_finanziari_lungo",
                rationale_type="note_evidence", confidence=0.9,
            ),
            ClassificationHint(
                target_row_id="fondi_rischi",
                suggested_classification="debiti_operativi",
                rationale_type="label_match", confidence=0.8,
            ),
        ]

        result = _riclassifica_con_evidenze(schema, "2024", hints)

        total = result["n_hints_rerouted"] + result["n_hints_unresolved"] + result["n_hints_confirmed"]
        assert total > 0
        assert "provenance" in result
        assert result["provenance"]["metodo"] == "deterministico+evidenze"

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
        assert evi["confidence"] >= det["confidence"]

    def test_reroute_moves_value(self):
        """A fund hint with high confidence should reroute from debiti_operativi."""
        schema = _schema_minimo()
        hints = [
            ClassificationHint(
                target_row_id="fondi_rischi",
                suggested_classification="debiti_finanziari_lungo",
                rationale_type="note_evidence", confidence=0.9,
            ),
        ]

        det = _riclassifica_deterministico(schema, "2024")
        evi = _riclassifica_con_evidenze(schema, "2024", hints)

        # fondi_rischi (500K) should have moved from debiti_operativi to debiti_finanziari_lungo
        det_fin_lungo = det["sp_riclassificato"]["passivo"]["pfn"]["dettaglio"]["debiti_finanziari_lungo"]
        evi_fin_lungo = evi["sp_riclassificato"]["passivo"]["pfn"]["dettaglio"]["debiti_finanziari_lungo"]
        assert evi_fin_lungo == det_fin_lungo + 500000

        det_deb_op = det["sp_riclassificato"]["passivo"]["debiti_operativi"]["totale"]
        evi_deb_op = evi["sp_riclassificato"]["passivo"]["debiti_operativi"]["totale"]
        assert evi_deb_op == det_deb_op - 500000
        assert evi["n_hints_rerouted"] == 1

    def test_low_confidence_hint_not_rerouted(self):
        """A hint with confidence < 0.7 should be marked unresolved, not rerouted."""
        schema = _schema_minimo()
        hints = [
            ClassificationHint(
                target_row_id="fondi_rischi",
                suggested_classification="debiti_finanziari_lungo",
                rationale_type="label_match", confidence=0.5,
            ),
        ]

        result = _riclassifica_con_evidenze(schema, "2024", hints)
        assert result["n_hints_rerouted"] == 0
        assert result["n_hints_unresolved"] == 1


class TestCandidateScoring:
    def test_valid_candidate(self):
        schema = _schema_minimo()
        risultati = {"2024": _riclassifica_deterministico(schema, "2024")}
        score = _score_candidate(risultati, ["2024"])
        # Deterministic may or may not pass quadratura
        assert "valid" in score
        assert "quad_errors" in score

    def test_empty_is_invalid(self):
        score = _score_candidate({}, ["2024"])
        assert not score["valid"]

    def test_pick_valid_over_invalid(self):
        valid = {"valid": True, "quad_errors": 0, "avg_confidence": 0.8, "n_unresolved": 0, "reasons": []}
        invalid = {"valid": False, "quad_errors": 1, "avg_confidence": 0.95, "n_unresolved": 0, "reasons": ["fail"]}
        candidates = [
            ("llm", {"2024": {}}, invalid, 100.0),
            ("det", {"2024": {}}, valid, 1.0),
        ]
        name, _ = _pick_best_candidate(candidates)
        assert name == "det"

    def test_pick_higher_confidence_among_valid(self):
        low = {"valid": True, "quad_errors": 0, "avg_confidence": 0.7, "n_unresolved": 0, "reasons": []}
        high = {"valid": True, "quad_errors": 0, "avg_confidence": 0.95, "n_unresolved": 0, "reasons": []}
        candidates = [
            ("det", {"2024": {}}, low, 1.0),
            ("llm", {"2024": {}}, high, 50.0),
        ]
        name, _ = _pick_best_candidate(candidates)
        assert name == "llm"

    def test_pick_fewer_errors_among_invalid(self):
        bad = {"valid": False, "quad_errors": 3, "avg_confidence": 0.9, "n_unresolved": 0, "reasons": ["a", "b", "c"]}
        less_bad = {"valid": False, "quad_errors": 1, "avg_confidence": 0.7, "n_unresolved": 0, "reasons": ["a"]}
        candidates = [
            ("llm", {"2024": {}}, bad, 100.0),
            ("det", {"2024": {}}, less_bad, 1.0),
        ]
        name, _ = _pick_best_candidate(candidates)
        assert name == "det"
