"""Test per i calcolatori deterministici."""

import pytest
from tools.calcolatori import (
    calcola_ccon,
    calcola_pfn,
    calcola_subtotale,
    cagr,
    ciclo_cassa,
    current_ratio,
    ebitda_margin,
    giorni_crediti,
    giorni_debiti,
    giorni_magazzino,
    pfn_su_ebitda,
    pfn_su_pn,
    quick_ratio,
    rapporto_indebitamento,
    roe,
    roi,
    ros,
    variazione_yoy,
    verifica_quadratura,
)


class TestAggregatiSP:
    def test_ccon_positivo(self):
        assert calcola_ccon(1_000_000, 500_000, 200_000, 800_000) == 900_000

    def test_ccon_negativo(self):
        assert calcola_ccon(100_000, 50_000, 20_000, 500_000) == -330_000

    def test_pfn_positiva_indebitamento(self):
        assert calcola_pfn(2_000_000, 500_000, 300_000) == 2_200_000

    def test_pfn_negativa_cassa_netta(self):
        assert calcola_pfn(100_000, 50_000, 500_000) == -350_000

    def test_quadratura_ok(self):
        r = verifica_quadratura(15_000_000, 15_000_000)
        assert r["ok"] is True
        assert r["delta"] == 0

    def test_quadratura_ko(self):
        r = verifica_quadratura(15_000_000, 12_000_000)
        assert r["ok"] is False
        assert r["delta"] == 3_000_000

    def test_quadratura_tolleranza(self):
        r = verifica_quadratura(15_000_001, 15_000_000, tolleranza=1)
        assert r["ok"] is True

    def test_subtotale(self):
        voci = [
            {"id": "a", "valore": {"2023": 100}},
            {"id": "b", "valore": {"2023": 200}},
            {"id": "c", "valore": {"2023": 300}},
        ]
        assert calcola_subtotale(voci, ["a", "c"], "2023") == 400


class TestIndici:
    def test_roe(self):
        r = roe(120_000, 1_000_000)
        assert r == pytest.approx(0.12)

    def test_roe_pn_zero(self):
        assert roe(120_000, 0) is None

    def test_roi(self):
        r = roi(500_000, 5_000_000)
        assert r == pytest.approx(0.10)

    def test_ros(self):
        r = ros(500_000, 10_000_000)
        assert r == pytest.approx(0.05)

    def test_ebitda_margin(self):
        r = ebitda_margin(1_200_000, 10_000_000)
        assert r == pytest.approx(0.12)

    def test_pfn_su_ebitda(self):
        r = pfn_su_ebitda(4_500_000, 1_000_000)
        assert r == pytest.approx(4.5)

    def test_pfn_su_pn(self):
        r = pfn_su_pn(800_000, 1_000_000)
        assert r == pytest.approx(0.8)

    def test_current_ratio(self):
        r = current_ratio(1_000_000, 500_000, 200_000, 1_000_000)
        assert r == pytest.approx(1.7)

    def test_quick_ratio(self):
        r = quick_ratio(1_000_000, 200_000, 1_000_000)
        assert r == pytest.approx(1.2)

    def test_giorni_crediti(self):
        r = giorni_crediti(2_500_000, 10_000_000)
        assert r == pytest.approx(91.2, abs=0.1)

    def test_giorni_debiti(self):
        r = giorni_debiti(1_500_000, 6_000_000)
        assert r == pytest.approx(91.2, abs=0.1)

    def test_giorni_magazzino(self):
        r = giorni_magazzino(800_000, 6_000_000)
        assert r == pytest.approx(48.7, abs=0.1)

    def test_ciclo_cassa(self):
        r = ciclo_cassa(91.2, 48.7, 91.2)
        assert r == pytest.approx(48.7)

    def test_ciclo_cassa_con_none(self):
        assert ciclo_cassa(91.2, None, 60.0) is None

    def test_rapporto_indebitamento(self):
        r = rapporto_indebitamento(2_000_000, 1_000_000, 1_500_000)
        assert r == pytest.approx(2.0)


class TestTrend:
    def test_variazione_yoy_positiva(self):
        r = variazione_yoy(1_150_000, 1_000_000)
        assert r == pytest.approx(0.15)

    def test_variazione_yoy_negativa(self):
        r = variazione_yoy(850_000, 1_000_000)
        assert r == pytest.approx(-0.15)

    def test_variazione_yoy_base_zero(self):
        assert variazione_yoy(100_000, 0) is None

    def test_cagr(self):
        r = cagr(1_000_000, 1_500_000, 5)
        assert r == pytest.approx(0.0845, abs=0.001)

    def test_cagr_un_anno(self):
        r = cagr(1_000_000, 1_100_000, 1)
        assert r == pytest.approx(0.10)

    def test_cagr_invalido(self):
        assert cagr(0, 1_000_000, 5) is None
        assert cagr(1_000_000, 1_000_000, 0) is None
