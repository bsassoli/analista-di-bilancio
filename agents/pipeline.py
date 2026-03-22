"""Pipeline runner: estrazione → checker → riclassificatore → post-checker.

Collega le fasi deterministiche (checker) con quelle LLM-powered (riclassifica)
per produrre SP e CE riclassificati a partire dallo schema normalizzato.
"""

import json
import sys
from pathlib import Path
from typing import Any, Optional

from tools.evidence_schema import ClassificationHint, ExtractionBundle

# Percorso root del progetto
ROOT = Path(__file__).parent.parent

sys.path.insert(0, str(ROOT))

from tools.validatori import (
    valida_schema_normalizzato,
    valida_quadratura_sp,
    valida_coerenza_utile,
    calcola_severity,
)
from tools.calcolatori import (
    calcola_ccon,
    calcola_pfn,
    verifica_quadratura,
)
from tools.schema import (
    crea_sp_riclassificato_vuoto,
    crea_ce_riclassificato_vuoto,
    MAPPING_SP,
    MAPPING_CE,
    MAPPING_SP_IFRS,
    MAPPING_CE_IFRS,
)
from agents.base import agent_loop


# ---------------------------------------------------------------------------
# 1. CHECKER PRE-RICLASSIFICA  (deterministico, nessuna chiamata API)
# ---------------------------------------------------------------------------

def _checks_voci_negative(schema: dict) -> list[dict]:
    """Identifica voci SP che non dovrebbero essere negative."""
    issues: list[dict] = []
    voci_positive_attese = {
        "immobilizzazioni", "rimanenze", "disponibilita_liquide",
        "cassa", "crediti", "partecipazioni", "totale_attivo",
    }
    for voce in schema.get("sp", []):
        vid = voce.get("id", "")
        for pattern in voci_positive_attese:
            if pattern in vid:
                for anno, val in voce.get("valore", {}).items():
                    if val is not None and val < 0:
                        issues.append({
                            "codice": "VOCI_NEGATIVE",
                            "esito": "warn",
                            "severity_contributo": "warning",
                            "dettaglio": (
                                f"Voce '{vid}' negativa ({val:,}) "
                                f"nell'anno {anno}"
                            ),
                        })
                break
    return issues


def _checks_voci_zero(schema: dict) -> list[dict]:
    """Segnala voci tipicamente non-zero che risultano 0 in tutti gli anni."""
    issues: list[dict] = []
    voci_tipicamente_non_zero = {
        "patrimonio_netto", "totale_attivo", "totale_passivo",
        "ricavi", "ricavi_vendite_prestazioni",
    }
    for sezione in ("sp", "ce"):
        for voce in schema.get(sezione, []):
            vid = voce.get("id", "")
            for pattern in voci_tipicamente_non_zero:
                if pattern in vid:
                    valori = voce.get("valore", {})
                    if valori and all(v == 0 for v in valori.values()):
                        issues.append({
                            "codice": "VOCI_ZERO",
                            "esito": "warn",
                            "severity_contributo": "warning",
                            "dettaglio": f"Voce '{vid}' vale 0 in tutti gli anni",
                        })
                    break
    return issues


def esegui_checker(schema: dict) -> dict:
    """Esegue tutti i check pre-riclassifica sullo schema normalizzato.

    Fase completamente deterministica — nessuna chiamata API.

    Args:
        schema: Schema normalizzato JSON (output estrattore numerico).

    Returns:
        Report checker con severity per anno e score complessivo.
    """
    azienda = schema.get("azienda", "sconosciuta")
    anni = [str(a) for a in schema.get("anni_estratti", [])]

    # --- Check strutturali (cross-anno) ---
    issues_strutturali = valida_schema_normalizzato(schema)

    # I duplicati di ID sono spesso strutturali nel formato del bilancio:
    # IFRS: subtotali ripetuti; OIC: "esigibili entro/oltre" per ogni voce.
    # Downgrade da critical a warning — l'estrattore numerico disambigua gli ID.
    for issue in issues_strutturali:
        if issue["codice"] == "DUPLICATI":
            issue["severity"] = "warning"

    # --- Check per anno ---
    risultati_per_anno: dict[str, Any] = {}

    for anno in anni:
        checks_anno: list[dict] = []

        # Quadratura SP
        check_quad = valida_quadratura_sp(schema, anno)
        checks_anno.append(check_quad)

        # Coerenza utile CE vs SP
        check_utile = valida_coerenza_utile(schema, anno)
        checks_anno.append(check_utile)

        # Voci negative
        checks_anno.extend(_checks_voci_negative(schema))

        # Voci zero
        checks_anno.extend(_checks_voci_zero(schema))

        # Severity complessiva anno
        # Combiniamo issues strutturali (hanno severity, non severity_contributo)
        # con i checks per anno
        tutti_checks = []
        for issue in issues_strutturali:
            tutti_checks.append({
                "codice": issue["codice"],
                "esito": "fail" if issue["severity"] == "critical" else "warn",
                "severity_contributo": issue["severity"],
                "dettaglio": issue["dettaglio"],
            })
        tutti_checks.extend(checks_anno)

        severity_label, score = calcola_severity(tutti_checks)

        risultati_per_anno[anno] = {
            "severity": severity_label,
            "score": score,
            "checks": tutti_checks,
        }

    # Severity complessiva globale
    severity_globale = "ok"
    for anno_res in risultati_per_anno.values():
        if anno_res["severity"] == "critical":
            severity_globale = "critical"
            break
        if anno_res["severity"] == "warning":
            severity_globale = "warning"

    # Check cross-anno: continuità voci
    checks_cross: list[dict] = []
    if len(anni) > 1:
        for sezione in ("sp", "ce"):
            voci_per_anno: dict[str, set[str]] = {}
            for voce in schema.get(sezione, []):
                for anno in anni:
                    if voce.get("valore", {}).get(anno) is not None:
                        voci_per_anno.setdefault(anno, set()).add(voce["id"])

            if len(voci_per_anno) > 1:
                anni_ordinati = sorted(voci_per_anno.keys())
                for i in range(1, len(anni_ordinati)):
                    precedente = voci_per_anno.get(anni_ordinati[i - 1], set())
                    corrente = voci_per_anno.get(anni_ordinati[i], set())
                    scomparse = precedente - corrente
                    for vid in scomparse:
                        checks_cross.append({
                            "codice": "CONTINUITA_VOCI",
                            "esito": "warn",
                            "severity_contributo": "warning",
                            "dettaglio": (
                                f"Voce '{vid}' ({sezione.upper()}) presente nel "
                                f"{anni_ordinati[i-1]} ma assente nel {anni_ordinati[i]}"
                            ),
                        })

    puo_procedere = severity_globale != "critical"

    return {
        "azienda": azienda,
        "tipo_check": "pre_riclassifica",
        "severity_globale": severity_globale,
        "puo_procedere": puo_procedere,
        "risultati_per_anno": risultati_per_anno,
        "checks_cross_anno": checks_cross,
    }


# ---------------------------------------------------------------------------
# 2. RICLASSIFICATORE  (LLM-powered via agent_loop)
# ---------------------------------------------------------------------------

def _prepara_input_riclassifica(schema: dict, checker_report: dict) -> dict:
    """Prepara il payload di input per il subagente riclassificatore."""
    return {
        "task": "riclassifica",
        "azienda": schema.get("azienda", ""),
        "anni": schema.get("anni_estratti", []),
        "tipo_bilancio": schema.get("tipo_bilancio", "ordinario"),
        "formato": schema.get("metadata", {}).get("formato", ""),
        "sp": schema.get("sp", []),
        "ce": schema.get("ce", []),
        "metadata": schema.get("metadata", {}),
        "flags_globali": schema.get("flags_globali", []),
        "annotazioni_voci": schema.get("annotazioni_voci", []),
        "checker_report": {
            "severity_globale": checker_report.get("severity_globale", "ok"),
            "warnings": [
                c["dettaglio"]
                for anno_res in checker_report.get("risultati_per_anno", {}).values()
                for c in anno_res.get("checks", [])
                if c.get("severity_contributo") == "warning"
            ],
        },
        "mapping_sp_reference": {
            k: f"{v[0]}.{v[1]}" for k, v in MAPPING_SP.items()
        },
        "mapping_ce_reference": MAPPING_CE,
        "schema_sp_target": crea_sp_riclassificato_vuoto(),
        "schema_ce_target": crea_ce_riclassificato_vuoto(),
        "istruzioni": (
            "Riclassifica lo Stato Patrimoniale con criterio finanziario e il "
            "Conto Economico con criterio a valore aggiunto. "
            f"Formato bilancio: {schema.get('metadata', {}).get('formato', 'sconosciuto')}. "
            "Mappa ciascuna voce alla destinazione riclassificata corretta, "
            "usando le tabelle di mapping nel tuo SKILL.md come riferimento. "
            "Per voci ambigue (es. 'altri debiti', 'fondi rischi'), "
            "usa il campo 'note' (genitore) per disambiguare. "
            "Per ogni anno, restituisci un JSON con questa struttura esatta:\n"
            '{"risultati_per_anno": {"2024": {"anno": "2024", '
            '"sp_riclassificato": <schema_sp_target compilato>, '
            '"ce_riclassificato": <schema_ce_target compilato>, '
            '"deviazioni": [...], "voci_non_mappate": [...], "confidence": 0.9}}}\n'
            "IMPORTANTE: tutti i valori devono essere NUMERI INTERI, non stringhe. "
            "Calcola CCON, PFN, EBITDA, EBIT, EBT, utile netto. "
            "Verifica la quadratura SP (attivo = passivo)."
        ),
    }


def _estrai_risultati_llm(risultato: dict, anni: list[str]) -> dict:
    """Estrae risultati_per_anno dalla risposta LLM in vari formati possibili."""
    # Caso 1: struttura diretta
    if "risultati_per_anno" in risultato:
        return risultato["risultati_per_anno"]

    # Caso 2: anni come chiavi top-level
    found = {}
    for anno in anni:
        if anno in risultato:
            found[anno] = risultato[anno]
    if found:
        return found

    # Caso 3: raw_response con JSON embedded
    raw = risultato.get("raw_response", "")
    if raw:
        try:
            start = raw.index("{")
            end = raw.rindex("}") + 1
            parsed = json.loads(raw[start:end])
            if "risultati_per_anno" in parsed:
                return parsed["risultati_per_anno"]
            for anno in anni:
                if anno in parsed:
                    found[anno] = parsed[anno]
            if found:
                return found
        except (ValueError, json.JSONDecodeError):
            pass

    # Caso 4: il risultato stesso potrebbe essere un anno singolo
    if "sp_riclassificato" in risultato and "ce_riclassificato" in risultato:
        anno = risultato.get("anno", anni[0] if anni else "2024")
        return {anno: risultato}

    return {}


def _fuzzy_get(voci: dict, *patterns) -> int:
    """Cerca un valore per pattern parziale sull'ID.

    Prova ogni pattern in ordine, restituisce il primo match.
    """
    for pattern in patterns:
        # Exact match
        if pattern in voci:
            return voci[pattern]
        # Partial match (l'ID contiene il pattern)
        for vid, val in voci.items():
            if pattern in vid:
                return val
    return 0


def _riclassifica_deterministico(schema: dict, anno: str) -> dict:
    """Riclassifica in modo deterministico con mapping format-agnostic.

    Funziona per bilanci OIC e IFRS usando fuzzy matching sui pattern
    definiti in MAPPING_SP_IFRS e MAPPING_CE_IFRS.
    """
    sp = crea_sp_riclassificato_vuoto()
    ce = crea_ce_riclassificato_vuoto()
    deviazioni: list[str] = []
    voci_non_mappate: list[str] = []

    # Costruisci lookup per id
    sp_voci = {v["id"]: v.get("valore", {}).get(anno, 0) or 0
               for v in schema.get("sp", [])}
    ce_voci = {v["id"]: v.get("valore", {}).get(anno, 0) or 0
               for v in schema.get("ce", [])}

    # --- SP: mapping via fuzzy_get con pattern multipli ---
    # Immobilizzazioni materiali
    imm_mat = _fuzzy_get(sp_voci,
        "totale_immobilizzazioni_materiali", "immobilizzazioni_materiali",
        "immobili_impianti", "b_ii",
    )
    sp["attivo"]["capitale_fisso_netto"]["dettaglio"]["immobilizzazioni_materiali_nette"] = imm_mat

    # Immobilizzazioni immateriali
    imm_imm = _fuzzy_get(sp_voci,
        "totale_immobilizzazioni_immateriali", "immobilizzazioni_immateriali",
        "avviamento", "b_i",
    )
    sp["attivo"]["capitale_fisso_netto"]["dettaglio"]["immobilizzazioni_immateriali_nette"] = imm_imm

    # Immobilizzazioni finanziarie
    partecipazioni = _fuzzy_get(sp_voci, "partecipazioni")
    crediti_fin_lt = _fuzzy_get(sp_voci,
        "crediti_finanziari_a_lungo", "altri_crediti_finanziari_a_lungo",
        "immobilizzazioni_finanziarie", "b_iii",
    )
    imm_fin = partecipazioni + crediti_fin_lt
    sp["attivo"]["capitale_fisso_netto"]["dettaglio"]["immobilizzazioni_finanziarie"] = imm_fin

    cfn = imm_mat + imm_imm + imm_fin
    sp["attivo"]["capitale_fisso_netto"]["totale"] = cfn

    # Crediti commerciali
    crediti_comm = _fuzzy_get(sp_voci,
        "crediti_commerciali", "crediti_verso_clienti",
        "crediti_commerciali_e_altre",
    )
    crediti_comm_infra = _fuzzy_get(sp_voci,
        "crediti_commerciali_verso_societ",
        "crediti_verso_controllate",
    )
    crediti_comm_tot = crediti_comm + crediti_comm_infra
    sp["attivo"]["ccon"]["dettaglio"]["crediti_commerciali"] = crediti_comm_tot

    # Rimanenze
    rimanenze = _fuzzy_get(sp_voci, "rimanenze")
    sp["attivo"]["ccon"]["dettaglio"]["rimanenze"] = rimanenze

    # Altri crediti operativi
    att_fiscali_correnti = _fuzzy_get(sp_voci,
        "attivit_fiscali_per_imposte_correnti", "attivita_fiscali_per_imposte_correnti",
        "crediti_tributari", "crediti_verso_erario",
    )
    altri_crediti_op = _fuzzy_get(sp_voci,
        "altri_crediti_operativi", "crediti_verso_altri",
    )
    tot_altri_crediti = att_fiscali_correnti + altri_crediti_op
    sp["attivo"]["ccon"]["dettaglio"]["altri_crediti_operativi"] = tot_altri_crediti

    # Altre attività non operative
    att_fiscali_diff = _fuzzy_get(sp_voci,
        "attivit_fiscali_per_imposte_differite", "attivita_fiscali_per_imposte_differite",
        "imposte_anticipate",
    )
    crediti_fin_bt = _fuzzy_get(sp_voci,
        "crediti_finanziari_a_breve", "altri_crediti_finanziari_a_breve",
    )
    sp["attivo"]["altre_attivita_non_operative"]["dettaglio"]["attivita_fiscali_differite"] = att_fiscali_diff
    sp["attivo"]["altre_attivita_non_operative"]["dettaglio"]["crediti_finanziari"] = crediti_fin_bt
    sp["attivo"]["altre_attivita_non_operative"]["totale"] = att_fiscali_diff + crediti_fin_bt

    # Disponibilità liquide
    cassa = _fuzzy_get(sp_voci,
        "cassa_e_disponibilit", "disponibilita_liquide", "disponibilit_liquide",
    )

    # --- SP PASSIVO ---
    # Patrimonio Netto
    pn_totale = _fuzzy_get(sp_voci,
        "totale_patrimonio_netto", "patrimonio_netto",
    )
    capitale = _fuzzy_get(sp_voci,
        "capitale_emesso", "capitale_sociale", "capitale",
    )
    utile_es = _fuzzy_get(sp_voci,
        "utile_d_esercizio", "utile_perdita_esercizio",
        "utile_dell_esercizio",
    )
    riserve = pn_totale - capitale - utile_es if pn_totale else 0
    sp["passivo"]["patrimonio_netto"]["totale"] = pn_totale
    sp["passivo"]["patrimonio_netto"]["dettaglio"]["capitale_sociale"] = capitale
    sp["passivo"]["patrimonio_netto"]["dettaglio"]["riserve"] = riserve
    sp["passivo"]["patrimonio_netto"]["dettaglio"]["utile_perdita_esercizio"] = utile_es

    # Debiti finanziari lungo
    fin_lt = _fuzzy_get(sp_voci,
        "finanziamenti_a_lungo_termine", "debiti_verso_banche_lungo",
        "debiti_verso_banche_oltre",
    )
    sp["passivo"]["pfn"]["dettaglio"]["debiti_finanziari_lungo"] = fin_lt

    # Debiti finanziari breve
    fin_bt = _fuzzy_get(sp_voci,
        "finanziamenti_a_breve_termine", "debiti_verso_banche_breve",
        "debiti_verso_banche_entro",
    )
    deb_altri_fin = _fuzzy_get(sp_voci, "debiti_verso_altri_finanziatori")
    sp["passivo"]["pfn"]["dettaglio"]["debiti_finanziari_breve"] = fin_bt + deb_altri_fin

    # Disponibilità liquide sottratte
    sp["passivo"]["pfn"]["dettaglio"]["disponibilita_liquide_sottratte"] = cassa

    pfn = calcola_pfn(fin_lt, fin_bt + deb_altri_fin, cassa)
    sp["passivo"]["pfn"]["totale"] = pfn

    # Debiti operativi
    deb_comm = _fuzzy_get(sp_voci,
        "debiti_commerciali", "debiti_verso_fornitori",
        "debiti_commerciali_e_altre_passivit",
    )
    deb_comm_infra = _fuzzy_get(sp_voci,
        "debiti_commerciali_verso_societ",
        "debiti_verso_controllate",
    )
    deb_fiscali = _fuzzy_get(sp_voci,
        "passivit_fiscali", "passivita_fiscali",
        "debiti_tributari",
    )
    tfr = _fuzzy_get(sp_voci,
        "tfr", "benefici_successivi", "trattamento_fine_rapporto",
    )
    altre_pass = _fuzzy_get(sp_voci,
        "altre_passivit", "altre_passivita", "altri_debiti",
        "fondi_rischi",
    )

    debiti_operativi = deb_comm + deb_comm_infra + deb_fiscali + tfr + altre_pass
    sp["passivo"]["debiti_operativi"]["totale"] = debiti_operativi

    # CCON
    ccon = calcola_ccon(crediti_comm_tot, rimanenze, tot_altri_crediti, debiti_operativi)
    sp["attivo"]["ccon"]["dettaglio"]["debiti_operativi_sottratti"] = debiti_operativi
    sp["attivo"]["ccon"]["totale"] = ccon

    # Quadratura SP
    totale_attivo_calc = (
        cfn
        + crediti_comm_tot + rimanenze + tot_altri_crediti
        + att_fiscali_diff + crediti_fin_bt
        + cassa
    )
    totale_passivo_calc = pn_totale + fin_lt + fin_bt + deb_altri_fin + debiti_operativi
    quad = verifica_quadratura(totale_attivo_calc, totale_passivo_calc)
    sp["quadratura"] = quad

    if not quad["ok"]:
        tot_att_dich = schema.get("metadata", {}).get(
            "totale_attivo_dichiarato", {}
        ).get(anno, 0)
        tot_pass_dich = schema.get("metadata", {}).get(
            "totale_passivo_dichiarato", {}
        ).get(anno, 0)
        deviazioni.append(
            f"Quadratura non perfetta: calcolato attivo={totale_attivo_calc:,}, "
            f"passivo={totale_passivo_calc:,} (dichiarati: {tot_att_dich:,} / {tot_pass_dich:,})"
        )

    # --- CE ---
    ricavi = _fuzzy_get(ce_voci,
        "ricavi_vendite_prestazioni", "ricavi_delle_vendite", "ricavi",
    )
    altri_ricavi = _fuzzy_get(ce_voci, "altri_ricavi_e_proventi", "altri_ricavi")
    var_rim_pf = _fuzzy_get(ce_voci,
        "variazione_nelle_rimanenze_di_prodotti",
        "variazione_rimanenze_prodotti",
    )
    ce["ricavi_netti"] = ricavi + altri_ricavi + var_rim_pf

    materie_prime = _fuzzy_get(ce_voci,
        "per_materie_prime", "costi_materie_prime",
        "materie_prime_materiali", "materie_prime",
    )
    var_rim_mp = _fuzzy_get(ce_voci,
        "variazione_nelle_rimanenze_di_materie",
        "variazione_rimanenze_materie",
    )
    ce["costi_materie_prime_merci"] = materie_prime + var_rim_mp

    ce["valore_aggiunto_industriale"] = ce["ricavi_netti"] + ce["costi_materie_prime_merci"]

    costi_servizi = _fuzzy_get(ce_voci,
        "altri_costi_operativi", "per_servizi", "costi_servizi",
        "costi_per_servizi",
    )
    godimento = _fuzzy_get(ce_voci, "godimento_beni_terzi", "per_godimento")
    oneri_diversi = _fuzzy_get(ce_voci, "oneri_diversi_di_gestione")
    ce["costi_servizi_godimento"] = costi_servizi + godimento + oneri_diversi

    costo_personale = _fuzzy_get(ce_voci,
        "costo_del_personale", "per_il_personale",
        "costi_personale", "costi_del_personale",
    )
    ce["costi_personale"] = costo_personale

    ce["ebitda"] = (
        ce["valore_aggiunto_industriale"]
        + ce["costi_servizi_godimento"]
        + ce["costi_personale"]
    )

    ammortamenti = _fuzzy_get(ce_voci,
        "ammortamenti_e_svalutazioni", "ammortamenti",
    )
    accantonamenti_sval = _fuzzy_get(ce_voci, "accantonamenti_e_svalutazioni", "accantonamenti")
    ce["ammortamenti_svalutazioni"] = ammortamenti + accantonamenti_sval

    ce["ebit"] = ce["ebitda"] + ce["ammortamenti_svalutazioni"]

    ricavi_fin = _fuzzy_get(ce_voci, "ricavi_finanziari", "proventi_finanziari")
    costi_fin = _fuzzy_get(ce_voci, "costi_finanziari", "oneri_finanziari")
    cambi = _fuzzy_get(ce_voci,
        "utile_derivante_da_transizioni_in_valute",
        "utili_perdite_su_cambi",
    )
    ce["proventi_oneri_finanziari"] = ricavi_fin + costi_fin + cambi

    ce["ebt"] = ce["ebit"] + ce["proventi_oneri_finanziari"]

    imposte = _fuzzy_get(ce_voci, "imposte_sul_reddito", "imposte")
    ce["imposte"] = imposte

    ce["utile_netto"] = ce["ebt"] + ce["imposte"]

    # Verifiche coerenza
    ebitda_dichiarato = _fuzzy_get(ce_voci, "ebitda_margine_operativo_lordo", "ebitda")
    if ebitda_dichiarato != 0 and abs(ce["ebitda"] - ebitda_dichiarato) > 1:
        deviazioni.append(
            f"EBITDA calcolato ({ce['ebitda']:,}) vs dichiarato ({ebitda_dichiarato:,}), "
            f"delta: {ce['ebitda'] - ebitda_dichiarato:,}"
        )

    ebit_dichiarato = _fuzzy_get(ce_voci, "ebit_risultato_operativo")
    if ebit_dichiarato != 0 and abs(ce["ebit"] - ebit_dichiarato) > 1:
        deviazioni.append(
            f"EBIT calcolato ({ce['ebit']:,}) vs dichiarato ({ebit_dichiarato:,}), "
            f"delta: {ce['ebit'] - ebit_dichiarato:,}"
        )

    utile_dich = schema.get("metadata", {}).get("utile_dichiarato", {}).get(anno, 0)
    if utile_dich and abs(ce["utile_netto"] - utile_dich) > 1:
        deviazioni.append(
            f"Utile netto calcolato ({ce['utile_netto']:,}) vs dichiarato ({utile_dich:,})"
        )

    n_deviazioni = len(deviazioni)
    n_non_mappate = len(voci_non_mappate)
    confidence = 1.0 - (n_deviazioni * 0.05) - (n_non_mappate * 0.1)
    if not quad["ok"]:
        confidence -= 0.15
    confidence = max(0.0, round(confidence, 2))

    return {
        "anno": anno,
        "sp_riclassificato": sp,
        "ce_riclassificato": ce,
        "deviazioni": deviazioni,
        "voci_non_mappate": voci_non_mappate,
        "confidence": confidence,
    }


# ---------------------------------------------------------------------------
# Evidence-aware reclassification
# ---------------------------------------------------------------------------

# Rows whose classification can be rerouted by hints.
# Maps fuzzy-match bucket → set of row_id patterns that could be rerouted.
_REROUTABLE_PATTERNS: dict[str, list[str]] = {
    "debiti_operativi": [
        "fondi_rischi", "fondi_oneri", "altri_debiti", "debiti_diversi",
        "passivit_fiscali", "debiti_tributari",
    ],
    "debiti_finanziari_lungo": [
        "fondi_rischi", "fondi_oneri", "debiti_verso_banche",
        "finanziamenti", "passivit_per_leasing",
    ],
    "debiti_finanziari_breve": [
        "debiti_verso_banche", "debiti_verso_altri_finanziatori",
    ],
}


def _build_hint_by_row(hints: list[ClassificationHint]) -> dict[str, ClassificationHint]:
    """Build lookup: row_id → best (highest confidence) hint."""
    by_row: dict[str, ClassificationHint] = {}
    for h in hints:
        rid = h.target_row_id
        if rid not in by_row or h.confidence > by_row[rid].confidence:
            by_row[rid] = h
    return by_row


def _riclassifica_con_evidenze(
    schema: dict,
    anno: str,
    hints: list[ClassificationHint],
) -> dict:
    """Evidence-aware reclassification.

    Runs deterministic reclassification, then applies hint-based adjustments:
    - Reroutes ambiguous rows to the hint-suggested bucket
    - Marks rows as unresolved if hints conflict with fuzzy mapping
    - Penalizes confidence for weak/missing evidence, boosts for strong evidence
    """
    result = _riclassifica_deterministico(schema, anno)

    if not hints:
        return result

    hint_by_row = _build_hint_by_row(hints)
    sp = result["sp_riclassificato"]
    deviazioni = result.get("deviazioni", [])
    voci_non_mappate = result.get("voci_non_mappate", [])

    # Build row_id → value lookup
    sp_voci = {v["id"]: v.get("valore", {}).get(anno, 0) or 0
               for v in schema.get("sp", [])}

    rerouted = 0
    unresolved = 0
    supported = 0

    for row_id, hint in hint_by_row.items():
        val = sp_voci.get(row_id, 0)
        if val == 0:
            continue  # no value to reroute

        target = hint.suggested_classification

        # Check: is this row currently in a DIFFERENT bucket than the hint suggests?
        # We detect this by checking if the row_id matches a reroutable pattern
        # for a bucket OTHER than the suggested one.
        current_bucket = None
        for bucket, patterns in _REROUTABLE_PATTERNS.items():
            if any(p in row_id for p in patterns) and bucket != target:
                current_bucket = bucket
                break

        if current_bucket is None:
            # Row is either already in the right bucket or not reroutable
            supported += 1
            continue

        # Reroute: only if confidence >= 0.7
        if hint.confidence < 0.7:
            unresolved += 1
            voci_non_mappate.append(
                f"{row_id}: hint suggerisce {target} (conf={hint.confidence}) "
                f"ma confidence troppo bassa per reroute da {current_bucket}"
            )
            continue

        # Apply the reroute
        # Remove from current bucket
        if current_bucket == "debiti_operativi":
            sp["passivo"]["debiti_operativi"]["totale"] -= val
        elif current_bucket == "debiti_finanziari_lungo":
            sp["passivo"]["pfn"]["dettaglio"]["debiti_finanziari_lungo"] -= val
        elif current_bucket == "debiti_finanziari_breve":
            sp["passivo"]["pfn"]["dettaglio"]["debiti_finanziari_breve"] -= val

        # Add to target bucket
        if target == "debiti_finanziari_lungo":
            sp["passivo"]["pfn"]["dettaglio"]["debiti_finanziari_lungo"] += val
        elif target == "debiti_finanziari_breve":
            sp["passivo"]["pfn"]["dettaglio"]["debiti_finanziari_breve"] += val
        elif target == "debiti_operativi":
            sp["passivo"]["debiti_operativi"]["totale"] += val

        rerouted += 1
        deviazioni.append({
            "tipo": "reroute_semantico",
            "descrizione": (
                f"'{row_id}' ({val:,}€) spostato da {current_bucket} → {target} "
                f"(conf={hint.confidence}, rationale={hint.rationale_type})"
            ),
            "impatto": f"Reclassificazione basata su evidenza semantica",
        })

    # Recalculate PFN totale after reroutes
    if rerouted > 0:
        pfn_det = sp["passivo"]["pfn"]["dettaglio"]
        pfn_lungo = pfn_det.get("debiti_finanziari_lungo", 0)
        pfn_breve = pfn_det.get("debiti_finanziari_breve", 0)
        cassa = pfn_det.get("disponibilita_liquide_sottratte", 0)
        sp["passivo"]["pfn"]["totale"] = calcola_pfn(pfn_lungo, pfn_breve, cassa)

        # Recalculate CCON
        ccon_det = sp["attivo"]["ccon"]["dettaglio"]
        debiti_op = sp["passivo"]["debiti_operativi"]["totale"]
        ccon_det["debiti_operativi_sottratti"] = debiti_op
        sp["attivo"]["ccon"]["totale"] = calcola_ccon(
            ccon_det.get("crediti_commerciali", 0),
            ccon_det.get("rimanenze", 0),
            ccon_det.get("altri_crediti_operativi", 0),
            debiti_op,
        )

    result["deviazioni"] = deviazioni
    result["voci_non_mappate"] = voci_non_mappate

    # Confidence adjustment
    confidence = result.get("confidence", 0.5)
    if rerouted > 0:
        confidence += min(rerouted * 0.02, 0.06)  # boost for evidence-based changes
    if unresolved > 0:
        confidence -= min(unresolved * 0.03, 0.1)  # penalize unresolved
    if supported > 0:
        confidence += min(supported * 0.01, 0.05)  # slight boost for confirmation
    result["confidence"] = max(0.0, min(1.0, round(confidence, 2)))

    result["n_hints_rerouted"] = rerouted
    result["n_hints_unresolved"] = unresolved
    result["n_hints_confirmed"] = supported

    # Provenance: trace how each key bucket was determined
    result["provenance"] = {
        "metodo": "deterministico+evidenze",
        "n_hints_totali": len(hints),
        "reroutes": [
            d for d in deviazioni
            if isinstance(d, dict) and d.get("tipo") == "reroute_semantico"
        ],
        "unresolved": voci_non_mappate,
        "confirmed_by_evidence": supported,
        "bucket_sources": {
            "debiti_finanziari_lungo": "fuzzy" + ("+hint" if any(
                h.suggested_classification == "debiti_finanziari_lungo"
                for h in hints
            ) else ""),
            "debiti_finanziari_breve": "fuzzy" + ("+hint" if any(
                h.suggested_classification == "debiti_finanziari_breve"
                for h in hints
            ) else ""),
            "debiti_operativi": "fuzzy" + ("+hint" if any(
                h.suggested_classification == "debiti_operativi"
                for h in hints
            ) else ""),
        },
    }

    return result


def _verifica_quadratura_risultato(risultati_per_anno: dict) -> list[str]:
    """Verifica la quadratura SP dei risultati riclassificati.

    Returns:
        Lista di errori trovati (vuota se tutto ok).
    """
    errori = []
    for anno, res in risultati_per_anno.items():
        sp = res.get("sp_riclassificato", {})
        quad = sp.get("quadratura", {})
        if not quad.get("ok", False):
            delta = quad.get("delta", 0)
            errori.append(
                f"Anno {anno}: SP non quadra, delta={delta:,}€ "
                f"(attivo={quad.get('totale_attivo', 0):,}, "
                f"passivo={quad.get('totale_passivo', 0):,})"
            )
    return errori


def _retry_riclassifica_con_feedback(
    schema: dict,
    checker_report: dict,
    risultato_precedente: dict,
    errori: list[str],
) -> dict:
    """Ritenta la riclassifica LLM con feedback sugli errori."""
    task_input = _prepara_input_riclassifica(schema, checker_report)
    task_input["retry"] = True
    task_input["risultato_precedente"] = risultato_precedente
    task_input["errori_da_correggere"] = errori
    task_input["istruzioni"] += (
        "\n\nATTENZIONE: il tentativo precedente aveva errori. "
        "Correggi i seguenti problemi:\n"
        + "\n".join(f"- {e}" for e in errori)
        + "\nVerifica attentamente la quadratura SP prima di rispondere."
    )

    try:
        risultato = agent_loop(
            nome_agente="skill_riclassifica",
            task_input=task_input,
            max_turns=15,
        )
    except Exception as e:
        return {"error": str(e)}

    return risultato


def _score_candidate(risultati: dict[str, Any], anni: list[str]) -> dict:
    """Score a reclassification candidate for selection.

    Returns dict with: valid (bool), quad_errors (int), avg_confidence,
    n_unresolved, reasons (list of rejection reasons).
    """
    if not risultati:
        return {"valid": False, "quad_errors": 999, "avg_confidence": 0,
                "n_unresolved": 999, "reasons": ["no results"]}

    errori = _verifica_quadratura_risultato(risultati)
    confidences = [r.get("confidence", 0) for r in risultati.values()]
    avg_conf = sum(confidences) / max(len(confidences), 1)
    n_unresolved = sum(
        len(r.get("voci_non_mappate", [])) for r in risultati.values()
    )

    return {
        "valid": len(errori) == 0,
        "quad_errors": len(errori),
        "avg_confidence": round(avg_conf, 3),
        "n_unresolved": n_unresolved,
        "reasons": errori,
    }


def _pick_best_candidate(candidates: list[tuple[str, dict, dict, float]]) -> tuple[str, dict]:
    """Pick the best reclassification candidate.

    Args:
        candidates: list of (name, risultati_per_anno, score_dict, elapsed_s)

    Selection logic:
      1. Valid candidates (quad passes) always beat invalid ones
      2. Among valid: highest avg_confidence wins
      3. Among invalid: fewest quad_errors wins
    """
    valid = [(n, r, s, t) for n, r, s, t in candidates if s["valid"]]
    if valid:
        # Pick highest confidence among valid
        best = max(valid, key=lambda x: x[2]["avg_confidence"])
        return best[0], best[1]

    # No valid candidate — pick the one with fewest errors
    best = min(candidates, key=lambda x: (x[2]["quad_errors"], -x[2]["avg_confidence"]))
    return best[0], best[1]


def esegui_riclassifica(
    schema: dict,
    checker_report: dict,
    bundle: Optional[ExtractionBundle] = None,
) -> dict:
    """Esegue la riclassificazione con candidate selection.

    Generates up to 3 candidates:
      1. LLM (primary)
      2. LLM retry with feedback (only if #1 fails quadratura)
      3. Deterministic + evidence (always generated as fallback)

    Picks the best valid candidate. If none pass quadratura, picks
    the least-bad one.

    Args:
        schema: Schema normalizzato JSON.
        checker_report: Report del checker pre-riclassifica.
        bundle: Optional ExtractionBundle with classification hints.

    Returns:
        Risultato riclassificazione per tutti gli anni.
    """
    import time as _time

    anni = [str(a) for a in schema.get("anni_estratti", [])]
    azienda = schema.get("azienda", "sconosciuta")
    formato = schema.get("metadata", {}).get("formato", "")
    hints = bundle.classification_hints if bundle else []

    # Collect candidates: (name, risultati_per_anno, score, elapsed)
    candidates: list[tuple[str, dict, dict, float]] = []
    timing: dict[str, float] = {}

    # --- Candidate 1: LLM ---
    print(f"  Metodo: LLM (formato {formato})")
    t0 = _time.time()
    task_input = _prepara_input_riclassifica(schema, checker_report)

    try:
        risultato_llm = agent_loop(
            nome_agente="skill_riclassifica",
            task_input=task_input,
            max_turns=15,
        )
    except Exception as e:
        print(f"  [LLM] Exception: {e}")
        risultato_llm = {"error": str(e)}

    elapsed_llm = round(_time.time() - t0, 1)
    timing["llm"] = elapsed_llm

    risultati_llm: dict[str, Any] = {}
    if "error" not in risultato_llm:
        risultati_llm = _estrai_risultati_llm(risultato_llm, anni)

    if risultati_llm:
        score_llm = _score_candidate(risultati_llm, anni)
        candidates.append(("llm", risultati_llm, score_llm, elapsed_llm))
        status = "PASS" if score_llm["valid"] else f"FAIL ({score_llm['quad_errors']} quad errors)"
        print(f"  [LLM] {status}, confidence={score_llm['avg_confidence']}, tempo={elapsed_llm}s")

        # --- Candidate 2: LLM retry (only if LLM failed quadratura) ---
        if not score_llm["valid"]:
            print(f"  [RETRY] Quadratura fallita, ritento con feedback...")
            t1 = _time.time()
            risultato_retry = _retry_riclassifica_con_feedback(
                schema, checker_report, risultato_llm, score_llm["reasons"],
            )
            elapsed_retry = round(_time.time() - t1, 1)
            timing["llm_retry"] = elapsed_retry

            if "error" not in risultato_retry:
                risultati_retry = _estrai_risultati_llm(risultato_retry, anni)
                if risultati_retry:
                    score_retry = _score_candidate(risultati_retry, anni)
                    candidates.append(("llm_retry", risultati_retry, score_retry, elapsed_retry))
                    status = "PASS" if score_retry["valid"] else f"FAIL ({score_retry['quad_errors']} errors)"
                    print(f"  [RETRY] {status}, confidence={score_retry['avg_confidence']}, tempo={elapsed_retry}s")
    else:
        if "error" not in risultato_llm:
            print("  [LLM] Risposta non parsabile.")

    # --- Candidate 3: Deterministic + evidence (always generated) ---
    t2 = _time.time()
    risultati_det: dict[str, Any] = {}
    if hints:
        for anno in anni:
            risultati_det[anno] = _riclassifica_con_evidenze(schema, anno, hints)
        det_name = "deterministico+evidenze"
    else:
        for anno in anni:
            risultati_det[anno] = _riclassifica_deterministico(schema, anno)
        det_name = "deterministico"
    elapsed_det = round(_time.time() - t2, 1)
    timing[det_name] = elapsed_det

    score_det = _score_candidate(risultati_det, anni)
    candidates.append((det_name, risultati_det, score_det, elapsed_det))
    status = "PASS" if score_det["valid"] else f"FAIL ({score_det['quad_errors']} errors)"
    print(f"  [{det_name.upper()}] {status}, confidence={score_det['avg_confidence']}, tempo={elapsed_det}s")

    # --- Selection ---
    metodo, risultati_per_anno = _pick_best_candidate(candidates)
    print(f"  Metodo selezionato: {metodo}")

    # Log rejected candidates
    rejected = []
    for name, _, score, elapsed in candidates:
        if name != metodo:
            rejected.append({
                "candidato": name,
                "valid": score["valid"],
                "quad_errors": score["quad_errors"],
                "avg_confidence": score["avg_confidence"],
                "tempo_s": elapsed,
                "motivo_scarto": score["reasons"] if not score["valid"] else ["non selezionato (confidence inferiore)"],
            })

    return {
        "azienda": azienda,
        "metodo": metodo,
        "risultati_per_anno": risultati_per_anno,
        "candidate_selection": {
            "n_candidates": len(candidates),
            "selected": metodo,
            "rejected": rejected,
            "timing": timing,
            "total_reclassifica_s": round(sum(timing.values()), 1),
        },
    }


# ---------------------------------------------------------------------------
# 3. CHECKER POST-RICLASSIFICA  (deterministico)
# ---------------------------------------------------------------------------

def _esegui_post_checker(risultato_riclassifica: dict, schema_originale: dict) -> dict:
    """Verifica coerenza e quadratura dei dati riclassificati.

    Args:
        risultato_riclassifica: Output di esegui_riclassifica.
        schema_originale: Schema normalizzato originale.

    Returns:
        Report post-checker con severity per anno.
    """
    risultati_per_anno: dict[str, Any] = {}
    anni = [str(a) for a in schema_originale.get("anni_estratti", [])]

    for anno in anni:
        checks: list[dict] = []
        dati_anno = risultato_riclassifica.get("risultati_per_anno", {}).get(anno, {})

        sp = dati_anno.get("sp_riclassificato", {})
        ce = dati_anno.get("ce_riclassificato", {})
        confidence = dati_anno.get("confidence", 0)
        voci_nm = dati_anno.get("voci_non_mappate", [])

        # Check RICLASS_QUADRATURA
        quad = sp.get("quadratura", {})
        if quad.get("ok"):
            checks.append({
                "codice": "RICLASS_QUADRATURA",
                "esito": "pass",
                "severity_contributo": "ok",
                "dettaglio": (
                    f"SP riclassificato quadra: attivo={quad.get('totale_attivo', 0):,}, "
                    f"passivo={quad.get('totale_passivo', 0):,}"
                ),
            })
        else:
            delta = quad.get("delta", 0)
            checks.append({
                "codice": "RICLASS_QUADRATURA",
                "esito": "fail",
                "severity_contributo": "critical",
                "dettaglio": (
                    f"SP riclassificato NON quadra: delta={delta:,}€ "
                    f"(attivo={quad.get('totale_attivo', 0):,}, "
                    f"passivo={quad.get('totale_passivo', 0):,})"
                ),
            })

        # Check RICLASS_UTILE — utile CE riclassificato vs utile normalizzato
        utile_dich = schema_originale.get("metadata", {}).get(
            "utile_dichiarato", {}
        ).get(anno)
        utile_ricl = ce.get("utile_netto", 0) if ce else 0

        if utile_dich is not None:
            delta_utile = abs(utile_ricl - utile_dich)

            # Per bilanci consolidati, l'utile CE include la quota terzi
            # mentre l'utile_dichiarato potrebbe essere solo del gruppo.
            # Cerchiamo la quota terzi nello schema per calcolare la tolleranza.
            tolleranza_utile = 1
            for v in schema_originale.get("ce", []):
                label_low = v.get("label", "").lower()
                if "pertinenza" in label_low and "terzi" in label_low:
                    qt = v.get("valore", {}).get(anno, 0) or 0
                    tolleranza_utile = max(tolleranza_utile, abs(qt) + 1)
                    break

            if delta_utile <= tolleranza_utile:
                checks.append({
                    "codice": "RICLASS_UTILE",
                    "esito": "pass",
                    "severity_contributo": "ok",
                    "dettaglio": (
                        f"Utile netto CE riclassificato ({utile_ricl:,}) "
                        f"= utile dichiarato ({utile_dich:,})"
                        + (f" [tolleranza consolidato: quota terzi {tolleranza_utile-1:,}€]"
                           if tolleranza_utile > 1 else "")
                    ),
                })
            else:
                checks.append({
                    "codice": "RICLASS_UTILE",
                    "esito": "warn",
                    "severity_contributo": "warning",
                    "dettaglio": (
                        f"Utile netto CE riclassificato ({utile_ricl:,}) "
                        f"≠ utile dichiarato ({utile_dich:,}), delta: {delta_utile:,}€"
                    ),
                })

        # Check RICLASS_CONFIDENCE
        if confidence < 0.5:
            checks.append({
                "codice": "RICLASS_CONFIDENCE",
                "esito": "fail",
                "severity_contributo": "critical",
                "dettaglio": f"Confidence riclassifica troppo bassa: {confidence}",
            })
        elif confidence < 0.8:
            checks.append({
                "codice": "RICLASS_CONFIDENCE",
                "esito": "warn",
                "severity_contributo": "warning",
                "dettaglio": f"Confidence riclassifica bassa: {confidence}",
            })
        else:
            checks.append({
                "codice": "RICLASS_CONFIDENCE",
                "esito": "pass",
                "severity_contributo": "ok",
                "dettaglio": f"Confidence riclassifica: {confidence}",
            })

        # Check VOCI_NON_MAPPATE
        if voci_nm:
            tot_attivo = sp.get("quadratura", {}).get("totale_attivo", 1)
            peso = sum(abs(v.get("valore", 0)) for v in voci_nm if isinstance(v, dict))
            pct = (peso / tot_attivo * 100) if tot_attivo else 0

            if pct > 5:
                sev = "critical"
            elif pct > 1:
                sev = "warning"
            else:
                sev = "warning"

            checks.append({
                "codice": "VOCI_NON_MAPPATE",
                "esito": "fail" if sev == "critical" else "warn",
                "severity_contributo": sev,
                "dettaglio": (
                    f"{len(voci_nm)} voci non mappate "
                    f"(peso: {pct:.1f}% del totale attivo)"
                ),
            })

        # Check RICLASS_COMPLETEZZA — aggregati non vuoti
        if sp:
            for nome_agg in ("capitale_fisso_netto", "ccon", "altre_attivita_non_operative"):
                sezione_att = sp.get("attivo", {}).get(nome_agg, {})
                if sezione_att.get("totale", 0) == 0:
                    checks.append({
                        "codice": "RICLASS_COMPLETEZZA",
                        "esito": "warn",
                        "severity_contributo": "warning",
                        "dettaglio": f"Aggregato SP attivo '{nome_agg}' vale 0",
                    })

        # Check CCON_COERENZA
        if sp:
            ccon_val = sp.get("attivo", {}).get("ccon", {}).get("totale", 0)
            if ccon_val < 0:
                checks.append({
                    "codice": "CCON_COERENZA",
                    "esito": "warn",
                    "severity_contributo": "warning",
                    "dettaglio": f"CCON negativo ({ccon_val:,}€) — verificare",
                })

        # Check PFN_SEGNO (informativo)
        if sp:
            pfn_val = sp.get("passivo", {}).get("pfn", {}).get("totale", 0)
            checks.append({
                "codice": "PFN_SEGNO",
                "esito": "pass",
                "severity_contributo": "ok",
                "dettaglio": (
                    f"PFN = {pfn_val:,}€ "
                    f"({'indebitamento netto' if pfn_val > 0 else 'posizione finanziaria netta positiva'})"
                ),
            })

        severity_label, score = calcola_severity(checks)

        risultati_per_anno[anno] = {
            "severity": severity_label,
            "score": score,
            "checks": checks,
        }

    severity_globale = "ok"
    for anno_res in risultati_per_anno.values():
        if anno_res["severity"] == "critical":
            severity_globale = "critical"
            break
        if anno_res["severity"] == "warning":
            severity_globale = "warning"

    return {
        "azienda": risultato_riclassifica.get("azienda", ""),
        "tipo_check": "post_riclassifica",
        "severity_globale": severity_globale,
        "risultati_per_anno": risultati_per_anno,
    }


# ---------------------------------------------------------------------------
# 4. PIPELINE COMPLETA
# ---------------------------------------------------------------------------

def esegui_pipeline(
    schema: dict,
    bundle: Optional[ExtractionBundle] = None,
) -> dict:
    """Esegue la pipeline completa: checker → riclassifica → post-checker.

    Args:
        schema: Schema normalizzato JSON.
        bundle: Optional ExtractionBundle with classification hints.

    Returns:
        Dict con risultati di tutte le fasi.
    """
    azienda = schema.get("azienda", "sconosciuta")
    print(f"\n{'='*70}")
    print(f"  PIPELINE ANALISI BILANCIO — {azienda}")
    print(f"{'='*70}")

    # --- FASE 1: Checker pre-riclassifica ---
    print(f"\n[FASE 1] Checker pre-riclassifica...")
    checker_report = esegui_checker(schema)
    severity = checker_report["severity_globale"]
    print(f"  Severity globale: {severity}")

    for anno, res in checker_report["risultati_per_anno"].items():
        n_warn = sum(
            1 for c in res["checks"]
            if c.get("severity_contributo") == "warning"
        )
        n_crit = sum(
            1 for c in res["checks"]
            if c.get("severity_contributo") == "critical"
        )
        print(f"  Anno {anno}: severity={res['severity']}, score={res['score']}, "
              f"warnings={n_warn}, critical={n_crit}")

    if not checker_report["puo_procedere"]:
        print(f"\n  [STOP] Severity critical — impossibile procedere.")
        print(f"  Issues critiche:")
        for anno, res in checker_report["risultati_per_anno"].items():
            for c in res["checks"]:
                if c.get("severity_contributo") == "critical":
                    print(f"    - [{anno}] {c['codice']}: {c['dettaglio']}")
        return {
            "azienda": azienda,
            "completata": False,
            "fase_bloccante": "checker_pre_riclassifica",
            "checker_pre": checker_report,
            "riclassifica": None,
            "checker_post": None,
        }

    # --- FASE 2: Riclassificazione ---
    print(f"\n[FASE 2] Riclassificazione...")
    risultato_riclassifica = esegui_riclassifica(schema, checker_report, bundle=bundle)
    metodo = risultato_riclassifica.get("metodo", "?")
    print(f"  Metodo: {metodo}")

    for anno, res in risultato_riclassifica.get("risultati_per_anno", {}).items():
        conf = res.get("confidence", "N/A")
        n_dev = len(res.get("deviazioni", []))
        n_nm = len(res.get("voci_non_mappate", []))
        print(f"  Anno {anno}: confidence={conf}, deviazioni={n_dev}, non_mappate={n_nm}")

        # Stampa CCON e PFN
        sp = res.get("sp_riclassificato", {})
        ccon_val = sp.get("attivo", {}).get("ccon", {}).get("totale", "N/A")
        pfn_val = sp.get("passivo", {}).get("pfn", {}).get("totale", "N/A")
        print(f"    CCON: {ccon_val:,}€" if isinstance(ccon_val, int) else f"    CCON: {ccon_val}")
        print(f"    PFN:  {pfn_val:,}€" if isinstance(pfn_val, int) else f"    PFN:  {pfn_val}")

        ce = res.get("ce_riclassificato", {})
        ebitda = ce.get("ebitda", "N/A")
        utile = ce.get("utile_netto", "N/A")
        print(f"    EBITDA: {ebitda:,}€" if isinstance(ebitda, int) else f"    EBITDA: {ebitda}")
        print(f"    Utile netto: {utile:,}€" if isinstance(utile, int) else f"    Utile netto: {utile}")

        if res.get("deviazioni"):
            for dev in res["deviazioni"]:
                print(f"    [DEV] {dev}")

    # --- FASE 3: Checker post-riclassifica ---
    print(f"\n[FASE 3] Checker post-riclassifica...")
    checker_post = _esegui_post_checker(risultato_riclassifica, schema)
    severity_post = checker_post["severity_globale"]
    print(f"  Severity globale post: {severity_post}")

    for anno, res in checker_post["risultati_per_anno"].items():
        print(f"  Anno {anno}: severity={res['severity']}, score={res['score']}")
        for c in res["checks"]:
            marker = (
                "PASS" if c["esito"] == "pass"
                else "WARN" if c["esito"] == "warn"
                else "FAIL"
            )
            print(f"    [{marker}] {c['codice']}: {c['dettaglio']}")

    print(f"\n{'='*70}")
    print(f"  PIPELINE COMPLETATA — severity finale: {severity_post}")
    print(f"{'='*70}\n")

    return {
        "azienda": azienda,
        "completata": True,
        "severity_finale": severity_post,
        "checker_pre": checker_report,
        "riclassifica": risultato_riclassifica,
        "checker_post": checker_post,
    }


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python -m agents.pipeline <schema_json_path>")
        sys.exit(1)

    schema_path = Path(sys.argv[1])
    if not schema_path.exists():
        print(f"[ERRORE] File non trovato: {schema_path}")
        sys.exit(1)

    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)

    print(f"Schema caricato: {schema.get('azienda')}")
    print(f"Anni: {schema.get('anni_estratti')}")
    print(f"Formato: {schema.get('metadata', {}).get('formato', 'N/A')}")
    print(f"Voci SP: {len(schema.get('sp', []))}, Voci CE: {len(schema.get('ce', []))}")

    risultato = esegui_pipeline(schema)

    azienda = schema.get("azienda", "output")
    nome_file = azienda.lower().replace(" ", "_").replace(".", "")
    output_path = ROOT / "data" / "output" / f"{nome_file}_pipeline_result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(risultato, f, indent=2, ensure_ascii=False)
    print(f"Risultato salvato in: {output_path}")
