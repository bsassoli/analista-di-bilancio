"""Test per agents/estrattore_pdf_docling.py — pipeline ibrida (mocked)."""

import json
import pytest
from unittest.mock import patch, MagicMock

from agents.estrattore_pdf_docling import (
    _estrai_struttura,
    _mapping_semantico,
    _valida_estrazione,
    _estrai_json,
    estrai_pdf_docling,
)
from tools.evidence_schema import DocumentProfile


def _mock_profile():
    return DocumentProfile(
        company_name="Test", years_present=["2024"],
        accounting_standard="IFRS", scope="unknown",
        format_type="ordinario", page_map={"sp": [], "ce": [], "nota_integrativa": [],
                                            "relazione_gestione": [], "other": []},
    )


class TestEstraiJson:
    """Test per il parser JSON dalle risposte LLM."""

    def test_json_diretto(self):
        result = _estrai_json('{"a": 1}')
        assert result == {"a": 1}

    def test_json_in_markdown(self):
        testo = '```json\n{"a": 1}\n```'
        result = _estrai_json(testo)
        assert result == {"a": 1}

    def test_json_con_testo_attorno(self):
        testo = 'Ecco il risultato:\n{"a": 1}\nFine.'
        result = _estrai_json(testo)
        assert result == {"a": 1}

    def test_json_non_valido(self):
        result = _estrai_json("niente json qui")
        assert "error" in result

    def test_json_nested(self):
        testo = '{"sezioni": {"sp": {"righe": []}}}'
        result = _estrai_json(testo)
        assert "sezioni" in result


class TestValidaEstrazione:
    """Test per la validazione post-estrazione."""

    def _risultato_con_totali(self, att_2024, pas_2024, utile=True):
        righe_attivo = [
            {"label": "Totale attività", "valori": {"2024": str(att_2024)}},
        ]
        righe_passivo = [
            {"label": "Totale patrimonio netto e passività", "valori": {"2024": str(pas_2024)}},
        ]
        righe_ce = []
        if utile:
            righe_ce.append(
                {"label": "Risultato netto dell'esercizio", "valori": {"2024": "400000"}}
            )
        return {
            "sezioni": {
                "sp_attivo": {"righe": righe_attivo},
                "sp_passivo": {"righe": righe_passivo},
                "ce": {"righe": righe_ce},
            }
        }

    def test_quadratura_ok(self):
        result = self._risultato_con_totali(8_000_000, 8_000_000)
        problemi = _valida_estrazione(result, ["2024"])
        # Nessun problema di quadratura
        quad_problemi = [p for p in problemi if "Quadratura" in p]
        assert len(quad_problemi) == 0

    def test_quadratura_ko(self):
        result = self._risultato_con_totali(8_000_000, 6_000_000)
        problemi = _valida_estrazione(result, ["2024"])
        quad_problemi = [p for p in problemi if "Quadratura" in p]
        assert len(quad_problemi) == 1

    def test_utile_non_trovato(self):
        result = self._risultato_con_totali(8_000_000, 8_000_000, utile=False)
        problemi = _valida_estrazione(result, ["2024"])
        utile_problemi = [p for p in problemi if "Utile" in p]
        assert len(utile_problemi) == 1

    def test_totali_mancanti(self):
        result = {"sezioni": {"sp_attivo": {"righe": []}, "sp_passivo": {"righe": []}, "ce": {"righe": []}}}
        problemi = _valida_estrazione(result, ["2024"])
        assert len(problemi) >= 1


class TestEstraiStruttura:
    """Test per Fase 1 — estrazione strutturale (Docling mockato)."""

    @patch("agents.estrattore_pdf_docling.identifica_tabelle_prospetto")
    @patch("agents.estrattore_pdf_docling.tabella_a_righe_bilancio")
    def test_struttura_base(self, mock_tab_righe, mock_identifica):
        import pandas as pd

        mock_identifica.return_value = {
            "sp_tabelle": [{"dataframe": pd.DataFrame(), "pagina": 52}],
            "ce_tabelle": [{"dataframe": pd.DataFrame(), "pagina": 54}],
            "altre_tabelle": [],
            "formato": "IFRS",
            "n_tabelle_totali": 10,
        }
        mock_tab_righe.return_value = [
            {"label": "Voce test", "valori": {"2024": "1000", "2023": "900"}, "livello": "dettaglio"},
        ]

        result = _estrai_struttura("fake.pdf")

        assert result["formato"] == "IFRS"
        assert len(result["sp_righe"]) == 1
        assert len(result["ce_righe"]) == 1
        assert "2024" in result["anni_presenti"]
        assert "2023" in result["anni_presenti"]

    @patch("agents.estrattore_pdf_docling.identifica_tabelle_prospetto")
    @patch("agents.estrattore_pdf_docling.tabella_a_righe_bilancio")
    def test_nessun_prospetto(self, mock_tab_righe, mock_identifica):
        mock_identifica.return_value = {
            "sp_tabelle": [],
            "ce_tabelle": [],
            "altre_tabelle": [],
            "formato": "IFRS",
            "n_tabelle_totali": 5,
        }
        mock_tab_righe.return_value = []

        result = _estrai_struttura("fake.pdf")
        assert len(result["sp_righe"]) == 0
        assert len(result["ce_righe"]) == 0


class TestMappingSemantico:
    """Test per Fase 2 — mapping LLM (API mockato, 2 chiamate separate)."""

    @patch("agents.estrattore_pdf_docling.crea_client")
    def test_mapping_split_sp_ce(self, mock_client):
        risposta_sp = {
            "sp_attivo": {"righe": [
                {"label": "Immobilizzazioni", "valori": {"2024": "1000"}, "livello": "dettaglio"},
                {"label": "Totale attivo", "valori": {"2024": "1000"}, "livello": "totale"},
            ]},
            "sp_passivo": {"righe": [
                {"label": "Patrimonio netto", "valori": {"2024": "1000"}, "livello": "totale"},
                {"label": "Totale passivo e patrimonio netto", "valori": {"2024": "1000"}, "livello": "totale"},
            ]},
            "problemi": [],
        }
        risposta_ce = {
            "ce": {"righe": [
                {"label": "Ricavi", "valori": {"2024": "5000"}, "livello": "dettaglio"},
            ]},
            "problemi": [],
        }

        # Mock restituisce risposte diverse per le 2 chiamate (SP + CE)
        mock_resp_sp = MagicMock()
        mock_resp_sp.content = [MagicMock(text=json.dumps(risposta_sp))]
        mock_resp_ce = MagicMock()
        mock_resp_ce.content = [MagicMock(text=json.dumps(risposta_ce))]
        mock_client.return_value.messages.create.side_effect = [mock_resp_sp, mock_resp_ce]

        result = _mapping_semantico(
            sp_righe=[{"label": "Test", "valori": {"2024": "100"}}],
            ce_righe=[{"label": "Ricavi", "valori": {"2024": "5000"}}],
            formato="IFRS",
            anni=["2024"],
        )

        assert "sezioni" in result
        assert len(result["sezioni"]["sp_attivo"]["righe"]) == 2
        assert len(result["sezioni"]["sp_passivo"]["righe"]) == 2
        assert len(result["sezioni"]["ce"]["righe"]) == 1
        assert result["confidence_estrazione"] > 0

    @patch("agents.estrattore_pdf_docling.crea_client")
    def test_mapping_sp_only(self, mock_client):
        """Se non ci sono righe CE, fa solo la chiamata SP (no retry se quadra)."""
        risposta_sp = {
            "sp_attivo": {"righe": [
                {"label": "A", "valori": {"2024": "100"}, "livello": "dettaglio"},
                {"label": "Totale attivo", "valori": {"2024": "100"}, "livello": "totale"},
            ]},
            "sp_passivo": {"righe": [
                {"label": "Totale passivo e patrimonio netto", "valori": {"2024": "100"}, "livello": "totale"},
            ]},
            "problemi": [],
        }
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text=json.dumps(risposta_sp))]
        mock_client.return_value.messages.create.return_value = mock_resp

        result = _mapping_semantico(
            sp_righe=[{"label": "A", "valori": {"2024": "100"}}],
            ce_righe=[],
            formato="IFRS",
            anni=["2024"],
        )

        assert len(result["sezioni"]["sp_attivo"]["righe"]) == 2
        assert len(result["sezioni"]["ce"]["righe"]) == 0
        # Solo 1 chiamata (SP), no retry perché quadra
        assert mock_client.return_value.messages.create.call_count == 1

    @patch("agents.estrattore_pdf_docling.crea_client")
    def test_mapping_llm_error_graceful(self, mock_client):
        """Se una chiamata LLM fallisce, l'altra continua."""
        risposta_ce = {
            "ce": {"righe": [{"label": "R", "valori": {"2024": "5000"}, "livello": "dettaglio"}]},
            "problemi": [],
        }
        mock_resp_sp = MagicMock()
        mock_resp_sp.content = [MagicMock(text="non json")]
        mock_resp_ce = MagicMock()
        mock_resp_ce.content = [MagicMock(text=json.dumps(risposta_ce))]
        mock_client.return_value.messages.create.side_effect = [mock_resp_sp, mock_resp_ce]

        result = _mapping_semantico(
            sp_righe=[{"label": "A", "valori": {"2024": "1"}}],
            ce_righe=[{"label": "R", "valori": {"2024": "5000"}}],
            formato="IFRS",
            anni=["2024"],
        )

        # SP fallita ma CE ok
        assert len(result["sezioni"]["sp_attivo"]["righe"]) == 0
        assert len(result["sezioni"]["ce"]["righe"]) == 1
        assert any("SP fallito" in p for p in result["problemi_layout"])


class TestPipelineCompleta:
    """Test per estrai_pdf_docling end-to-end (tutto mockato)."""

    @patch("agents.estrattore_pdf_docling.classifica_pagine")
    @patch("agents.estrattore_pdf_docling._valida_estrazione")
    @patch("agents.estrattore_pdf_docling._mapping_semantico")
    @patch("agents.estrattore_pdf_docling._estrai_struttura")
    def test_pipeline_ok(self, mock_struttura, mock_mapping, mock_valida, mock_recon):
        mock_recon.return_value = _mock_profile()
        mock_struttura.return_value = {
            "sp_righe": [{"label": "V", "valori": {"2024": "1"}}],
            "ce_righe": [{"label": "R", "valori": {"2024": "2"}}],
            "sp_pagine": [52],
            "ce_pagine": [54],
            "anni_presenti": ["2024"],
            "formato": "IFRS",
        }
        mock_mapping.return_value = {
            "azienda": "Test",
            "sezioni": {
                "sp_attivo": {"pagine": [], "righe": []},
                "sp_passivo": {"pagine": [], "righe": []},
                "ce": {"pagine": [], "righe": []},
            },
            "confidence_estrazione": 0.92,
        }
        mock_valida.return_value = []

        result = estrai_pdf_docling("fake.pdf")

        assert "error" not in result
        assert result["confidence_estrazione"] == 0.92
        # Pagine arricchite
        assert result["sezioni"]["sp_attivo"]["pagine"] == [52]
        assert result["sezioni"]["ce"]["pagine"] == [54]
        # ExtractionBundle included
        assert "bundle" in result
        bundle = result["bundle"]
        assert bundle.document_profile.company_name == "Test"
        assert bundle.document_profile.accounting_standard == "IFRS"

    @patch("agents.estrattore_pdf_docling.classifica_pagine")
    @patch("agents.estrattore_pdf_docling._estrai_struttura")
    def test_pipeline_nessun_prospetto(self, mock_struttura, mock_recon):
        mock_recon.return_value = _mock_profile()
        mock_struttura.return_value = {
            "sp_righe": [],
            "ce_righe": [],
            "sp_pagine": [],
            "ce_pagine": [],
            "anni_presenti": [],
            "formato": "IFRS",
        }

        result = estrai_pdf_docling("fake.pdf")
        assert "error" in result

    @patch("agents.estrattore_pdf_docling.classifica_pagine")
    @patch("agents.estrattore_pdf_docling._valida_estrazione")
    @patch("agents.estrattore_pdf_docling._mapping_semantico")
    @patch("agents.estrattore_pdf_docling._estrai_struttura")
    def test_pipeline_con_problemi_validazione(self, mock_struttura, mock_mapping, mock_valida, mock_recon):
        mock_recon.return_value = _mock_profile()
        mock_struttura.return_value = {
            "sp_righe": [{"label": "V", "valori": {"2024": "1"}}],
            "ce_righe": [],
            "sp_pagine": [52],
            "ce_pagine": [],
            "anni_presenti": ["2024"],
            "formato": "IFRS",
        }
        mock_mapping.return_value = {
            "sezioni": {
                "sp_attivo": {"pagine": [], "righe": []},
                "sp_passivo": {"pagine": [], "righe": []},
                "ce": {"pagine": [], "righe": []},
            },
        }
        mock_valida.return_value = ["[2024] Quadratura SP fallita"]

        result = estrai_pdf_docling("fake.pdf")
        assert "problemi_layout" in result
        assert len(result["problemi_layout"]) == 1
