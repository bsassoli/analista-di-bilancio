"""Tests for tools.document_recon — page classification and reconnaissance."""

from unittest.mock import MagicMock, patch

from tools.document_recon import (
    _keyword_score,
    _punteggio_pagina,
    _rileva_anni,
    _rileva_nome_azienda,
    classifica_pagine,
)


class TestKeywordScore:
    def test_no_match(self):
        assert _keyword_score("testo generico", ["foo", "bar"]) == 0

    def test_some_matches(self):
        assert _keyword_score("totale attivo e totale passivo", ["totale attivo", "totale passivo"]) == 2

    def test_partial_match(self):
        assert _keyword_score("attivo circolante", ["attivo", "passivo"]) == 1


class TestPunteggioPagina:
    def test_empty_page(self):
        sc = _punteggio_pagina("")
        assert sc["numeric_density"] == 0.0
        assert sc["sp_score"] == 0

    def test_numeric_page(self):
        text = "Immobilizzazioni  1.250.000  1.100.000\nTerreni  500.000  400.000\nTotale attivo  2.000.000  1.800.000"
        sc = _punteggio_pagina(text)
        assert sc["numeric_density"] > 0.1
        assert sc["sp_score"] >= 1

    def test_prose_page(self):
        text = ("La nota integrativa descrive i criteri di valutazione adottati "
                "dalla società per la redazione del bilancio. I principi contabili "
                "sono conformi alle disposizioni del codice civile.")
        sc = _punteggio_pagina(text)
        assert sc["numeric_density"] < 0.1
        assert sc["ni_score"] >= 2


class TestRilevaAnni:
    def test_finds_years(self):
        testi = ["", "Bilancio al 31.12.2024 e 31.12.2023", ""]
        anni = _rileva_anni(testi, [2])  # page 2 (1-based)
        assert "2024" in anni
        assert "2023" in anni

    def test_no_years(self):
        testi = ["Nessun anno qui"]
        assert _rileva_anni(testi, [1]) == []

    def test_filters_to_statement_pages(self):
        testi = ["anno 2020 vecchio", "Bilancio 2024 e 2023"]
        # Only scan page 2
        anni = _rileva_anni(testi, [2])
        assert "2024" in anni
        assert "2020" not in anni


class TestRilevaNomeAzienda:
    def test_finds_spa(self):
        testi = ["Bilancio di Enervit S.p.A. al 31 dicembre 2024"]
        assert "Enervit S.p.A." in _rileva_nome_azienda(testi)

    def test_finds_srl(self):
        testi = ["Mario Rossi S.r.l. — Nota integrativa"]
        assert "S.r.l." in _rileva_nome_azienda(testi)

    def test_no_match(self):
        testi = ["Pagina senza nome azienda"]
        assert _rileva_nome_azienda(testi) == ""


class TestClassificaPagine:
    @patch("tools.document_recon._estrai_testo_pagine")
    def test_basic_classification(self, mock_extract):
        """SP page, CE page, NI page correctly classified."""
        sp_text = (
            "STATO PATRIMONIALE\n"
            "Immobilizzazioni  1.250.000  1.100.000\n"
            "Terreni  500.000  400.000\n"
            "Fabbricati  300.000  250.000\n"
            "Totale attivo  2.050.000  1.750.000\n"
            "Patrimonio netto  1.000.000  900.000\n"
            "Totale passivo  2.050.000  1.750.000\n"
        )
        ce_text = (
            "CONTO ECONOMICO\n"
            "Ricavi  5.000.000  4.500.000\n"
            "Costi della produzione  3.000.000  2.800.000\n"
            "Risultato operativo  2.000.000  1.700.000\n"
            "Risultato netto  1.500.000  1.200.000\n"
            "Valore della produzione  5.500.000  5.000.000\n"
        )
        ni_text = (
            "NOTA INTEGRATIVA\n"
            "La presente nota integrativa illustra i criteri di valutazione "
            "adottati per la redazione del bilancio d'esercizio. "
            "Le immobilizzazioni materiali sono iscritte al costo di acquisto. "
            "I crediti verso clienti sono valutati al valore nominale. "
            "I debiti verso fornitori sono iscritti al valore nominale. "
            "La composizione delle voci è la seguente. " * 5
        )
        mock_extract.return_value = [sp_text, ce_text, ni_text]

        profile = classifica_pagine("/fake/path.pdf")
        assert 1 in profile.page_map["sp"]
        assert 2 in profile.page_map["ce"]
        # NI should be detected
        assert len(profile.page_map["nota_integrativa"]) >= 1

    @patch("tools.document_recon._estrai_testo_pagine")
    def test_ifrs_detection(self, mock_extract):
        text = "Attività non correnti 1.000.000\nAttività correnti 500.000\nPassività non correnti 300.000\n" * 3
        mock_extract.return_value = [text]
        profile = classifica_pagine("/fake/path.pdf")
        assert profile.accounting_standard == "IFRS"

    @patch("tools.document_recon._estrai_testo_pagine")
    def test_oic_detection(self, mock_extract):
        text = "Valore della produzione 5.000.000\nCosti della produzione 3.000.000\nImmobilizzazioni materiali\n" * 3
        mock_extract.return_value = [text]
        profile = classifica_pagine("/fake/path.pdf")
        assert profile.accounting_standard == "OIC"

    @patch("tools.document_recon._estrai_testo_pagine")
    def test_consolidato_detection(self, mock_extract):
        mock_extract.return_value = ["Bilancio consolidato del gruppo al 31.12.2024"]
        profile = classifica_pagine("/fake/path.pdf")
        assert profile.scope == "consolidato"

    @patch("tools.document_recon._estrai_testo_pagine")
    def test_year_detection(self, mock_extract):
        text = "Bilancio al 31.12.2024\nTotale attivo  1.000.000  900.000\nTotale passivo  1.000.000  900.000\nImmobilizzazioni  500.000  400.000\nPatrimonio netto  600.000  500.000\n"
        mock_extract.return_value = [text]
        profile = classifica_pagine("/fake/path.pdf")
        assert "2024" in profile.years_present

    @patch("tools.document_recon._estrai_testo_pagine")
    def test_empty_pdf(self, mock_extract):
        mock_extract.return_value = []
        profile = classifica_pagine("/fake/path.pdf")
        assert profile.n_pages == 0
        assert profile.years_present == []
