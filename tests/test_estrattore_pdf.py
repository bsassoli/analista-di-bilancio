"""Test per le funzioni deterministiche di agents/estrattore_pdf.py."""

import pytest

from agents.estrattore_pdf import _pagina_e_prospetto, _rileva_formato, _seleziona_gruppo_prospetto


# ---------------------------------------------------------------------------
# Helpers per generare testi realistici
# ---------------------------------------------------------------------------

def _testo_sp_attivo():
    """Testo realistico di una pagina SP attivo (IFRS)."""
    lines = [
        "STATO PATRIMONIALE",
        "                                           31.12.2024    31.12.2023",
        "Attivo                                                             ",
        "Attivita non correnti                                              ",
        "Totale immobilizzazioni materiali          12.345.678     11.234.567",
        "Totale immobilizzazioni immateriali         3.456.789      3.234.567",
        "Totale immobilizzazioni finanziarie         1.234.567      1.123.456",
        "Totale attivita non correnti               17.037.034     15.592.590",
        "Attivita correnti                                                  ",
        "Rimanenze                                   5.678.901      5.234.567",
        "Crediti commerciali                          4.567.890      4.123.456",
        "Disponibilita liquide                        2.345.678      2.123.456",
        "Totale attivita correnti                    12.592.469     11.481.479",
        "Totale attivo                               29.629.503     27.074.069",
    ]
    return "\n".join(lines)


def _testo_sp_passivo():
    """Testo realistico di una pagina SP passivo."""
    lines = [
        "STATO PATRIMONIALE — PASSIVO",
        "                                           31.12.2024    31.12.2023",
        "Patrimonio netto                                                   ",
        "Capitale sociale                             5.000.000      5.000.000",
        "Riserve                                      8.234.567      7.654.321",
        "Utile d'esercizio                            1.234.567      1.123.456",
        "Totale patrimonio netto                     14.469.134     13.777.777",
        "Passivita non correnti                                             ",
        "Finanziamenti a lungo termine                3.456.789      3.234.567",
        "Totale passivita non correnti                4.567.890      4.234.567",
        "Passivita correnti                                                 ",
        "Debiti commerciali                           5.678.901      5.234.567",
        "Totale passivita correnti                   10.592.479      9.061.725",
        "Totale passivo                              29.629.503     27.074.069",
    ]
    return "\n".join(lines)


def _testo_ce():
    """Testo realistico di una pagina CE."""
    lines = [
        "CONTO ECONOMICO",
        "                                           31.12.2024    31.12.2023",
        "Ricavi delle vendite                        25.678.901     24.234.567",
        "Costi materie prime                        (12.345.678)   (11.234.567)",
        "Costi per servizi                           (5.678.901)    (5.234.567)",
        "Costi del personale                         (3.456.789)    (3.234.567)",
        "EBITDA                                       4.197.533      4.530.866",
        "Ammortamenti                                (1.234.567)    (1.123.456)",
        "Risultato operativo                          2.962.966      3.407.410",
        "Proventi finanziari                            123.456        112.345",
        "Oneri finanziari                              (234.567)      (212.345)",
        "Risultato prima delle imposte                2.851.855      3.307.410",
        "Imposte                                       (800.000)      (750.000)",
        "Risultato netto d'esercizio                  2.051.855      2.557.410",
    ]
    return "\n".join(lines)


def _testo_generico():
    """Testo discorsivo senza contenuto contabile."""
    return (
        "La presente relazione illustra l'andamento della gestione. "
        "Il mercato ha mostrato segnali di ripresa nel corso dell'anno. "
        "L'azienda ha continuato a investire in ricerca e sviluppo."
    )


# ---------------------------------------------------------------------------
# TestPaginaEProspetto
# ---------------------------------------------------------------------------

class TestPaginaEProspetto:

    def test_sp_attivo_con_numeri(self):
        result = _pagina_e_prospetto(_testo_sp_attivo())
        assert result["tipo"] == "sp_attivo"
        assert result["score"] > 0

    def test_sp_passivo_con_numeri(self):
        result = _pagina_e_prospetto(_testo_sp_passivo())
        assert result["tipo"] == "sp_passivo"
        assert result["score"] > 0

    def test_ce_con_numeri(self):
        result = _pagina_e_prospetto(_testo_ce())
        assert result["tipo"] == "ce"
        assert result["score"] > 0

    def test_testo_generico_nessun_tipo(self):
        result = _pagina_e_prospetto(_testo_generico())
        assert result["tipo"] is None
        assert result["score"] == 0

    def test_testo_vuoto(self):
        result = _pagina_e_prospetto("")
        assert result["tipo"] is None
        assert result["score"] == 0

    def test_testo_none_like(self):
        # Empty string
        result = _pagina_e_prospetto("   ")
        # Should return None tipo since no financial content
        assert result["tipo"] is None


# ---------------------------------------------------------------------------
# TestRilevaFormato
# ---------------------------------------------------------------------------

class TestRilevaFormato:

    def test_ifrs_detection(self):
        testi = [
            {"testo": "Le attivita non correnti includono immobilizzazioni secondo IFRS"},
            {"testo": "attivita correnti come da IAS 1"},
        ]
        assert _rileva_formato(testi) == "IFRS"

    def test_oic_detection(self):
        testi = [
            {"testo": "A) Valore della produzione"},
            {"testo": "B) Costi della produzione"},
        ]
        assert _rileva_formato(testi) == "OIC_ordinario"

    def test_mixed_signals_more_ifrs(self):
        testi = [
            {"testo": "attivita non correnti secondo IFRS"},
            {"testo": "attivita correnti ias 1"},
            {"testo": "valore della produzione"},
        ]
        # 2 IFRS signals vs 1 OIC
        assert _rileva_formato(testi) == "IFRS"

    def test_mixed_signals_more_oic(self):
        testi = [
            {"testo": "valore della produzione"},
            {"testo": "costi della produzione"},
            {"testo": "b) immobilizzazioni"},
            {"testo": "attivita non correnti"},
        ]
        # 3 OIC vs 1 IFRS
        assert _rileva_formato(testi) == "OIC_ordinario"

    def test_empty_testi(self):
        # No signals at all => IFRS wins tie (0 > 0 is false, so OIC)
        result = _rileva_formato([{"testo": "nessun segnale"}])
        assert result == "OIC_ordinario"


# ---------------------------------------------------------------------------
# TestSelezionaGruppoProspetto
# ---------------------------------------------------------------------------

class TestSelezionaGruppoProspetto:

    def test_single_group_returns_pages(self):
        candidati = [
            {"pagina": 10, "tipo": "sp_attivo", "score": 5},
            {"pagina": 11, "tipo": "sp_passivo", "score": 4},
        ]
        result = _seleziona_gruppo_prospetto(candidati, "separato", 100)
        assert result == [10, 11]

    def test_multiple_groups_separato_picks_later(self):
        # Two groups far apart
        candidati = [
            {"pagina": 5, "tipo": "sp_attivo", "score": 6},
            {"pagina": 6, "tipo": "sp_passivo", "score": 6},
            {"pagina": 50, "tipo": "sp_attivo", "score": 6},
            {"pagina": 51, "tipo": "sp_passivo", "score": 6},
        ]
        result = _seleziona_gruppo_prospetto(candidati, "separato", 100)
        assert 50 in result and 51 in result
        assert 5 not in result

    def test_multiple_groups_consolidato_picks_earlier(self):
        candidati = [
            {"pagina": 5, "tipo": "sp_attivo", "score": 6},
            {"pagina": 6, "tipo": "sp_passivo", "score": 6},
            {"pagina": 50, "tipo": "sp_attivo", "score": 6},
            {"pagina": 51, "tipo": "sp_passivo", "score": 6},
        ]
        result = _seleziona_gruppo_prospetto(candidati, "consolidato", 100)
        assert 5 in result and 6 in result
        assert 50 not in result

    def test_empty_candidati(self):
        result = _seleziona_gruppo_prospetto([], "separato", 100)
        assert result == []
