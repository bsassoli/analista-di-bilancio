"""Test per il parser PDF e utilità correlate."""

import pytest
from tools.pdf_parser import normalizza_numero, genera_id, identifica_sezione


class TestNormalizzaNumero:
    def test_intero_semplice(self):
        assert normalizza_numero("1250000") == 1250000

    def test_con_punti_migliaia(self):
        assert normalizza_numero("1.250.000") == 1250000

    def test_negativo_parentesi(self):
        assert normalizza_numero("(350.000)") == -350000

    def test_negativo_segno(self):
        assert normalizza_numero("-350.000") == -350000

    def test_con_decimali(self):
        assert normalizza_numero("1.250.000,50") == 1250000

    def test_trattino(self):
        assert normalizza_numero("-") == 0
        assert normalizza_numero("–") == 0
        assert normalizza_numero("—") == 0

    def test_vuoto(self):
        assert normalizza_numero("") == 0
        assert normalizza_numero(None) == 0

    def test_asterischi(self):
        assert normalizza_numero("***") is None

    def test_zero(self):
        assert normalizza_numero("0") == 0

    def test_spazi(self):
        assert normalizza_numero("  1.250.000  ") == 1250000

    def test_piccolo_numero(self):
        assert normalizza_numero("42") == 42

    def test_centomila(self):
        assert normalizza_numero("100.000") == 100000


class TestGeneraId:
    def test_semplice(self):
        assert genera_id("Immobilizzazioni materiali") == "immobilizzazioni_materiali"

    def test_con_riferimento(self):
        assert genera_id("II - Immobilizzazioni materiali") == "immobilizzazioni_materiali"

    def test_con_parentesi(self):
        assert genera_id("Utile (perdita) dell'esercizio") == "utile_dell_esercizio"

    def test_con_accenti(self):
        assert genera_id("Disponibilità liquide") == "disponibilità_liquide"


class TestIdentificaSezione:
    def test_sp(self):
        assert identifica_sezione("STATO PATRIMONIALE ATTIVO") == "sp"

    def test_ce(self):
        assert identifica_sezione("CONTO ECONOMICO") == "ce"

    def test_nota_integrativa(self):
        assert identifica_sezione("NOTA INTEGRATIVA al bilancio") == "nota_integrativa"

    def test_relazione(self):
        assert identifica_sezione("Relazione sulla gestione") == "relazione_gestione"

    def test_nessuna(self):
        assert identifica_sezione("Pagina generica con testo") is None

    def test_filtro_tipo(self):
        assert identifica_sezione("STATO PATRIMONIALE", tipo="sp") == "sp"
        assert identifica_sezione("STATO PATRIMONIALE", tipo="ce") is None
