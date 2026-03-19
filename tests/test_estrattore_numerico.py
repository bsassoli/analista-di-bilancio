"""Test per le funzioni deterministiche di agents/estrattore_numerico.py."""

import pytest

from agents.estrattore_numerico import _converti_sezione, normalizza_estrazione


# ---------------------------------------------------------------------------
# TestConvertiSezione
# ---------------------------------------------------------------------------

class TestConvertiSezione:

    def test_dettaglio_subtotale_totale(self):
        righe = [
            {"label": "Crediti verso clienti", "valori": {"2024": "2.000.000", "2023": "1.800.000"},
             "livello": "dettaglio", "genitore": "Crediti", "nota_ref": None},
            {"label": "Totale immobilizzazioni", "valori": {"2024": "3.700.000", "2023": "3.550.000"},
             "livello": "totale", "genitore": None, "nota_ref": None},
            {"label": "I - Rimanenze", "valori": {"2024": "1.200.000", "2023": "1.100.000"},
             "livello": "subtotale", "genitore": "Attivo circolante", "nota_ref": None},
        ]
        voci = _converti_sezione(righe, ["2024", "2023"])
        assert len(voci) == 3

        # Check livello mapping
        labels = {v["label"]: v["livello"] for v in voci}
        assert labels["Totale immobilizzazioni"] == 1  # totale
        assert labels["I - Rimanenze"] == 2  # subtotale
        assert labels["Crediti verso clienti"] == 3  # dettaglio

        # Check values are integers
        for v in voci:
            assert isinstance(v["valore"]["2024"], int)

    def test_di_cui_rows_skipped(self):
        righe = [
            {"label": "Crediti verso clienti", "valori": {"2024": "2.000.000"},
             "livello": "dettaglio", "genitore": "", "nota_ref": None},
            {"label": "di cui verso controllate", "valori": {"2024": "500.000"},
             "livello": "di_cui", "genitore": "Crediti verso clienti", "nota_ref": None},
        ]
        voci = _converti_sezione(righe, ["2024"])
        assert len(voci) == 1
        assert voci[0]["label"] == "Crediti verso clienti"

    def test_sezione_senza_valori_skipped(self):
        righe = [
            {"label": "B) Immobilizzazioni", "valori": {},
             "livello": "sezione", "genitore": None, "nota_ref": None},
            {"label": "Crediti", "valori": {"2024": ""},
             "livello": "sezione", "genitore": None, "nota_ref": None},
            {"label": "Totale attivo", "valori": {"2024": "8.100.000"},
             "livello": "totale", "genitore": None, "nota_ref": None},
        ]
        voci = _converti_sezione(righe, ["2024"])
        assert len(voci) == 1
        assert voci[0]["label"] == "Totale attivo"

    def test_id_dedup_with_genitore(self):
        """Duplicate labels with different genitori get disambiguated."""
        righe = [
            {"label": "esigibili entro l'esercizio", "valori": {"2024": "100.000"},
             "livello": "dettaglio", "genitore": "Crediti verso clienti", "nota_ref": None},
            {"label": "esigibili entro l'esercizio", "valori": {"2024": "200.000"},
             "livello": "dettaglio", "genitore": "Crediti tributari", "nota_ref": None},
        ]
        voci = _converti_sezione(righe, ["2024"])
        assert len(voci) == 2
        ids = [v["id"] for v in voci]
        assert ids[0] != ids[1]

    def test_variazione_significativa_yoy_flag(self):
        """Voci with >30% YoY variation get flagged."""
        righe = [
            {"label": "Rimanenze", "valori": {"2024": "2.000.000", "2023": "1.000.000"},
             "livello": "dettaglio", "genitore": "", "nota_ref": None},
        ]
        voci = _converti_sezione(righe, ["2024", "2023"])
        assert len(voci) == 1
        assert "variazione_significativa_yoy" in voci[0]["flags"]

    def test_no_flag_for_small_variation(self):
        """Voci with <30% YoY variation should NOT be flagged."""
        righe = [
            {"label": "Rimanenze", "valori": {"2024": "1.100.000", "2023": "1.000.000"},
             "livello": "dettaglio", "genitore": "", "nota_ref": None},
        ]
        voci = _converti_sezione(righe, ["2024", "2023"])
        assert "variazione_significativa_yoy" not in voci[0]["flags"]


# ---------------------------------------------------------------------------
# TestNormalizzaEstrazione
# ---------------------------------------------------------------------------

class TestNormalizzaEstrazione:

    def test_with_fixture(self, risposta_llm_estrazione):
        schema = normalizza_estrazione(risposta_llm_estrazione)

        # Verify SP and CE voci counts
        assert len(schema["sp"]) > 0
        assert len(schema["ce"]) > 0

        # Verify totale_attivo_dichiarato and totale_passivo_dichiarato
        meta = schema["metadata"]
        ta = meta["totale_attivo_dichiarato"]
        tp = meta["totale_passivo_dichiarato"]
        assert ta.get("2024") == 8_100_000
        assert ta.get("2023") == 7_400_000
        assert tp.get("2024") == 8_100_000
        assert tp.get("2023") == 7_400_000

        # Verify utile_dichiarato
        utile = meta["utile_dichiarato"]
        assert utile.get("2024") == 400_000
        assert utile.get("2023") == 350_000

        # Verify formato detected
        assert meta["formato"] == "OIC_ordinario"

        # Verify anni
        assert schema["anni_estratti"] == [2024, 2023]

    def test_sp_contains_expected_voci(self, risposta_llm_estrazione):
        schema = normalizza_estrazione(risposta_llm_estrazione)
        sp_ids = [v["id"] for v in schema["sp"]]
        # Should have totale immobilizzazioni and totale attivo
        assert any("totale_immobilizzazioni" in vid for vid in sp_ids)
        assert any("totale_attivo" in vid for vid in sp_ids)

    def test_ce_contains_expected_voci(self, risposta_llm_estrazione):
        schema = normalizza_estrazione(risposta_llm_estrazione)
        ce_ids = [v["id"] for v in schema["ce"]]
        assert any("ricavi" in vid for vid in ce_ids)
        assert any("materie_prime" in vid for vid in ce_ids)
