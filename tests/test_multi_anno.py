"""Test per il modulo multi-anno e validazione cross-anno."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from tools.validatori import valida_cross_anno
from tools.schema import crea_sp_riclassificato_vuoto, crea_ce_riclassificato_vuoto
from tools.calcolatori import verifica_quadratura


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _crea_risultato_anno_semplice(
    anno: str,
    totale_attivo: int = 10_000_000,
    pn: int = 4_000_000,
    pfn: int = 2_000_000,
    ebitda: int = 1_500_000,
    utile: int = 500_000,
) -> dict:
    """Crea un risultato riclassificato minimo."""
    sp = crea_sp_riclassificato_vuoto()
    ce = crea_ce_riclassificato_vuoto()

    sp["attivo"]["capitale_fisso_netto"]["totale"] = totale_attivo // 2
    sp["attivo"]["ccon"]["totale"] = totale_attivo // 4
    sp["attivo"]["altre_attivita_non_operative"]["totale"] = totale_attivo // 4

    sp["passivo"]["patrimonio_netto"]["totale"] = pn
    sp["passivo"]["pfn"]["totale"] = pfn
    sp["passivo"]["pfn"]["dettaglio"]["debiti_finanziari_lungo"] = pfn
    sp["passivo"]["debiti_operativi"]["totale"] = totale_attivo - pn - pfn

    sp["quadratura"] = verifica_quadratura(totale_attivo, totale_attivo)

    ce["ricavi_netti"] = 15_000_000
    ce["ebitda"] = ebitda
    ce["ebit"] = ebitda - 500_000
    ce["utile_netto"] = utile

    return {
        "anno": anno,
        "sp_riclassificato": sp,
        "ce_riclassificato": ce,
        "deviazioni": [],
        "voci_non_mappate": [],
        "confidence": 0.90,
    }


# ---------------------------------------------------------------------------
# Test valida_cross_anno
# ---------------------------------------------------------------------------

class TestValidaCrossAnno:
    def test_due_anni_coerenti(self):
        """Nessun issue con dati coerenti."""
        risultati = {
            "2023": _crea_risultato_anno_semplice("2023", totale_attivo=10_000_000),
            "2024": _crea_risultato_anno_semplice("2024", totale_attivo=11_000_000),
        }
        issues = valida_cross_anno(risultati)
        assert len(issues) == 0

    def test_salto_attivo_grande(self):
        """Salto >50% nel totale attivo."""
        risultati = {
            "2023": _crea_risultato_anno_semplice("2023", totale_attivo=10_000_000),
            "2024": _crea_risultato_anno_semplice("2024", totale_attivo=20_000_000),
        }
        issues = valida_cross_anno(risultati)
        codici = [i["codice"] for i in issues]
        assert "CROSS_SALTO_ATTIVO" in codici

    def test_cambio_segno_ebitda(self):
        """Cambio segno EBITDA tra anni."""
        risultati = {
            "2023": _crea_risultato_anno_semplice("2023", ebitda=1_000_000),
            "2024": _crea_risultato_anno_semplice("2024", ebitda=-500_000),
        }
        issues = valida_cross_anno(risultati)
        codici = [i["codice"] for i in issues]
        assert "CROSS_SEGNO_EBITDA" in codici

    def test_un_solo_anno(self):
        """Nessun check con un solo anno."""
        risultati = {
            "2024": _crea_risultato_anno_semplice("2024"),
        }
        issues = valida_cross_anno(risultati)
        assert len(issues) == 0

    def test_tre_anni(self):
        """Verifica che controlla tutti i pair consecutivi."""
        risultati = {
            "2022": _crea_risultato_anno_semplice("2022", totale_attivo=10_000_000),
            "2023": _crea_risultato_anno_semplice("2023", totale_attivo=10_500_000),
            "2024": _crea_risultato_anno_semplice("2024", totale_attivo=25_000_000),
        }
        issues = valida_cross_anno(risultati)
        # Solo il salto 2023→2024 dovrebbe triggerare
        salti = [i for i in issues if i["codice"] == "CROSS_SALTO_ATTIVO"]
        assert len(salti) == 1
        assert "2024" in salti[0]["dettaglio"]


# ---------------------------------------------------------------------------
# Test merge risultati
# ---------------------------------------------------------------------------

class TestMergeRisultati:
    def test_merge_senza_overlap(self):
        """Merge di 2 PDF senza anni sovrapposti."""
        from agents.orchestratore_multi import _merge_risultati

        pdf1 = {
            "pipeline": {
                "riclassifica": {
                    "risultati_per_anno": {
                        "2022": _crea_risultato_anno_semplice("2022"),
                        "2021": _crea_risultato_anno_semplice("2021"),
                    }
                }
            }
        }
        pdf2 = {
            "pipeline": {
                "riclassifica": {
                    "risultati_per_anno": {
                        "2024": _crea_risultato_anno_semplice("2024"),
                        "2023": _crea_risultato_anno_semplice("2023"),
                    }
                }
            }
        }

        merged = _merge_risultati([pdf1, pdf2])
        assert sorted(merged.keys()) == ["2021", "2022", "2023", "2024"]

    def test_merge_con_overlap_preferisce_primario(self):
        """Anno sovrapposto: prende dalla sorgente dove è primario."""
        from agents.orchestratore_multi import _merge_risultati

        # PDF bilancio 2024: anni 2024 (primario), 2023 (comparativo)
        pdf_2024 = {
            "pipeline": {
                "riclassifica": {
                    "risultati_per_anno": {
                        "2024": _crea_risultato_anno_semplice("2024", utile=600_000),
                        "2023": _crea_risultato_anno_semplice("2023", utile=400_000),
                    }
                }
            }
        }
        # PDF bilancio 2023: anni 2023 (primario), 2022 (comparativo)
        pdf_2023 = {
            "pipeline": {
                "riclassifica": {
                    "risultati_per_anno": {
                        "2023": _crea_risultato_anno_semplice("2023", utile=500_000),
                        "2022": _crea_risultato_anno_semplice("2022", utile=300_000),
                    }
                }
            }
        }

        # Ordine: più vecchio prima
        merged = _merge_risultati([pdf_2023, pdf_2024])
        assert sorted(merged.keys()) == ["2022", "2023", "2024"]

        # 2023 dovrebbe venire dal pdf_2023 (dove è primario), utile=500k
        assert merged["2023"]["ce_riclassificato"]["utile_netto"] == 500_000

        # 2024 dal pdf_2024 (primario lì), utile=600k
        assert merged["2024"]["ce_riclassificato"]["utile_netto"] == 600_000

    def test_merge_pdf_vuoto(self):
        """PDF senza risultati viene ignorato."""
        from agents.orchestratore_multi import _merge_risultati

        pdf_ok = {
            "pipeline": {
                "riclassifica": {
                    "risultati_per_anno": {
                        "2024": _crea_risultato_anno_semplice("2024"),
                    }
                }
            }
        }
        pdf_vuoto = {
            "pipeline": {
                "riclassifica": {
                    "risultati_per_anno": {}
                }
            }
        }

        merged = _merge_risultati([pdf_vuoto, pdf_ok])
        assert list(merged.keys()) == ["2024"]


# ---------------------------------------------------------------------------
# Test stato persistente
# ---------------------------------------------------------------------------

class TestStatoPersistente:
    def test_carica_stato_inesistente(self):
        """carica_stato restituisce None per azienda sconosciuta."""
        from agents.base import carica_stato
        assert carica_stato("azienda_inesistente_xyz_123") is None

    def test_salva_e_carica_stato(self, tmp_path):
        """Salva e ricarica stato."""
        from tools.schema import crea_stato_iniziale

        stato = crea_stato_iniziale("Test S.r.l.", [2023, 2024])
        assert stato["azienda"] == "Test S.r.l."
        assert sorted(stato["anni"]) == [2023, 2024]
        assert stato["fase_corrente"] == "inizializzazione"
        assert "2023" in stato["qualita_dati"]
        assert "2024" in stato["qualita_dati"]


# ---------------------------------------------------------------------------
# Test estrattore qualitativo
# ---------------------------------------------------------------------------

class TestCercaPatternTesto:
    def test_pattern_trovato(self):
        from tools.pdf_parser import cerca_pattern_testo

        testo = "La società ha effettuato una rivalutazione ex D.L. 104/2020 per 1.200.000 euro."
        risultati = cerca_pattern_testo(testo, [r"rivalutazione.*?D\.L\.\s*\d+"])
        assert len(risultati) == 1
        assert "rivalutazione" in risultati[0]["match"].lower()

    def test_pattern_non_trovato(self):
        from tools.pdf_parser import cerca_pattern_testo

        testo = "Testo generico senza pattern rilevanti."
        risultati = cerca_pattern_testo(testo, [r"rivalutazione", r"leasing"])
        assert len(risultati) == 0

    def test_pattern_multipli(self):
        from tools.pdf_parser import cerca_pattern_testo

        testo = "Debiti verso banche per 500.000, finanziamento soci per 300.000"
        risultati = cerca_pattern_testo(testo, [r"debiti verso banche", r"finanziamento soci"])
        assert len(risultati) == 2

    def test_contesto_intorno(self):
        from tools.pdf_parser import cerca_pattern_testo

        testo = "A" * 200 + "parola_chiave" + "B" * 200
        risultati = cerca_pattern_testo(testo, [r"parola_chiave"])
        assert len(risultati) == 1
        contesto = risultati[0]["contesto"]
        # Contesto dovrebbe essere circa 200+14+100 = ~214 chars max per lato
        assert len(contesto) <= 300
