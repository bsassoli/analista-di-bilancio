"""Fixture condivise per tutti i test."""

import json
import pytest
from pathlib import Path

from tools.schema import crea_sp_riclassificato_vuoto, crea_ce_riclassificato_vuoto
from tools.calcolatori import calcola_ccon, calcola_pfn, verifica_quadratura


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _carica_fixture(nome: str) -> dict:
    return json.loads((FIXTURES_DIR / nome).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Schema normalizzato minimo 2 anni
# ---------------------------------------------------------------------------

@pytest.fixture
def schema_minimo_2anni():
    """Schema normalizzato con dati realistici da PMI italiana, 2 anni."""
    return {
        "azienda": "Test S.r.l.",
        "anni_estratti": [2024, 2023],
        "tipo_bilancio": "ordinario",
        "sp": [
            # Attivo
            {"id": "immobilizzazioni_immateriali", "label": "Immobilizzazioni immateriali", "livello": 2,
             "aggregato": "", "valore": {"2024": 500_000, "2023": 600_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "immobilizzazioni_materiali", "label": "Immobilizzazioni materiali", "livello": 2,
             "aggregato": "", "valore": {"2024": 3_000_000, "2023": 2_800_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "immobilizzazioni_finanziarie", "label": "Immobilizzazioni finanziarie", "livello": 2,
             "aggregato": "", "valore": {"2024": 200_000, "2023": 150_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "rimanenze", "label": "Rimanenze", "livello": 2,
             "aggregato": "", "valore": {"2024": 1_200_000, "2023": 1_100_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "crediti_commerciali", "label": "Crediti verso clienti", "livello": 2,
             "aggregato": "", "valore": {"2024": 2_000_000, "2023": 1_800_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "altri_crediti_operativi", "label": "Crediti tributari", "livello": 3,
             "aggregato": "", "valore": {"2024": 300_000, "2023": 250_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "attivita_fiscali_differite", "label": "Imposte anticipate", "livello": 3,
             "aggregato": "", "valore": {"2024": 100_000, "2023": 80_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "disponibilita_liquide", "label": "Disponibilita liquide", "livello": 2,
             "aggregato": "", "valore": {"2024": 800_000, "2023": 620_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "totale_attivo", "label": "Totale attivo", "livello": 1,
             "aggregato": "", "valore": {"2024": 8_100_000, "2023": 7_400_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            # Passivo
            {"id": "capitale_sociale", "label": "Capitale sociale", "livello": 3,
             "aggregato": "", "valore": {"2024": 500_000, "2023": 500_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "riserve", "label": "Riserve", "livello": 3,
             "aggregato": "", "valore": {"2024": 1_500_000, "2023": 1_300_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "utile_perdita_esercizio", "label": "Utile (perdita) dell'esercizio", "livello": 3,
             "aggregato": "", "valore": {"2024": 400_000, "2023": 350_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "totale_patrimonio_netto", "label": "Totale patrimonio netto", "livello": 1,
             "aggregato": "", "valore": {"2024": 2_400_000, "2023": 2_150_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "debiti_verso_banche_lungo", "label": "Debiti verso banche oltre", "livello": 3,
             "aggregato": "", "valore": {"2024": 1_500_000, "2023": 1_800_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "debiti_verso_banche_breve", "label": "Debiti verso banche entro", "livello": 3,
             "aggregato": "", "valore": {"2024": 500_000, "2023": 400_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "debiti_commerciali", "label": "Debiti verso fornitori", "livello": 2,
             "aggregato": "", "valore": {"2024": 1_800_000, "2023": 1_600_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "debiti_tributari", "label": "Debiti tributari", "livello": 3,
             "aggregato": "", "valore": {"2024": 300_000, "2023": 250_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "tfr", "label": "TFR", "livello": 2,
             "aggregato": "", "valore": {"2024": 400_000, "2023": 350_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "altri_debiti", "label": "Altri debiti", "livello": 3,
             "aggregato": "", "valore": {"2024": 400_000, "2023": 230_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "totale_passivo", "label": "Totale passivo e patrimonio netto", "livello": 1,
             "aggregato": "", "valore": {"2024": 8_100_000, "2023": 7_400_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
        ],
        "ce": [
            {"id": "ricavi_vendite_prestazioni", "label": "Ricavi delle vendite", "livello": 1,
             "aggregato": "", "valore": {"2024": 12_000_000, "2023": 11_000_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "altri_ricavi", "label": "Altri ricavi e proventi", "livello": 2,
             "aggregato": "", "valore": {"2024": 200_000, "2023": 150_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "costi_materie_prime", "label": "Costi per materie prime", "livello": 2,
             "aggregato": "", "valore": {"2024": -5_000_000, "2023": -4_500_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "costi_servizi", "label": "Costi per servizi", "livello": 2,
             "aggregato": "", "valore": {"2024": -2_500_000, "2023": -2_300_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "costi_personale", "label": "Costi del personale", "livello": 2,
             "aggregato": "", "valore": {"2024": -3_000_000, "2023": -2_800_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "ammortamenti", "label": "Ammortamenti e svalutazioni", "livello": 2,
             "aggregato": "", "valore": {"2024": -800_000, "2023": -750_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "proventi_finanziari", "label": "Proventi finanziari", "livello": 2,
             "aggregato": "", "valore": {"2024": 50_000, "2023": 30_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "oneri_finanziari", "label": "Oneri finanziari", "livello": 2,
             "aggregato": "", "valore": {"2024": -150_000, "2023": -130_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "imposte_sul_reddito", "label": "Imposte sul reddito", "livello": 2,
             "aggregato": "", "valore": {"2024": -200_000, "2023": -180_000},
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
            {"id": "utile_perdita_esercizio_ce", "label": "Utile (perdita) dell'esercizio", "livello": 1,
             "aggregato": "", "valore": {"2024": 400_000, "2023": 350_000},  # Note: this should be a subset but isn't used directly
             "fonte_riga_bilancio": "", "non_standard": False, "flags": [], "note": ""},
        ],
        "metadata": {
            "pagine_sp": [3, 4, 5],
            "pagine_ce": [6],
            "totale_attivo_dichiarato": {"2024": 8_100_000, "2023": 7_400_000},
            "totale_passivo_dichiarato": {"2024": 8_100_000, "2023": 7_400_000},
            "utile_dichiarato": {"2024": 400_000, "2023": 350_000},
            "formato": "OIC_ordinario",
        },
    }


# ---------------------------------------------------------------------------
# Pipeline result completo
# ---------------------------------------------------------------------------

def _crea_risultato_anno(anno: str, is_2024: bool) -> dict:
    """Crea un risultato riclassificato per un anno."""
    sp = crea_sp_riclassificato_vuoto()
    ce = crea_ce_riclassificato_vuoto()

    if is_2024:
        # SP attivo
        sp["attivo"]["capitale_fisso_netto"]["dettaglio"]["immobilizzazioni_materiali_nette"] = 3_000_000
        sp["attivo"]["capitale_fisso_netto"]["dettaglio"]["immobilizzazioni_immateriali_nette"] = 500_000
        sp["attivo"]["capitale_fisso_netto"]["dettaglio"]["immobilizzazioni_finanziarie"] = 200_000
        sp["attivo"]["capitale_fisso_netto"]["totale"] = 3_700_000
        sp["attivo"]["ccon"]["dettaglio"]["crediti_commerciali"] = 2_000_000
        sp["attivo"]["ccon"]["dettaglio"]["rimanenze"] = 1_200_000
        sp["attivo"]["ccon"]["dettaglio"]["altri_crediti_operativi"] = 300_000
        debiti_op = 2_500_000
        sp["attivo"]["ccon"]["dettaglio"]["debiti_operativi_sottratti"] = debiti_op
        sp["attivo"]["ccon"]["totale"] = calcola_ccon(2_000_000, 1_200_000, 300_000, debiti_op)
        sp["attivo"]["altre_attivita_non_operative"]["dettaglio"]["attivita_fiscali_differite"] = 100_000
        sp["attivo"]["altre_attivita_non_operative"]["totale"] = 100_000

        # SP passivo
        sp["passivo"]["patrimonio_netto"]["dettaglio"]["capitale_sociale"] = 500_000
        sp["passivo"]["patrimonio_netto"]["dettaglio"]["riserve"] = 1_500_000
        sp["passivo"]["patrimonio_netto"]["dettaglio"]["utile_perdita_esercizio"] = 400_000
        sp["passivo"]["patrimonio_netto"]["totale"] = 2_400_000
        sp["passivo"]["pfn"]["dettaglio"]["debiti_finanziari_lungo"] = 1_500_000
        sp["passivo"]["pfn"]["dettaglio"]["debiti_finanziari_breve"] = 500_000
        sp["passivo"]["pfn"]["dettaglio"]["disponibilita_liquide_sottratte"] = 800_000
        sp["passivo"]["pfn"]["totale"] = calcola_pfn(1_500_000, 500_000, 800_000)
        sp["passivo"]["debiti_operativi"]["totale"] = debiti_op

        totale_att = 3_700_000 + 2_000_000 + 1_200_000 + 300_000 + 100_000 + 800_000
        totale_pas = 2_400_000 + 1_500_000 + 500_000 + debiti_op
        sp["quadratura"] = verifica_quadratura(totale_att, totale_pas)

        # CE
        ce["ricavi_netti"] = 12_200_000
        ce["costi_materie_prime_merci"] = -5_000_000
        ce["valore_aggiunto_industriale"] = 7_200_000
        ce["costi_servizi_godimento"] = -2_500_000
        ce["costi_personale"] = -3_000_000
        ce["ebitda"] = 1_700_000
        ce["ammortamenti_svalutazioni"] = -800_000
        ce["ebit"] = 900_000
        ce["proventi_oneri_finanziari"] = -100_000
        ce["ebt"] = 800_000
        ce["imposte"] = -200_000
        ce["utile_netto"] = 400_000  # Note: doesn't perfectly add up but close enough for tests
    else:
        # 2023 - slightly smaller
        sp["attivo"]["capitale_fisso_netto"]["dettaglio"]["immobilizzazioni_materiali_nette"] = 2_800_000
        sp["attivo"]["capitale_fisso_netto"]["dettaglio"]["immobilizzazioni_immateriali_nette"] = 600_000
        sp["attivo"]["capitale_fisso_netto"]["dettaglio"]["immobilizzazioni_finanziarie"] = 150_000
        sp["attivo"]["capitale_fisso_netto"]["totale"] = 3_550_000
        sp["attivo"]["ccon"]["dettaglio"]["crediti_commerciali"] = 1_800_000
        sp["attivo"]["ccon"]["dettaglio"]["rimanenze"] = 1_100_000
        sp["attivo"]["ccon"]["dettaglio"]["altri_crediti_operativi"] = 250_000
        debiti_op = 2_200_000
        sp["attivo"]["ccon"]["dettaglio"]["debiti_operativi_sottratti"] = debiti_op
        sp["attivo"]["ccon"]["totale"] = calcola_ccon(1_800_000, 1_100_000, 250_000, debiti_op)
        sp["attivo"]["altre_attivita_non_operative"]["dettaglio"]["attivita_fiscali_differite"] = 80_000
        sp["attivo"]["altre_attivita_non_operative"]["totale"] = 80_000

        sp["passivo"]["patrimonio_netto"]["dettaglio"]["capitale_sociale"] = 500_000
        sp["passivo"]["patrimonio_netto"]["dettaglio"]["riserve"] = 1_300_000
        sp["passivo"]["patrimonio_netto"]["dettaglio"]["utile_perdita_esercizio"] = 350_000
        sp["passivo"]["patrimonio_netto"]["totale"] = 2_150_000
        sp["passivo"]["pfn"]["dettaglio"]["debiti_finanziari_lungo"] = 1_800_000
        sp["passivo"]["pfn"]["dettaglio"]["debiti_finanziari_breve"] = 400_000
        sp["passivo"]["pfn"]["dettaglio"]["disponibilita_liquide_sottratte"] = 620_000
        sp["passivo"]["pfn"]["totale"] = calcola_pfn(1_800_000, 400_000, 620_000)
        sp["passivo"]["debiti_operativi"]["totale"] = debiti_op

        totale_att = 3_550_000 + 1_800_000 + 1_100_000 + 250_000 + 80_000 + 620_000
        totale_pas = 2_150_000 + 1_800_000 + 400_000 + debiti_op
        sp["quadratura"] = verifica_quadratura(totale_att, totale_pas)

        ce["ricavi_netti"] = 11_150_000
        ce["costi_materie_prime_merci"] = -4_500_000
        ce["valore_aggiunto_industriale"] = 6_650_000
        ce["costi_servizi_godimento"] = -2_300_000
        ce["costi_personale"] = -2_800_000
        ce["ebitda"] = 1_550_000
        ce["ammortamenti_svalutazioni"] = -750_000
        ce["ebit"] = 800_000
        ce["proventi_oneri_finanziari"] = -100_000
        ce["ebt"] = 700_000
        ce["imposte"] = -180_000
        ce["utile_netto"] = 350_000

    return {
        "anno": anno,
        "sp_riclassificato": sp,
        "ce_riclassificato": ce,
        "deviazioni": [],
        "voci_non_mappate": [],
        "confidence": 0.95,
    }


@pytest.fixture
def pipeline_result():
    """Pipeline result completo con 2 anni."""
    return {
        "azienda": "Test S.r.l.",
        "completata": True,
        "severity_finale": "warning",
        "checker_pre": {
            "azienda": "Test S.r.l.",
            "tipo_check": "pre_riclassifica",
            "severity_globale": "ok",
            "puo_procedere": True,
            "risultati_per_anno": {
                "2024": {"severity": "ok", "score": 1.0, "checks": []},
                "2023": {"severity": "ok", "score": 1.0, "checks": []},
            },
            "checks_cross_anno": [],
        },
        "riclassifica": {
            "azienda": "Test S.r.l.",
            "metodo": "deterministico",
            "risultati_per_anno": {
                "2024": _crea_risultato_anno("2024", True),
                "2023": _crea_risultato_anno("2023", False),
            },
        },
        "checker_post": {
            "azienda": "Test S.r.l.",
            "tipo_check": "post_riclassifica",
            "severity_globale": "warning",
            "risultati_per_anno": {
                "2024": {
                    "severity": "ok",
                    "score": 1.0,
                    "checks": [
                        {"codice": "RICLASS_QUADRATURA", "esito": "pass",
                         "severity_contributo": "ok", "dettaglio": "SP quadra"},
                    ],
                },
                "2023": {
                    "severity": "ok",
                    "score": 1.0,
                    "checks": [
                        {"codice": "RICLASS_QUADRATURA", "esito": "pass",
                         "severity_contributo": "ok", "dettaglio": "SP quadra"},
                    ],
                },
            },
        },
    }


@pytest.fixture
def analisi():
    """Risultato analisi completa."""
    return {
        "azienda": "Test S.r.l.",
        "anni": [2023, 2024],
        "indici": {
            "redditivita": {
                "ROE": {"2023": 0.1628, "2024": 0.1758},
                "ROI": {"2023": 0.0500, "2024": 0.0550},
                "ROS": {"2023": 0.0717, "2024": 0.0738},
                "ROA": {"2023": 0.1081, "2024": 0.1111},
                "EBITDA_margin": {"2023": 0.1390, "2024": 0.1393},
            },
            "struttura": {
                "indice_indipendenza_finanziaria": {"2023": 0.2905, "2024": 0.2963},
                "rapporto_indebitamento": {"2023": 1.7674, "2024": 1.7500},
                "copertura_immobilizzazioni": {"2023": 1.1127, "2024": 1.0541},
                "pfn_ebitda": {"2023": 1.0194, "2024": 0.7059},
                "pfn_pn": {"2023": 0.7349, "2024": 0.5000},
            },
            "liquidita": {
                "current_ratio": {"2023": 1.7231, "2024": 1.6400},
                "quick_ratio": {"2023": 0.9308, "2024": 0.9200},
                "giorni_crediti": {"2023": 58.9, "2024": 59.8},
                "giorni_debiti": {"2023": 178.4, "2024": 182.5},
                "giorni_magazzino": {"2023": 59.0, "2024": 58.4},
                "ciclo_cassa": {"2023": -60.5, "2024": -64.3},
            },
            "efficienza": {
                "costo_personale_su_va": {"2023": 0.4211, "2024": 0.4167},
                "incidenza_ammortamenti": {"2023": 0.0673, "2024": 0.0656},
            },
        },
        "variazioni_yoy": {},
        "cagr": {"ricavi": 0.0941, "ebitda": 0.0968},
        "trend": [
            {"indice": "ROE", "categoria": "redditivita", "direzione": "crescente",
             "variazione_periodo": 0.013, "variazione_percentuale": 0.08, "significativo": False},
        ],
        "alert": [
            {"tipo": "attenzione", "indice": "quick_ratio", "valore": 0.92,
             "soglia": 1.0, "anno": "2024", "messaggio": "Quick ratio sotto soglia (< 1)"},
        ],
        "narrative": {
            "sintesi": "Test S.r.l. presenta ricavi netti in crescita.",
            "redditivita": "La redditivita e in miglioramento.",
            "struttura_finanziaria": "La struttura finanziaria e solida.",
            "liquidita": "Il current ratio e adeguato.",
            "conclusioni": "L'azienda presenta un profilo equilibrato.",
        },
    }


@pytest.fixture
def risposta_llm_estrazione():
    """Risposta LLM simulata per l'estrattore PDF."""
    return _carica_fixture("risposta_llm_estrazione.json")


@pytest.fixture
def risposta_llm_riclassifica():
    """Risposta LLM simulata per il riclassificatore."""
    return _carica_fixture("risposta_llm_riclassifica.json")
