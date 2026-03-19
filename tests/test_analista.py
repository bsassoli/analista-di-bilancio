"""Test per le funzioni deterministiche di agents/analista.py."""

import pytest

from agents.analista import (
    _estrai_valori_anno,
    _calcola_indici_anno,
    _calcola_trend,
    _genera_alert,
    _genera_narrative_template,
    SOGLIE,
)


# ---------------------------------------------------------------------------
# TestEstraiValoriAnno
# ---------------------------------------------------------------------------

class TestEstraiValoriAnno:

    def test_extract_2024(self, pipeline_result):
        risultato_2024 = pipeline_result["riclassifica"]["risultati_per_anno"]["2024"]
        valori = _estrai_valori_anno(risultato_2024)

        assert valori["ricavi_netti"] == 12_200_000
        assert valori["ebitda"] == 1_700_000
        assert valori["patrimonio_netto"] == 2_400_000
        assert valori["pfn"] == 1_200_000  # 1_500_000 + 500_000 - 800_000
        assert valori["utile_netto"] == 400_000
        assert valori["crediti_commerciali"] == 2_000_000
        assert valori["rimanenze"] == 1_200_000
        assert valori["liquidita"] == 800_000
        assert valori["ebit"] == 900_000

    def test_extract_2023(self, pipeline_result):
        risultato_2023 = pipeline_result["riclassifica"]["risultati_per_anno"]["2023"]
        valori = _estrai_valori_anno(risultato_2023)

        assert valori["ricavi_netti"] == 11_150_000
        assert valori["ebitda"] == 1_550_000
        assert valori["patrimonio_netto"] == 2_150_000
        assert valori["utile_netto"] == 350_000


# ---------------------------------------------------------------------------
# TestCalcolaIndiciAnno
# ---------------------------------------------------------------------------

class TestCalcolaIndiciAnno:

    def test_known_inputs(self):
        v = {
            "ricavi_netti": 10_000_000,
            "ebitda": 2_000_000,
            "ebit": 1_000_000,
            "ebt": 800_000,
            "utile_netto": 500_000,
            "ammortamenti": 1_000_000,
            "costi_personale": 2_000_000,
            "valore_aggiunto": 5_000_000,
            "patrimonio_netto": 3_000_000,
            "pfn": 1_500_000,
            "debiti_operativi": 2_000_000,
            "debiti_fin_lungo": 1_000_000,
            "debiti_fin_breve": 500_000,
            "capitale_fisso_netto": 4_000_000,
            "capitale_investito_netto": 6_000_000,
            "totale_attivo": 10_000_000,
            "totale_passivo": 10_000_000,
            "crediti_commerciali": 2_000_000,
            "rimanenze": 1_500_000,
            "liquidita": 500_000,
            "debiti_breve_totali": 2_500_000,
            "acquisti": 3_000_000,
            "costo_venduto": 6_000_000,
        }
        indici = _calcola_indici_anno(v)

        # ROE = 500k / 3M = 0.1667
        assert indici["redditivita"]["ROE"] == pytest.approx(0.1667, abs=0.001)
        # ROS = 1M / 10M = 0.10
        assert indici["redditivita"]["ROS"] == pytest.approx(0.10, abs=0.001)
        # EBITDA_margin = 2M / 10M = 0.20
        assert indici["redditivita"]["EBITDA_margin"] == pytest.approx(0.20, abs=0.001)
        # current_ratio = (2M + 1.5M + 0.5M) / 2.5M = 1.6
        assert indici["liquidita"]["current_ratio"] == pytest.approx(1.6, abs=0.01)

    def test_zero_denominators_handled(self):
        """Division by zero should return None, not raise."""
        v = {
            "ricavi_netti": 0,
            "ebitda": 0,
            "ebit": 0,
            "ebt": 0,
            "utile_netto": 0,
            "ammortamenti": 0,
            "costi_personale": 0,
            "valore_aggiunto": 0,
            "patrimonio_netto": 0,
            "pfn": 0,
            "debiti_operativi": 0,
            "debiti_fin_lungo": 0,
            "debiti_fin_breve": 0,
            "capitale_fisso_netto": 0,
            "capitale_investito_netto": 0,
            "totale_attivo": 0,
            "totale_passivo": 0,
            "crediti_commerciali": 0,
            "rimanenze": 0,
            "liquidita": 0,
            "debiti_breve_totali": 0,
            "acquisti": 0,
            "costo_venduto": 0,
        }
        indici = _calcola_indici_anno(v)
        assert indici["redditivita"]["ROE"] is None
        assert indici["redditivita"]["ROS"] is None
        assert indici["liquidita"]["current_ratio"] is None

    def test_with_pn_medio(self):
        v = {
            "ricavi_netti": 10_000_000,
            "ebitda": 2_000_000,
            "ebit": 1_000_000,
            "ebt": 800_000,
            "utile_netto": 500_000,
            "ammortamenti": 1_000_000,
            "costi_personale": 2_000_000,
            "valore_aggiunto": 5_000_000,
            "patrimonio_netto": 3_000_000,
            "pfn": 1_500_000,
            "debiti_operativi": 2_000_000,
            "debiti_fin_lungo": 1_000_000,
            "debiti_fin_breve": 500_000,
            "capitale_fisso_netto": 4_000_000,
            "capitale_investito_netto": 6_000_000,
            "totale_attivo": 10_000_000,
            "totale_passivo": 10_000_000,
            "crediti_commerciali": 2_000_000,
            "rimanenze": 1_500_000,
            "liquidita": 500_000,
            "debiti_breve_totali": 2_500_000,
            "acquisti": 3_000_000,
            "costo_venduto": 6_000_000,
        }
        # pn_medio = 2_500_000
        indici = _calcola_indici_anno(v, pn_medio=2_500_000)
        # ROE = 500k / 2.5M = 0.20
        assert indici["redditivita"]["ROE"] == pytest.approx(0.20, abs=0.001)


# ---------------------------------------------------------------------------
# TestCalcolaTrend
# ---------------------------------------------------------------------------

class TestCalcolaTrend:

    def test_crescente(self):
        indici = {
            "redditivita": {
                "ROS": {"2023": 0.10, "2024": 0.15},
            }
        }
        trend = _calcola_trend(indici, ["2023", "2024"])
        assert len(trend) == 1
        assert trend[0]["direzione"] == "crescente"

    def test_decrescente(self):
        indici = {
            "redditivita": {
                "ROS": {"2023": 0.15, "2024": 0.10},
            }
        }
        trend = _calcola_trend(indici, ["2023", "2024"])
        assert len(trend) == 1
        assert trend[0]["direzione"] == "decrescente"

    def test_stabile(self):
        indici = {
            "redditivita": {
                "ROS": {"2023": 0.10, "2024": 0.101},
            }
        }
        trend = _calcola_trend(indici, ["2023", "2024"])
        assert len(trend) == 1
        assert trend[0]["direzione"] == "stabile"


# ---------------------------------------------------------------------------
# TestGeneraAlert
# ---------------------------------------------------------------------------

class TestGeneraAlert:

    def test_current_ratio_rischio(self):
        indici = {
            "liquidita": {
                "current_ratio": {"2024": 0.8},
            }
        }
        alert = _genera_alert(indici, ["2024"])
        assert len(alert) >= 1
        alert_cr = [a for a in alert if a["indice"] == "current_ratio"]
        assert len(alert_cr) == 1
        assert alert_cr[0]["tipo"] == "rischio"

    def test_pfn_ebitda_rischio(self):
        indici = {
            "struttura": {
                "pfn_ebitda": {"2024": 5.0},
            }
        }
        alert = _genera_alert(indici, ["2024"])
        alert_pfn = [a for a in alert if a["indice"] == "pfn_ebitda"]
        assert len(alert_pfn) == 1
        assert alert_pfn[0]["tipo"] == "rischio"

    def test_safe_values_no_alerts(self):
        indici = {
            "redditivita": {
                "ROE": {"2024": 0.15},
                "ROI": {"2024": 0.10},
                "ROS": {"2024": 0.08},
                "ROA": {"2024": 0.06},
                "EBITDA_margin": {"2024": 0.15},
            },
            "struttura": {
                "indice_indipendenza_finanziaria": {"2024": 0.50},
                "rapporto_indebitamento": {"2024": 0.5},
                "copertura_immobilizzazioni": {"2024": 1.5},
                "pfn_ebitda": {"2024": 1.0},
                "pfn_pn": {"2024": 0.3},
            },
            "liquidita": {
                "current_ratio": {"2024": 2.0},
                "quick_ratio": {"2024": 1.5},
                "giorni_crediti": {"2024": 45},
                "giorni_debiti": {"2024": 60},
                "giorni_magazzino": {"2024": 30},
                "ciclo_cassa": {"2024": 15},
            },
            "efficienza": {
                "costo_personale_su_va": {"2024": 0.35},
                "incidenza_ammortamenti": {"2024": 0.05},
            },
        }
        alert = _genera_alert(indici, ["2024"])
        assert len(alert) == 0


# ---------------------------------------------------------------------------
# TestGeneraNarrativeTemplate
# ---------------------------------------------------------------------------

class TestGeneraNarrativeTemplate:

    def test_returns_5_keys(self, pipeline_result):
        risultati = pipeline_result["riclassifica"]["risultati_per_anno"]
        anni = sorted(risultati.keys())
        valori_per_anno = {}
        for anno in anni:
            valori_per_anno[anno] = _estrai_valori_anno(risultati[anno])

        indici = {
            "redditivita": {"ROE": {a: 0.15 for a in anni}, "ROS": {a: 0.08 for a in anni},
                            "ROI": {a: 0.10 for a in anni}, "ROA": {a: 0.06 for a in anni},
                            "EBITDA_margin": {a: 0.14 for a in anni}},
            "struttura": {"indice_indipendenza_finanziaria": {a: 0.30 for a in anni},
                          "pfn_ebitda": {a: 0.7 for a in anni},
                          "copertura_immobilizzazioni": {a: 1.1 for a in anni},
                          "rapporto_indebitamento": {a: 1.5 for a in anni},
                          "pfn_pn": {a: 0.5 for a in anni}},
            "liquidita": {"current_ratio": {a: 1.6 for a in anni},
                          "quick_ratio": {a: 0.9 for a in anni},
                          "giorni_crediti": {a: 60 for a in anni},
                          "giorni_debiti": {a: 180 for a in anni},
                          "giorni_magazzino": {a: 59 for a in anni},
                          "ciclo_cassa": {a: -61 for a in anni}},
            "efficienza": {"costo_personale_su_va": {a: 0.42 for a in anni},
                           "incidenza_ammortamenti": {a: 0.07 for a in anni}},
        }
        trend = []
        alert = []

        narrative = _genera_narrative_template(
            indici, trend, alert, anni, valori_per_anno, "Test S.r.l."
        )

        expected_keys = {"sintesi", "redditivita", "struttura_finanziaria", "liquidita", "conclusioni"}
        assert set(narrative.keys()) == expected_keys

        for key in expected_keys:
            assert isinstance(narrative[key], str)
            assert len(narrative[key]) > 0
