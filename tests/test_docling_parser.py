"""Test per tools/docling_parser.py — funzioni deterministiche (mocked Docling)."""

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock

from tools.docling_parser import tabella_a_righe_bilancio, identifica_tabelle_prospetto


class TestTabellaARigheBilancio:
    """Test per la conversione DataFrame → righe bilancio."""

    def _df_sp_ifrs(self):
        """DataFrame simile a un SP IFRS Docling."""
        return pd.DataFrame({
            "Voci": [
                "Immobilizzazioni materiali",
                "Immobilizzazioni immateriali",
                "Totale attività non correnti",
                "Rimanenze",
                "Crediti commerciali",
                "Disponibilità liquide",
                "Totale attività correnti",
                "TOTALE ATTIVO",
            ],
            "31 dicembre 2024": [
                "3.000.000", "500.000", "3.500.000",
                "1.200.000", "2.000.000", "800.000",
                "4.000.000", "7.500.000",
            ],
            "31 dicembre 2023": [
                "2.800.000", "600.000", "3.400.000",
                "1.100.000", "1.800.000", "620.000",
                "3.520.000", "6.920.000",
            ],
        })

    def test_estrae_righe(self):
        df = self._df_sp_ifrs()
        righe = tabella_a_righe_bilancio(df, "IFRS")
        assert len(righe) == 8
        assert righe[0]["label"] == "Immobilizzazioni materiali"
        assert "2024" in righe[0]["valori"]
        assert "2023" in righe[0]["valori"]

    def test_rileva_anni_da_header(self):
        df = self._df_sp_ifrs()
        righe = tabella_a_righe_bilancio(df, "IFRS")
        anni = set()
        for r in righe:
            anni.update(r["valori"].keys())
        assert "2024" in anni
        assert "2023" in anni

    def test_livello_totale(self):
        df = self._df_sp_ifrs()
        righe = tabella_a_righe_bilancio(df, "IFRS")
        totale_attivo = [r for r in righe if "TOTALE ATTIVO" in r["label"]]
        assert len(totale_attivo) == 1
        assert totale_attivo[0]["livello"] == "totale"

    def test_livello_subtotale(self):
        df = pd.DataFrame({
            "Voci": ["Ricavi", "EBITDA", "Risultato netto"],
            "2024": ["10.000", "1.500", "400"],
            "2023": ["9.000", "1.200", "300"],
        })
        righe = tabella_a_righe_bilancio(df, "IFRS")
        ebitda = [r for r in righe if "EBITDA" in r["label"]]
        assert ebitda[0]["livello"] == "subtotale"

    def test_sezione_senza_valori(self):
        df = pd.DataFrame({
            "Voci": ["ATTIVITÀ NON CORRENTI", "Immobilizzazioni materiali"],
            "2024": ["", "3.000.000"],
            "2023": ["", "2.800.000"],
        })
        righe = tabella_a_righe_bilancio(df, "IFRS")
        sez = [r for r in righe if "CORRENTI" in r["label"]]
        assert sez[0]["livello"] == "sezione"

    def test_di_cui(self):
        df = pd.DataFrame({
            "Voci": ["Crediti commerciali", "di cui verso controllate"],
            "2024": ["2.000.000", "500.000"],
            "2023": ["1.800.000", "400.000"],
        })
        righe = tabella_a_righe_bilancio(df, "IFRS")
        di_cui = [r for r in righe if "di cui" in r["label"]]
        assert di_cui[0]["livello"] == "di_cui"

    def test_df_senza_anni(self):
        df = pd.DataFrame({
            "Voce": ["A", "B"],
            "Col1": ["x", "y"],
        })
        righe = tabella_a_righe_bilancio(df, "IFRS")
        assert len(righe) == 0  # Nessuna colonna anno rilevata

    def test_nota_ref(self):
        df = pd.DataFrame({
            "Voci": ["Immobilizzazioni materiali"],
            "Note": ["5"],
            "2024": ["3.000.000"],
            "2023": ["2.800.000"],
        })
        righe = tabella_a_righe_bilancio(df, "IFRS")
        assert righe[0]["nota_ref"] == "5"


class TestIdentificaTabelleProspetto:
    """Test per classificazione tabelle SP/CE (con Docling mockato)."""

    def _mock_table(self, df, page_no=1):
        """Crea un mock di tabella Docling."""
        table = MagicMock()
        prov = MagicMock()
        prov.page_no = page_no
        table.prov = [prov]
        table.export_to_dataframe = MagicMock(return_value=df)
        return table

    def _df_sp(self):
        return pd.DataFrame({
            "Voci": [f"Voce {i}" for i in range(10)] + ["Totale attivo"],
            "2024": [str(i * 100_000) for i in range(10)] + ["5000000"],
            "2023": [str(i * 90_000) for i in range(10)] + ["4500000"],
        })

    def _df_ce(self):
        return pd.DataFrame({
            "Voci": [f"Voce {i}" for i in range(8)] + ["Risultato operativo", "EBITDA"],
            "2024": [str(i * 50_000) for i in range(8)] + ["1000000", "1500000"],
            "2023": [str(i * 45_000) for i in range(8)] + ["900000", "1300000"],
        })

    def _df_piccola(self):
        return pd.DataFrame({
            "A": ["x", "y"],
            "B": ["1", "2"],
        })

    @patch("tools.docling_parser.converti_documento")
    def test_classifica_sp_e_ce(self, mock_conv):
        doc = MagicMock()
        doc.tables = [
            self._mock_table(self._df_sp(), page_no=52),
            self._mock_table(self._df_ce(), page_no=54),
            self._mock_table(self._df_piccola(), page_no=10),
        ]
        mock_conv.return_value = doc

        result = identifica_tabelle_prospetto("fake.pdf")

        assert len(result["sp_tabelle"]) >= 1
        assert len(result["ce_tabelle"]) >= 1
        assert result["n_tabelle_totali"] == 3

    @patch("tools.docling_parser.converti_documento")
    def test_rileva_formato_ifrs(self, mock_conv):
        df = pd.DataFrame({
            "Voci": ["Attività non correnti"] + [f"V{i}" for i in range(9)] + ["Totale attivo"],
            "2024": [""] + [str(i * 100_000) for i in range(9)] + ["5000000"],
            "2023": [""] + [str(i * 90_000) for i in range(9)] + ["4500000"],
        })
        doc = MagicMock()
        doc.tables = [self._mock_table(df)]
        mock_conv.return_value = doc

        result = identifica_tabelle_prospetto("fake.pdf")
        assert result["formato"] == "IFRS"

    @patch("tools.docling_parser.converti_documento")
    def test_rileva_formato_oic(self, mock_conv):
        df = pd.DataFrame({
            "Voci": ["Valore della produzione"] + [f"V{i}" for i in range(9)] + ["Risultato operativo"],
            "2024": ["10000000"] + [str(i * 100_000) for i in range(9)] + ["1000000"],
            "2023": ["9000000"] + [str(i * 90_000) for i in range(9)] + ["900000"],
        })
        doc = MagicMock()
        doc.tables = [self._mock_table(df)]
        mock_conv.return_value = doc

        result = identifica_tabelle_prospetto("fake.pdf")
        assert result["formato"] == "OIC_ordinario"

    @patch("tools.docling_parser.converti_documento")
    def test_filtra_tabelle_piccole(self, mock_conv):
        doc = MagicMock()
        doc.tables = [self._mock_table(self._df_piccola())]
        mock_conv.return_value = doc

        result = identifica_tabelle_prospetto("fake.pdf")
        assert len(result["sp_tabelle"]) == 0
        assert len(result["ce_tabelle"]) == 0

    @patch("tools.docling_parser.converti_documento")
    def test_post_filter_troppi_sp(self, mock_conv):
        doc = MagicMock()
        # 6 tabelle SP — dovrebbe tenerle max 4
        doc.tables = [self._mock_table(self._df_sp(), page_no=i) for i in range(6)]
        mock_conv.return_value = doc

        result = identifica_tabelle_prospetto("fake.pdf")
        assert len(result["sp_tabelle"]) <= 4
