"""Pipeline runner: estrazione → checker → riclassificatore → post-checker.

Collega le fasi deterministiche (checker) con quelle LLM-powered (riclassifica)
per produrre SP e CE riclassificati a partire dallo schema normalizzato.
"""

import json
import sys
from pathlib import Path
from typing import Any

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
    """Riclassifica in modo deterministico quando le voci IFRS sono chiare.

    Questa funzione gestisce il mapping diretto per bilanci IFRS di Enervit
    e casi simili dove le label sono sufficientemente esplicite.
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

    # --- SP ATTIVO ---
    # Immobilizzazioni materiali nette (uso il totale se disponibile)
    imm_mat = sp_voci.get("totale_immobilizzazioni_materiali", 0)
    sp["attivo"]["capitale_fisso_netto"]["dettaglio"]["immobilizzazioni_materiali_nette"] = imm_mat

    # Immobilizzazioni immateriali nette
    imm_imm = sp_voci.get("totale_immobilizzazioni_immateriali", 0)
    sp["attivo"]["capitale_fisso_netto"]["dettaglio"]["immobilizzazioni_immateriali_nette"] = imm_imm

    # Immobilizzazioni finanziarie — partecipazioni + crediti finanziari lungo
    partecipazioni = sp_voci.get("partecipazioni", 0)
    crediti_fin_lt = sp_voci.get("altri_crediti_finanziari_a_lungo_termine", 0)
    imm_fin = partecipazioni + crediti_fin_lt
    sp["attivo"]["capitale_fisso_netto"]["dettaglio"]["immobilizzazioni_finanziarie"] = imm_fin

    cfn = imm_mat + imm_imm + imm_fin
    sp["attivo"]["capitale_fisso_netto"]["totale"] = cfn

    # Crediti commerciali (include anche infragruppo commerciale)
    crediti_comm = sp_voci.get(
        "crediti_commerciali_e_altre_attività_a_breve_termine", 0
    )
    crediti_comm_infra = sp_voci.get(
        "crediti_commerciali_verso_società_controllate_collegate", 0
    )
    crediti_comm_tot = crediti_comm + crediti_comm_infra
    sp["attivo"]["ccon"]["dettaglio"]["crediti_commerciali"] = crediti_comm_tot

    # Rimanenze
    rimanenze = sp_voci.get("rimanenze", 0)
    sp["attivo"]["ccon"]["dettaglio"]["rimanenze"] = rimanenze

    # Altri crediti operativi — imposte correnti attive
    att_fiscali_correnti = sp_voci.get("attività_fiscali_per_imposte_correnti", 0)
    sp["attivo"]["ccon"]["dettaglio"]["altri_crediti_operativi"] = att_fiscali_correnti

    # Altre attività non operative
    att_fiscali_diff = sp_voci.get("attività_fiscali_per_imposte_differite", 0)
    crediti_fin_bt = sp_voci.get("altri_crediti_finanziari_a_breve_termine", 0)
    sp["attivo"]["altre_attivita_non_operative"]["dettaglio"]["attivita_fiscali_differite"] = att_fiscali_diff
    sp["attivo"]["altre_attivita_non_operative"]["dettaglio"]["crediti_finanziari"] = crediti_fin_bt
    sp["attivo"]["altre_attivita_non_operative"]["totale"] = att_fiscali_diff + crediti_fin_bt

    # Disponibilità liquide (entrano in PFN come sottratte)
    cassa = sp_voci.get("cassa_e_disponibilità_liquide", 0)

    # --- SP PASSIVO ---
    # Patrimonio Netto
    pn_totale = sp_voci.get("totale_patrimonio_netto", 0)
    capitale = sp_voci.get("capitale_emesso", 0)
    utile_es = sp_voci.get("utile_d_esercizio", 0)
    riserve = pn_totale - capitale - utile_es
    sp["passivo"]["patrimonio_netto"]["totale"] = pn_totale
    sp["passivo"]["patrimonio_netto"]["dettaglio"]["capitale_sociale"] = capitale
    sp["passivo"]["patrimonio_netto"]["dettaglio"]["riserve"] = riserve
    sp["passivo"]["patrimonio_netto"]["dettaglio"]["utile_perdita_esercizio"] = utile_es

    # Debiti finanziari lungo (finanziamenti LT)
    fin_lt = sp_voci.get("finanziamenti_a_lungo_termine", 0)
    sp["passivo"]["pfn"]["dettaglio"]["debiti_finanziari_lungo"] = fin_lt

    # Debiti finanziari breve (finanziamenti BT + debiti vs altri finanziatori)
    fin_bt = sp_voci.get("finanziamenti_a_breve_termine", 0)
    deb_altri_fin = sp_voci.get("debiti_verso_altri_finanziatori", 0)
    sp["passivo"]["pfn"]["dettaglio"]["debiti_finanziari_breve"] = fin_bt + deb_altri_fin

    # Disponibilità liquide sottratte
    sp["passivo"]["pfn"]["dettaglio"]["disponibilita_liquide_sottratte"] = cassa

    pfn = calcola_pfn(fin_lt, fin_bt + deb_altri_fin, cassa)
    sp["passivo"]["pfn"]["totale"] = pfn

    # Debiti operativi — debiti commerciali + infragruppo comm. + fiscali + TFR + altre passività
    deb_comm = sp_voci.get(
        "debiti_commerciali_e_altre_passività_a_breve_termine", 0
    )
    deb_comm_infra = sp_voci.get(
        "debiti_commerciali_verso_società_controllate_collegate", 0
    )
    deb_fiscali = sp_voci.get("passività_fiscali_per_imposte_correnti", 0)
    tfr = sp_voci.get(
        "benefici_successivi_alla_cessazione_del_rapporto_di_lavoro", 0
    )
    altre_pass_lt = sp_voci.get("altre_passività_a_lungo_termine", 0)

    debiti_operativi = deb_comm + deb_comm_infra + deb_fiscali + tfr + altre_pass_lt
    sp["passivo"]["debiti_operativi"]["totale"] = debiti_operativi

    # CCON
    ccon = calcola_ccon(crediti_comm_tot, rimanenze, att_fiscali_correnti, debiti_operativi)
    sp["attivo"]["ccon"]["dettaglio"]["debiti_operativi_sottratti"] = debiti_operativi
    sp["attivo"]["ccon"]["totale"] = ccon

    # Quadratura SP
    # Totale attivo = CFN + attività CCON lorde + altre attività + cassa
    totale_attivo_calc = (
        cfn
        + crediti_comm_tot + rimanenze + att_fiscali_correnti
        + att_fiscali_diff + crediti_fin_bt
        + cassa
    )
    totale_passivo_calc = pn_totale + fin_lt + fin_bt + deb_altri_fin + debiti_operativi
    quad = verifica_quadratura(totale_attivo_calc, totale_passivo_calc)
    sp["quadratura"] = quad

    # Se non quadra, annotiamo
    if not quad["ok"]:
        # Usiamo i totali dichiarati dal bilancio come riferimento
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
    ricavi = _fuzzy_get(ce_voci, "ricavi")
    altri_ricavi = _fuzzy_get(ce_voci, "altri_ricavi_e_proventi", "altri_ricavi")
    var_rim_pf = _fuzzy_get(ce_voci,
        "variazione_nelle_rimanenze_di_prodotti_finiti",
        "variazione_rimanenze_prodotti",
    )
    ce["ricavi_netti"] = ricavi + altri_ricavi + var_rim_pf

    materie_prime = _fuzzy_get(ce_voci,
        "materie_prime_materiali_di_confezionamento",
        "materie_prime",
        "costi_materie_prime",
    )
    var_rim_mp = _fuzzy_get(ce_voci,
        "variazione_nelle_rimanenze_di_materie_prime",
        "variazione_rimanenze_materie",
    )
    ce["costi_materie_prime_merci"] = materie_prime + var_rim_mp

    # Valore aggiunto industriale = ricavi netti + costi materie prime (negativo)
    ce["valore_aggiunto_industriale"] = ce["ricavi_netti"] + ce["costi_materie_prime_merci"]

    # "altri costi operativi" nel CE IFRS include servizi + godimento + oneri diversi
    altri_costi_op = _fuzzy_get(ce_voci, "altri_costi_operativi", "costi_servizi")
    ce["costi_servizi_godimento"] = altri_costi_op

    costo_personale = _fuzzy_get(ce_voci, "costo_del_personale", "costi_personale")
    ce["costi_personale"] = costo_personale

    # EBITDA
    ce["ebitda"] = (
        ce["valore_aggiunto_industriale"]
        + ce["costi_servizi_godimento"]
        + ce["costi_personale"]
    )

    # Ammortamenti e svalutazioni
    ammortamenti = _fuzzy_get(ce_voci, "ammortamenti")
    accantonamenti_sval = _fuzzy_get(ce_voci, "accantonamenti_e_svalutazioni", "accantonamenti")
    ce["ammortamenti_svalutazioni"] = ammortamenti + accantonamenti_sval

    # EBIT
    ce["ebit"] = ce["ebitda"] + ce["ammortamenti_svalutazioni"]

    # Proventi/oneri finanziari
    ricavi_fin = _fuzzy_get(ce_voci, "ricavi_finanziari", "proventi_finanziari")
    costi_fin = _fuzzy_get(ce_voci, "costi_finanziari", "oneri_finanziari")
    cambi = _fuzzy_get(ce_voci, "utile_derivante_da_transizioni_in_valute", "utili_perdite_su_cambi")
    ce["proventi_oneri_finanziari"] = ricavi_fin + costi_fin + cambi

    # EBT
    ce["ebt"] = ce["ebit"] + ce["proventi_oneri_finanziari"]

    # Imposte
    imposte = _fuzzy_get(ce_voci, "imposte_sul_reddito", "imposte")
    ce["imposte"] = imposte

    # Utile netto
    ce["utile_netto"] = ce["ebt"] + ce["imposte"]

    # Verifica coerenza con EBITDA dichiarato
    ebitda_dichiarato = ce_voci.get("ebitda_margine_operativo_lordo", 0)
    if ebitda_dichiarato != 0 and abs(ce["ebitda"] - ebitda_dichiarato) > 1:
        deviazioni.append(
            f"EBITDA calcolato ({ce['ebitda']:,}) vs dichiarato ({ebitda_dichiarato:,}), "
            f"delta: {ce['ebitda'] - ebitda_dichiarato:,}"
        )

    # Verifica coerenza con EBIT dichiarato
    ebit_dichiarato = ce_voci.get("ebit_risultato_operativo", 0)
    if ebit_dichiarato != 0 and abs(ce["ebit"] - ebit_dichiarato) > 1:
        deviazioni.append(
            f"EBIT calcolato ({ce['ebit']:,}) vs dichiarato ({ebit_dichiarato:,}), "
            f"delta: {ce['ebit'] - ebit_dichiarato:,}"
        )

    # Verifica utile netto vs dichiarato
    utile_dich = schema.get("metadata", {}).get("utile_dichiarato", {}).get(anno, 0)
    if utile_dich and abs(ce["utile_netto"] - utile_dich) > 1:
        deviazioni.append(
            f"Utile netto calcolato ({ce['utile_netto']:,}) vs dichiarato ({utile_dich:,})"
        )

    # Confidence
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


def esegui_riclassifica(schema: dict, checker_report: dict) -> dict:
    """Esegue la riclassificazione.

    Per bilanci IFRS con voci chiare, usa il mapping deterministico.
    Per bilanci ambigui o con voci non standard, invoca il LLM
    tramite agent_loop con skill_riclassifica come system prompt.

    Args:
        schema: Schema normalizzato JSON.
        checker_report: Report del checker pre-riclassifica.

    Returns:
        Risultato riclassificazione per tutti gli anni.
    """
    anni = [str(a) for a in schema.get("anni_estratti", [])]
    azienda = schema.get("azienda", "sconosciuta")
    formato = schema.get("metadata", {}).get("formato", "")

    # Strategia:
    # - Formato OIC → sempre LLM (le voci civilistiche richiedono interpretazione)
    # - Formato IFRS → deterministico se le voci matchano i pattern noti, LLM altrimenti
    # - Fallback a deterministico se LLM fallisce
    usa_llm = formato != "IFRS"  # OIC e formati sconosciuti → LLM

    if not usa_llm:
        # Anche per IFRS, se ci sono troppe voci ambigue → LLM
        voci_ambigue = sum(
            1 for sez in ("sp", "ce") for v in schema.get(sez, [])
            if v.get("non_standard") or "voce_non_standard" in v.get("flags", [])
        )
        if voci_ambigue > 3:
            usa_llm = True

    risultati_per_anno: dict[str, Any] = {}

    if usa_llm:
        print(f"  Metodo: LLM (formato {formato})")
        task_input = _prepara_input_riclassifica(schema, checker_report)

        try:
            risultato_llm = agent_loop(
                nome_agente="skill_riclassifica",
                task_input=task_input,
                max_turns=15,
            )
        except Exception as e:
            print(f"[WARN] LLM riclassifica exception: {e}. Fallback deterministico.")
            risultato_llm = {"error": str(e)}

        if "error" in risultato_llm:
            print(f"[WARN] LLM riclassifica fallito: {risultato_llm.get('error')}. Fallback.")
            usa_llm = False
        else:
            # Estrai risultati_per_anno dalla risposta LLM
            risultati_per_anno = _estrai_risultati_llm(risultato_llm, anni)
            if not risultati_per_anno:
                print("[WARN] Risposta LLM non parsabile. Fallback deterministico.")
                usa_llm = False

    if not usa_llm or not risultati_per_anno:
        # Mapping deterministico per anno
        for anno in anni:
            risultati_per_anno[anno] = _riclassifica_deterministico(schema, anno)

    return {
        "azienda": azienda,
        "metodo": "llm" if usa_llm and risultati_per_anno else "deterministico",
        "risultati_per_anno": risultati_per_anno,
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

def esegui_pipeline(schema: dict) -> dict:
    """Esegue la pipeline completa: checker → riclassifica → post-checker.

    Args:
        schema: Schema normalizzato JSON.

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
    risultato_riclassifica = esegui_riclassifica(schema, checker_report)
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
    # Carica schema normalizzato Enervit
    schema_path = ROOT / "data" / "output" / "enervit_schema_normalizzato.json"

    if not schema_path.exists():
        print(f"[ERRORE] File non trovato: {schema_path}")
        sys.exit(1)

    with open(schema_path, encoding="utf-8") as f:
        schema = json.load(f)

    print(f"Schema caricato: {schema.get('azienda')}")
    print(f"Anni: {schema.get('anni_estratti')}")
    print(f"Formato: {schema.get('metadata', {}).get('formato', 'N/A')}")
    print(f"Voci SP: {len(schema.get('sp', []))}, Voci CE: {len(schema.get('ce', []))}")

    # Esegui pipeline completa
    risultato = esegui_pipeline(schema)

    # Salva risultato
    output_path = ROOT / "data" / "output" / "enervit_pipeline_result.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(risultato, f, indent=2, ensure_ascii=False)
    print(f"Risultato salvato in: {output_path}")
