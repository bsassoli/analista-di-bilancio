"""Test per valida_subtotali e valida_riconciliazione_ce."""

import pytest
from tools.validatori import valida_subtotali, valida_riconciliazione_ce


class TestValidaSubtotali:
    def _schema_con_totali(self, totale_val, figli_vals):
        """Crea schema con un totale e figli nel SP."""
        figli = [
            {"id": f"voce_{i}", "label": f"Voce {i}", "livello": 3,
             "valore": {"2024": v}} for i, v in enumerate(figli_vals)
        ]
        totale = {
            "id": "totale_attivo", "label": "Totale attivo", "livello": 1,
            "valore": {"2024": totale_val},
        }
        return {"sp": figli + [totale], "ce": []}

    def test_subtotali_coerenti(self):
        schema = self._schema_con_totali(1_000_000, [600_000, 400_000])
        issues = valida_subtotali(schema)
        assert len(issues) == 0

    def test_subtotali_incoerenti(self):
        # Totale dice 1M ma figli sommano 500k (delta 50%)
        schema = self._schema_con_totali(1_000_000, [300_000, 200_000])
        issues = valida_subtotali(schema)
        assert len(issues) >= 1
        assert issues[0]["codice"] == "SUBTOTALE_INCOERENTE"

    def test_subtotali_tolleranza(self):
        # Delta piccolo (~4.8%) sotto soglia 5%
        schema = self._schema_con_totali(1_000_000, [520_000, 432_000])
        issues = valida_subtotali(schema)
        assert len(issues) == 0

    def test_nessun_totale(self):
        schema = {
            "sp": [
                {"id": "voce_a", "label": "Voce A", "livello": 3,
                 "valore": {"2024": 100_000}},
            ],
            "ce": [],
        }
        issues = valida_subtotali(schema)
        assert len(issues) == 0

    def test_totale_zero(self):
        schema = self._schema_con_totali(0, [100_000, 200_000])
        issues = valida_subtotali(schema)
        assert len(issues) == 0  # Totale zero = skip


class TestValidaRiconciliazioneCE:
    def _schema_ce(self, ricavi, costi, utile):
        return {
            "anni_estratti": [2024],
            "ce": [
                {"id": "ricavi", "label": "Ricavi vendite", "livello": 1,
                 "valore": {"2024": ricavi}},
                {"id": "costi_mp", "label": "Costi materie prime", "livello": 2,
                 "valore": {"2024": costi}},
                {"id": "utile", "label": "Utile (perdita) dell'esercizio", "livello": 1,
                 "valore": {"2024": utile}},
            ],
            "metadata": {"utile_dichiarato": {"2024": utile}},
        }

    def test_riconciliazione_ok(self):
        # ricavi + costi = 10M + (-9.6M) = 400k = utile
        schema = self._schema_ce(10_000_000, -9_600_000, 400_000)
        issues = valida_riconciliazione_ce(schema)
        assert len(issues) == 0

    def test_riconciliazione_ko(self):
        # ricavi + costi = 10M + (-5M) = 5M, ma utile dichiarato = 400k
        schema = self._schema_ce(10_000_000, -5_000_000, 400_000)
        issues = valida_riconciliazione_ce(schema)
        assert len(issues) >= 1
        assert issues[0]["codice"] == "CE_RICONCILIAZIONE"

    def test_nessun_dato(self):
        schema = {"anni_estratti": [2024], "ce": [], "metadata": {}}
        issues = valida_riconciliazione_ce(schema)
        assert len(issues) == 0
