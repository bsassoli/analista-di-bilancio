"""Test per i validatori."""

import pytest
from tools.validatori import (
    calcola_severity,
    valida_quadratura_sp,
    valida_coerenza_utile,
    valida_schema_normalizzato,
)


class TestCalcolaSeverity:
    def test_tutto_ok(self):
        checks = [
            {"severity_contributo": "ok"},
            {"severity_contributo": "ok"},
        ]
        sev, score = calcola_severity(checks)
        assert sev == "ok"
        assert score == 1.0

    def test_con_warning(self):
        checks = [
            {"severity_contributo": "ok"},
            {"severity_contributo": "warning"},
        ]
        sev, score = calcola_severity(checks)
        assert sev == "warning"
        assert score == 0.95

    def test_con_critical(self):
        checks = [
            {"severity_contributo": "ok"},
            {"severity_contributo": "critical"},
        ]
        sev, score = calcola_severity(checks)
        assert sev == "critical"
        assert score == 0.7

    def test_multipli_warning(self):
        checks = [{"severity_contributo": "warning"}] * 5
        sev, score = calcola_severity(checks)
        assert sev == "warning"
        assert score == 0.75

    def test_floor_zero(self):
        checks = [{"severity_contributo": "critical"}] * 10
        sev, score = calcola_severity(checks)
        assert sev == "critical"
        assert score == 0.0


class TestValidaQuadraturaSP:
    def test_quadra(self):
        schema = {
            "metadata": {
                "totale_attivo_dichiarato": {"2023": 15_000_000},
                "totale_passivo_dichiarato": {"2023": 15_000_000},
            }
        }
        r = valida_quadratura_sp(schema, "2023")
        assert r["esito"] == "pass"

    def test_non_quadra_critical(self):
        schema = {
            "metadata": {
                "totale_attivo_dichiarato": {"2023": 15_000_000},
                "totale_passivo_dichiarato": {"2023": 12_000_000},
            }
        }
        r = valida_quadratura_sp(schema, "2023")
        assert r["esito"] == "fail"
        assert r["severity_contributo"] == "critical"

    def test_dati_mancanti(self):
        schema = {"metadata": {}}
        r = valida_quadratura_sp(schema, "2023")
        assert r["esito"] == "warn"


class TestValidaSchemaNormalizzato:
    def test_schema_vuoto(self):
        issues = valida_schema_normalizzato({"sp": [], "ce": []})
        # Nessuna issue critica per sezioni vuote (non assenti)
        assert all(i["codice"] != "COMPLETEZZA_SP" or i["severity"] != "critical" for i in issues)

    def test_sp_assente(self):
        issues = valida_schema_normalizzato({"ce": [{"id": "test", "valore": {"2023": 100}}]})
        critical = [i for i in issues if i["severity"] == "critical"]
        assert len(critical) >= 1

    def test_duplicati(self):
        schema = {
            "sp": [
                {"id": "voce_a", "valore": {"2023": 100}},
                {"id": "voce_a", "valore": {"2023": 200}},
            ],
            "ce": [],
        }
        issues = valida_schema_normalizzato(schema)
        dup_issues = [i for i in issues if i["codice"] == "DUPLICATI"]
        assert len(dup_issues) == 1
