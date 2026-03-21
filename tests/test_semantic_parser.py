"""Tests for tools.semantic_parser — deterministic semantic extraction."""

from tools.semantic_parser import (
    _cerca_importo_vicino,
    _cerca_pattern,
    _estrai_snippet,
    estrai_evidenze_deterministiche,
)


class TestHelpers:
    def test_cerca_importo_vicino_found(self):
        testo = "Il fondo ammonta a 1.500.000 euro"
        val = _cerca_importo_vicino(testo, 10, raggio=200)
        assert val == 1500000

    def test_cerca_importo_vicino_none(self):
        testo = "Nessun importo qui"
        val = _cerca_importo_vicino(testo, 5, raggio=50)
        assert val is None

    def test_estrai_snippet(self):
        testo = "A" * 100 + "KEYWORD" + "B" * 100
        snippet = _estrai_snippet(testo, 100, raggio=20)
        assert "KEYWORD" in snippet
        assert len(snippet) <= 300

    def test_cerca_pattern(self):
        testo = "La scadenza dei debiti e la ripartizione dei debiti"
        matches = _cerca_pattern(testo, [r"scadenza\s+dei\s+debiti", r"ripartizione\s+dei\s+debiti"])
        assert len(matches) == 2
        assert matches[0][0] < matches[1][0]  # sorted by position

    def test_cerca_pattern_case_insensitive(self):
        testo = "FONDI PER RISCHI E ONERI"
        matches = _cerca_pattern(testo, [r"fondi\s+per\s+rischi"])
        assert len(matches) == 1


class TestDebtExtraction:
    def test_finds_debt_maturity(self):
        testi = [{"pagina": 72, "testo":
            "Scadenza dei debiti\n"
            "Debiti entro l'esercizio successivo: 5.500.000\n"
            "Debiti oltre cinque anni: 800.000"}]
        evidenze = estrai_evidenze_deterministiche(testi, [72])
        debt = [e for e in evidenze if e.evidence_type == "debt"]
        assert len(debt) >= 1
        assert debt[0].source_page == 72
        assert debt[0].confidence >= 0.7


class TestLeaseExtraction:
    def test_finds_ifrs16(self):
        testi = [{"pagina": 80, "testo":
            "I diritti d'uso ai sensi dell'IFRS 16 ammontano a 3.500.000 euro.\n"
            "Le passività per leasing sono pari a 3.200.000 euro."}]
        evidenze = estrai_evidenze_deterministiche(testi, [80])
        lease = [e for e in evidenze if e.evidence_type == "lease"]
        assert len(lease) >= 1
        assert any("IFRS" in e.snippet or "diritti" in e.snippet for e in lease)


class TestFundExtraction:
    def test_finds_fund_operativo(self):
        testi = [{"pagina": 75, "testo":
            "Il fondo garanzia prodotti è pari a 150.000 euro per obbligazioni contrattuali."}]
        evidenze = estrai_evidenze_deterministiche(testi, [75])
        fund = [e for e in evidenze if e.evidence_type == "fund"]
        assert len(fund) >= 1
        assert fund[0].normalized_hint.get("natura") == "operativo"


class TestRelatedPartyExtraction:
    def test_finds_related_party(self):
        testi = [{"pagina": 78, "testo":
            "Rapporti con parti correlate: crediti verso controllate 1.200.000"}]
        evidenze = estrai_evidenze_deterministiche(testi, [78])
        rp = [e for e in evidenze if e.evidence_type == "related_party"]
        assert len(rp) >= 1


class TestGoingConcernExtraction:
    def test_finds_going_concern(self):
        testi = [{"pagina": 10, "testo":
            "Gli amministratori hanno valutato la continuità aziendale. "
            "Non sussistono dubbi sulla continuità aziendale della società."}]
        evidenze = estrai_evidenze_deterministiche(testi, [10])
        gc = [e for e in evidenze if e.evidence_type == "going_concern"]
        assert len(gc) >= 1
        assert gc[0].confidence == 0.95


class TestAccountingPolicyExtraction:
    def test_finds_inventory_method(self):
        testi = [{"pagina": 65, "testo":
            "Criteri di valutazione\n"
            "Le rimanenze sono valutate secondo il metodo FIFO."}]
        evidenze = estrai_evidenze_deterministiche(testi, [65])
        ap = [e for e in evidenze if e.evidence_type == "accounting_policy"]
        assert len(ap) >= 1
        assert ap[0].normalized_hint.get("metodo", "").lower() == "fifo"


class TestNonRecurringExtraction:
    def test_finds_impairment(self):
        testi = [{"pagina": 90, "testo":
            "È stata rilevata una svalutazione per impairment di 500.000 euro."}]
        evidenze = estrai_evidenze_deterministiche(testi, [90])
        nr = [e for e in evidenze if e.evidence_type == "non_recurring"]
        assert len(nr) >= 1


class TestFiltersByNIPages:
    def test_ignores_non_ni_pages(self):
        testi = [
            {"pagina": 10, "testo": "Fondi per rischi e oneri per 100.000 euro"},
            {"pagina": 72, "testo": "Fondi per rischi e oneri per 200.000 euro"},
        ]
        # Only page 72 is NI
        evidenze = estrai_evidenze_deterministiche(testi, [72])
        assert all(e.source_page == 72 for e in evidenze)

    def test_empty_input(self):
        assert estrai_evidenze_deterministiche([], []) == []
