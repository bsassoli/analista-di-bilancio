"""Test per le funzioni deterministiche di agents/produttore.py."""

import pytest
from pathlib import Path

from agents.produttore import (
    _prepara_foglio_sp,
    _prepara_foglio_ce,
    _prepara_foglio_indici,
    _genera_excel,
    _genera_word,
    _nome_file_base,
)


# ---------------------------------------------------------------------------
# TestNomeFileBase
# ---------------------------------------------------------------------------

class TestNomeFileBase:

    def test_srl(self):
        assert _nome_file_base("Test S.r.l.") == "test_srl"

    def test_spa(self):
        assert _nome_file_base("Enervit S.p.A.") == "enervit_spa"

    def test_spaces_and_dots(self):
        assert _nome_file_base("Azienda Esempio S.r.l.") == "azienda_esempio_srl"

    def test_comma(self):
        assert _nome_file_base("Rossi, Bianchi S.r.l.") == "rossi_bianchi_srl"


# ---------------------------------------------------------------------------
# TestPreparaFoglioSP
# ---------------------------------------------------------------------------

class TestPreparaFoglioSP:

    def test_header_row(self, pipeline_result):
        anni = sorted(pipeline_result["riclassifica"]["risultati_per_anno"].keys())
        righe = _prepara_foglio_sp(pipeline_result, anni)
        header = righe[0]
        assert header[0] == "Voce"
        for anno in anni:
            assert anno in header

    def test_key_labels_present(self, pipeline_result):
        anni = sorted(pipeline_result["riclassifica"]["risultati_per_anno"].keys())
        righe = _prepara_foglio_sp(pipeline_result, anni)
        labels = [r[0] for r in righe]
        assert "CAPITALE FISSO NETTO" in labels
        assert "CCON (Capitale Circolante Operativo Netto)" in labels
        assert "PATRIMONIO NETTO" in labels
        assert "POSIZIONE FINANZIARIA NETTA" in labels
        assert "TOTALE ATTIVO" in labels
        assert "TOTALE PASSIVO" in labels

    def test_anni_columns_have_values(self, pipeline_result):
        anni = sorted(pipeline_result["riclassifica"]["risultati_per_anno"].keys())
        righe = _prepara_foglio_sp(pipeline_result, anni)
        # Find CAPITALE FISSO NETTO row - should have non-empty values
        for riga in righe:
            if riga[0] == "CAPITALE FISSO NETTO":
                for val in riga[1:]:
                    assert val != "n/d"
                break


# ---------------------------------------------------------------------------
# TestPreparaFoglioCE
# ---------------------------------------------------------------------------

class TestPreparaFoglioCE:

    def test_header_with_percentage_columns(self, pipeline_result):
        anni = sorted(pipeline_result["riclassifica"]["risultati_per_anno"].keys())
        righe = _prepara_foglio_ce(pipeline_result, anni)
        header = righe[0]
        assert header[0] == "Voce"
        # Each anno should have value + % column
        for anno in anni:
            assert anno in header
            assert f"% {anno}" in header

    def test_key_labels_present(self, pipeline_result):
        anni = sorted(pipeline_result["riclassifica"]["risultati_per_anno"].keys())
        righe = _prepara_foglio_ce(pipeline_result, anni)
        labels = [r[0] for r in righe]
        assert "EBITDA" in labels
        assert "EBIT" in labels
        assert "UTILE NETTO" in labels
        assert "Ricavi netti" in labels


# ---------------------------------------------------------------------------
# TestPreparaFoglioIndici
# ---------------------------------------------------------------------------

class TestPreparaFoglioIndici:

    def test_category_headers_present(self, analisi):
        anni = [str(a) for a in analisi["anni"]]
        righe = _prepara_foglio_indici(analisi, anni)

        # First row is header
        assert righe[0][0] == "Categoria"

        # Category headers should be present
        all_cells = [r[0] for r in righe]
        assert "REDDITIVITA" in all_cells
        assert "STRUTTURA FINANZIARIA" in all_cells
        assert "LIQUIDITA E CICLO COMMERCIALE" in all_cells
        assert "EFFICIENZA" in all_cells

    def test_indice_names_present(self, analisi):
        anni = [str(a) for a in analisi["anni"]]
        righe = _prepara_foglio_indici(analisi, anni)
        # Indice names are in column 1 (index 1)
        indice_names = [r[1] for r in righe if len(r) > 1]
        assert "ROE" in indice_names
        assert "current_ratio" in indice_names


# ---------------------------------------------------------------------------
# TestGeneraExcel
# ---------------------------------------------------------------------------

class TestGeneraExcel:

    def test_file_created(self, pipeline_result, analisi, tmp_path):
        path = _genera_excel(pipeline_result, analisi, tmp_path)
        assert Path(path).exists()
        assert path.endswith(".xlsx")

    def test_file_created_without_analisi(self, pipeline_result, tmp_path):
        path = _genera_excel(pipeline_result, None, tmp_path)
        assert Path(path).exists()
        assert path.endswith(".xlsx")


# ---------------------------------------------------------------------------
# TestGeneraWord
# ---------------------------------------------------------------------------

class TestGeneraWord:

    def test_file_created(self, pipeline_result, analisi, tmp_path):
        path = _genera_word(pipeline_result, analisi, tmp_path)
        assert Path(path).exists()
        assert path.endswith(".docx")

    def test_file_created_without_analisi(self, pipeline_result, tmp_path):
        path = _genera_word(pipeline_result, None, tmp_path)
        assert Path(path).exists()
        assert path.endswith(".docx")
