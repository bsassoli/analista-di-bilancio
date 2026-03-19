"""Definizioni schema dati e strutture condivise."""

from typing import Any, Optional


# --- Struttura voce di bilancio ---

def crea_voce(
    id: str,
    label: str,
    livello: int,
    aggregato: str,
    valore: dict[str, int | None],
    fonte_riga_bilancio: str = "",
    non_standard: bool = False,
    flags: Optional[list[str]] = None,
    note: str = "",
) -> dict:
    """Crea una voce di bilancio normalizzata."""
    return {
        "id": id,
        "label": label,
        "livello": livello,
        "aggregato": aggregato,
        "valore": valore,
        "fonte_riga_bilancio": fonte_riga_bilancio,
        "non_standard": non_standard,
        "flags": flags or [],
        "note": note,
    }


# --- Documento di stato orchestratore ---

def crea_stato_iniziale(azienda: str, anni: list[int]) -> dict:
    """Crea un nuovo documento di stato per l'orchestratore."""
    return {
        "azienda": azienda,
        "anni": sorted(anni),
        "fase_corrente": "inizializzazione",
        "qualita_dati": {
            str(anno): {"severity": "unknown", "issues": []} for anno in anni
        },
        "flags_globali": [],
        "schema_versione": "1.0",
        "deviazioni_schema": [],
    }


# --- Schema SP riclassificato vuoto ---

def crea_sp_riclassificato_vuoto() -> dict:
    """Crea la struttura vuota per lo SP riclassificato."""
    return {
        "attivo": {
            "capitale_fisso_netto": {
                "totale": 0,
                "dettaglio": {
                    "immobilizzazioni_materiali_nette": 0,
                    "immobilizzazioni_immateriali_nette": 0,
                    "immobilizzazioni_finanziarie": 0,
                },
            },
            "ccon": {
                "totale": 0,
                "dettaglio": {
                    "crediti_commerciali": 0,
                    "rimanenze": 0,
                    "altri_crediti_operativi": 0,
                    "debiti_operativi_sottratti": 0,
                },
            },
            "altre_attivita_non_operative": {
                "totale": 0,
                "dettaglio": {
                    "crediti_finanziari": 0,
                    "attivita_fiscali_differite": 0,
                },
            },
        },
        "passivo": {
            "patrimonio_netto": {
                "totale": 0,
                "dettaglio": {
                    "capitale_sociale": 0,
                    "riserve": 0,
                    "utile_perdita_esercizio": 0,
                },
            },
            "pfn": {
                "totale": 0,
                "dettaglio": {
                    "debiti_finanziari_lungo": 0,
                    "debiti_finanziari_breve": 0,
                    "disponibilita_liquide_sottratte": 0,
                },
            },
            "debiti_operativi": {
                "totale": 0,
                "nota": "Alimentano CCON, qui per quadratura",
            },
        },
        "quadratura": {
            "totale_attivo": 0,
            "totale_passivo": 0,
            "delta": 0,
            "ok": False,
        },
    }


# --- Schema CE riclassificato vuoto ---

def crea_ce_riclassificato_vuoto() -> dict:
    """Crea la struttura vuota per il CE riclassificato."""
    return {
        "ricavi_netti": 0,
        "costi_materie_prime_merci": 0,
        "valore_aggiunto_industriale": 0,
        "costi_servizi_godimento": 0,
        "costi_personale": 0,
        "ebitda": 0,
        "ammortamenti_svalutazioni": 0,
        "ebit": 0,
        "proventi_oneri_finanziari": 0,
        "ebt": 0,
        "imposte": 0,
        "utile_netto": 0,
    }


# --- Mapping voci civilistiche → destinazione riclassificata ---

# Chiave: pattern su fonte_riga_bilancio o id
# Valore: (sezione_target, voce_target)
MAPPING_SP = {
    # Attivo — Immobilizzazioni
    "B.I": ("attivo.capitale_fisso_netto.dettaglio", "immobilizzazioni_immateriali_nette"),
    "B.II": ("attivo.capitale_fisso_netto.dettaglio", "immobilizzazioni_materiali_nette"),
    "B.III": ("attivo.capitale_fisso_netto.dettaglio", "immobilizzazioni_finanziarie"),
    # Attivo — Circolante
    "C.I": ("attivo.ccon.dettaglio", "rimanenze"),
    "C.II.1": ("attivo.ccon.dettaglio", "crediti_commerciali"),
    "C.II.4bis": ("attivo.ccon.dettaglio", "altri_crediti_operativi"),
    "C.II.4ter": ("attivo.altre_attivita_non_operative.dettaglio", "attivita_fiscali_differite"),
    "C.II.5": ("attivo.ccon.dettaglio", "altri_crediti_operativi"),
    "C.IV": ("passivo.pfn.dettaglio", "disponibilita_liquide_sottratte"),
    # Passivo — PN
    "A.I": ("passivo.patrimonio_netto.dettaglio", "capitale_sociale"),
    "A.IV": ("passivo.patrimonio_netto.dettaglio", "riserve"),
    "A.VII": ("passivo.patrimonio_netto.dettaglio", "riserve"),
    "A.VIII": ("passivo.patrimonio_netto.dettaglio", "riserve"),
    "A.IX": ("passivo.patrimonio_netto.dettaglio", "utile_perdita_esercizio"),
    # Passivo — Debiti
    "D.4": ("passivo.pfn.dettaglio", "debiti_finanziari_breve"),  # banche entro
    "D.7": ("passivo.debiti_operativi", "totale"),  # fornitori
    "D.12": ("passivo.debiti_operativi", "totale"),  # tributari
    "D.13": ("passivo.debiti_operativi", "totale"),  # previdenziali
}

MAPPING_CE = {
    "A.1": "ricavi_netti",
    "A.2": "ricavi_netti",  # variazione rimanenze prodotti (rettifica)
    "A.3": "ricavi_netti",  # variazione lavori in corso
    "A.4": "ricavi_netti",  # incrementi immobilizzazioni
    "A.5": "ricavi_netti",  # altri ricavi
    "B.6": "costi_materie_prime_merci",
    "B.7": "costi_servizi_godimento",
    "B.8": "costi_servizi_godimento",
    "B.9": "costi_personale",
    "B.10a": "ammortamenti_svalutazioni",
    "B.10b": "ammortamenti_svalutazioni",
    "B.10c": "ammortamenti_svalutazioni",
    "B.10d": "ammortamenti_svalutazioni",
    "B.11": "costi_materie_prime_merci",  # variazione rimanenze MP
    "B.14": "costi_servizi_godimento",  # oneri diversi gestione
    "C.15": "proventi_oneri_finanziari",
    "C.16": "proventi_oneri_finanziari",
    "C.17": "proventi_oneri_finanziari",
    "C.17bis": "proventi_oneri_finanziari",
    "D.18": "proventi_oneri_finanziari",  # rivalutazioni
    "D.19": "proventi_oneri_finanziari",  # svalutazioni
    "20": "imposte",
}
