"""Agente analista: calcola indici, trend, alert e genera narrative."""

import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

# Aggiungi root al path per import
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.calcolatori import (
    roe, roi, ros, roa, ebitda_margin,
    indice_indipendenza_finanziaria, rapporto_indebitamento,
    copertura_immobilizzazioni, pfn_su_ebitda, pfn_su_pn,
    current_ratio, quick_ratio,
    giorni_crediti, giorni_debiti, giorni_magazzino, ciclo_cassa,
    variazione_yoy, cagr,
)


# ---------------------------------------------------------------------------
# Helpers per estrarre valori dalla struttura pipeline_result
# ---------------------------------------------------------------------------

def _estrai_valori_anno(risultato_anno: dict) -> dict:
    """Estrae tutti i valori rilevanti per il calcolo degli indici da un anno."""
    sp = risultato_anno["sp_riclassificato"]
    ce = risultato_anno["ce_riclassificato"]

    att = sp["attivo"]
    pas = sp["passivo"]

    cfn_totale = att["capitale_fisso_netto"]["totale"]
    cfn_det = att["capitale_fisso_netto"]["dettaglio"]
    ccon_det = att["ccon"]["dettaglio"]
    pn = pas["patrimonio_netto"]["totale"]
    pfn_det = pas["pfn"]["dettaglio"]
    pfn_totale = pas["pfn"]["totale"]
    debiti_op = pas["debiti_operativi"]["totale"]

    crediti_comm = ccon_det["crediti_commerciali"]
    rimanenze = ccon_det["rimanenze"]
    liquidita = pfn_det["disponibilita_liquide_sottratte"]
    debiti_fin_lungo = pfn_det["debiti_finanziari_lungo"]
    debiti_fin_breve = pfn_det["debiti_finanziari_breve"]

    # Debiti a breve totali = debiti finanziari breve + debiti operativi
    debiti_breve_totali = debiti_fin_breve + debiti_op

    # Totale attivo e passivo dalla quadratura
    totale_attivo = sp["quadratura"]["totale_attivo"]
    totale_passivo = sp["quadratura"]["totale_passivo"]

    # Capitale investito netto = CFN + CCON + altre attivita non operative
    cin = cfn_totale + att["ccon"]["totale"] + att.get("altre_attivita_non_operative", {}).get("totale", 0)

    # Costo del venduto approssimato = materie prime + servizi (per giorni magazzino)
    costi_mp = abs(ce.get("costi_materie_prime_merci", 0))
    costi_servizi = abs(ce.get("costi_servizi_godimento", 0))
    # Acquisti approssimati con costi materie prime
    acquisti = costi_mp
    # Costo venduto approssimato = materie prime + servizi
    costo_venduto = costi_mp + costi_servizi

    return {
        "ricavi_netti": ce["ricavi_netti"],
        "ebitda": ce["ebitda"],
        "ebit": ce["ebit"],
        "ebt": ce["ebt"],
        "utile_netto": ce["utile_netto"],
        "ammortamenti": abs(ce.get("ammortamenti_svalutazioni", 0)),
        "costi_personale": abs(ce.get("costi_personale", 0)),
        "valore_aggiunto": ce.get("valore_aggiunto_industriale", 0),
        "patrimonio_netto": pn,
        "pfn": pfn_totale,
        "debiti_operativi": debiti_op,
        "debiti_fin_lungo": debiti_fin_lungo,
        "debiti_fin_breve": debiti_fin_breve,
        "capitale_fisso_netto": cfn_totale,
        "capitale_investito_netto": cin,
        "totale_attivo": totale_attivo,
        "totale_passivo": totale_passivo,
        "crediti_commerciali": crediti_comm,
        "rimanenze": rimanenze,
        "liquidita": liquidita,
        "debiti_breve_totali": debiti_breve_totali,
        "acquisti": acquisti,
        "costo_venduto": costo_venduto,
    }


# ---------------------------------------------------------------------------
# Calcolo indici
# ---------------------------------------------------------------------------

def _calcola_indici_anno(v: dict, pn_medio: Optional[float] = None) -> dict:
    """Calcola tutti gli indici per un singolo anno."""
    # Se non abbiamo PN medio, usiamo PN corrente
    pn_m = pn_medio if pn_medio is not None else v["patrimonio_netto"]

    # Redditività
    val_roe = roe(v["utile_netto"], pn_m)
    val_roi = roi(v["ebit"], v["capitale_investito_netto"])
    val_ros = ros(v["ebit"], v["ricavi_netti"])
    val_roa = roa(v["ebit"], v["totale_attivo"])
    val_ebitda_m = ebitda_margin(v["ebitda"], v["ricavi_netti"])

    # Struttura finanziaria
    val_indip = indice_indipendenza_finanziaria(v["patrimonio_netto"], v["totale_passivo"])
    val_indeb = rapporto_indebitamento(v["pfn"], v["debiti_operativi"], v["patrimonio_netto"])
    val_cop_imm = copertura_immobilizzazioni(v["patrimonio_netto"], v["debiti_fin_lungo"], v["capitale_fisso_netto"])
    val_pfn_ebitda = pfn_su_ebitda(v["pfn"], v["ebitda"])
    val_pfn_pn = pfn_su_pn(v["pfn"], v["patrimonio_netto"])

    # Liquidità
    val_cr = current_ratio(v["crediti_commerciali"], v["rimanenze"], v["liquidita"], v["debiti_breve_totali"])
    val_qr = quick_ratio(v["crediti_commerciali"], v["liquidita"], v["debiti_breve_totali"])
    val_gg_cred = giorni_crediti(v["crediti_commerciali"], v["ricavi_netti"])
    val_gg_deb = giorni_debiti(v["debiti_operativi"], v["acquisti"])
    val_gg_mag = giorni_magazzino(v["rimanenze"], v["costo_venduto"])
    val_ciclo = ciclo_cassa(val_gg_cred, val_gg_mag, val_gg_deb)

    # Efficienza
    val_cp_va = None
    if v["valore_aggiunto"] and v["valore_aggiunto"] != 0:
        val_cp_va = v["costi_personale"] / v["valore_aggiunto"]
    val_inc_amm = None
    if v["ricavi_netti"] and v["ricavi_netti"] != 0:
        val_inc_amm = v["ammortamenti"] / v["ricavi_netti"]

    def _r(val, dec=4):
        return round(val, dec) if val is not None else None

    return {
        "redditivita": {
            "ROE": _r(val_roe),
            "ROI": _r(val_roi),
            "ROS": _r(val_ros),
            "ROA": _r(val_roa),
            "EBITDA_margin": _r(val_ebitda_m),
        },
        "struttura": {
            "indice_indipendenza_finanziaria": _r(val_indip),
            "rapporto_indebitamento": _r(val_indeb),
            "copertura_immobilizzazioni": _r(val_cop_imm),
            "pfn_ebitda": _r(val_pfn_ebitda),
            "pfn_pn": _r(val_pfn_pn),
        },
        "liquidita": {
            "current_ratio": _r(val_cr),
            "quick_ratio": _r(val_qr),
            "giorni_crediti": val_gg_cred,
            "giorni_debiti": val_gg_deb,
            "giorni_magazzino": val_gg_mag,
            "ciclo_cassa": val_ciclo,
        },
        "efficienza": {
            "costo_personale_su_va": _r(val_cp_va),
            "incidenza_ammortamenti": _r(val_inc_amm),
        },
    }


def _calcola_tutti_indici(risultati_per_anno: dict) -> tuple[dict, list[str]]:
    """Calcola indici per tutti gli anni. Restituisce (indici_struttura, anni_ordinati)."""
    anni = sorted(risultati_per_anno.keys())
    valori_per_anno = {}
    for anno in anni:
        valori_per_anno[anno] = _estrai_valori_anno(risultati_per_anno[anno])

    # Calcola PN medio per ROE (media tra anno corrente e precedente)
    indici_per_anno = {}
    for i, anno in enumerate(anni):
        pn_medio = None
        if i > 0:
            anno_prec = anni[i - 1]
            pn_medio = (valori_per_anno[anno]["patrimonio_netto"] + valori_per_anno[anno_prec]["patrimonio_netto"]) / 2
        indici_per_anno[anno] = _calcola_indici_anno(valori_per_anno[anno], pn_medio)

    # Riorganizza in formato spec: per categoria -> per indice -> per anno
    categorie = ["redditivita", "struttura", "liquidita", "efficienza"]
    indici = {}
    for cat in categorie:
        indici[cat] = {}
        # Prendi i nomi indici dal primo anno
        primo_anno = anni[0]
        for nome_indice in indici_per_anno[primo_anno][cat]:
            indici[cat][nome_indice] = {}
            for anno in anni:
                indici[cat][nome_indice][anno] = indici_per_anno[anno][cat][nome_indice]

    return indici, anni, valori_per_anno


# ---------------------------------------------------------------------------
# Trend e variazioni YoY
# ---------------------------------------------------------------------------

def _calcola_trend(indici: dict, anni: list[str]) -> list[dict]:
    """Calcola trend per ogni indice."""
    trend = []
    for cat, indici_cat in indici.items():
        for nome, valori in indici_cat.items():
            serie = [valori.get(a) for a in anni]
            serie_valida = [v for v in serie if v is not None]

            if len(serie_valida) < 2:
                continue

            # Direzione: confronta primo e ultimo valore valido
            primo = serie_valida[0]
            ultimo = serie_valida[-1]

            if ultimo > primo * 1.02:
                direzione = "crescente"
            elif ultimo < primo * 0.98:
                direzione = "decrescente"
            else:
                direzione = "stabile"

            variazione_periodo = ultimo - primo if primo != 0 else None

            # Significativo se variazione > 10% o se è un trend consistente
            variazione_pct = variazione_yoy(ultimo, primo)
            significativo = variazione_pct is not None and abs(variazione_pct) > 0.10

            entry = {
                "indice": nome,
                "categoria": cat,
                "direzione": direzione,
                "variazione_periodo": round(variazione_periodo, 4) if variazione_periodo is not None else None,
                "variazione_percentuale": round(variazione_pct, 4) if variazione_pct is not None else None,
                "significativo": significativo,
            }
            trend.append(entry)

    return trend


def _calcola_variazioni_yoy(indici: dict, anni: list[str]) -> dict:
    """Calcola variazioni YoY per ogni indice tra anni consecutivi."""
    variazioni = {}
    for cat, indici_cat in indici.items():
        variazioni[cat] = {}
        for nome, valori in indici_cat.items():
            variazioni[cat][nome] = {}
            for i in range(1, len(anni)):
                anno_corr = anni[i]
                anno_prec = anni[i - 1]
                v_corr = valori.get(anno_corr)
                v_prec = valori.get(anno_prec)
                if v_corr is not None and v_prec is not None:
                    var = variazione_yoy(v_corr, v_prec)
                    variazioni[cat][nome][f"{anno_prec}-{anno_corr}"] = round(var, 4) if var is not None else None
    return variazioni


# ---------------------------------------------------------------------------
# Alert
# ---------------------------------------------------------------------------

SOGLIE = {
    "indice_indipendenza_finanziaria": [
        {"tipo": "rischio", "condizione": "min", "soglia": 0.20, "msg": "Indipendenza finanziaria critica (< 20%)"},
        {"tipo": "attenzione", "condizione": "min", "soglia": 0.33, "msg": "Indipendenza finanziaria sotto il livello ottimale (< 33%)"},
    ],
    "rapporto_indebitamento": [
        {"tipo": "rischio", "condizione": "max", "soglia": 4.0, "msg": "Rapporto di indebitamento critico (> 4x)"},
        {"tipo": "attenzione", "condizione": "max", "soglia": 2.0, "msg": "Rapporto di indebitamento elevato (> 2x)"},
    ],
    "pfn_ebitda": [
        {"tipo": "rischio", "condizione": "max", "soglia": 4.0, "msg": "PFN/EBITDA critico (> 4x) - indebitamento insostenibile"},
        {"tipo": "attenzione", "condizione": "max", "soglia": 3.0, "msg": "PFN/EBITDA in zona di attenzione (> 3x)"},
    ],
    "pfn_pn": [
        {"tipo": "rischio", "condizione": "max", "soglia": 2.0, "msg": "PFN/PN critico (> 2x)"},
        {"tipo": "attenzione", "condizione": "max", "soglia": 1.0, "msg": "PFN/PN elevato (> 1x)"},
    ],
    "current_ratio": [
        {"tipo": "rischio", "condizione": "min", "soglia": 1.0, "msg": "Current ratio critico (< 1) - rischio di liquidita"},
        {"tipo": "attenzione", "condizione": "min", "soglia": 1.5, "msg": "Current ratio sotto il livello ottimale (< 1,5)"},
    ],
    "quick_ratio": [
        {"tipo": "attenzione", "condizione": "min", "soglia": 1.0, "msg": "Quick ratio sotto la soglia ottimale (< 1)"},
    ],
    "costo_personale_su_va": [
        {"tipo": "attenzione", "condizione": "max", "soglia": 0.60, "msg": "Incidenza costo del personale sul VA elevata (> 60%)"},
    ],
    "copertura_immobilizzazioni": [
        {"tipo": "rischio", "condizione": "min", "soglia": 1.0, "msg": "Immobilizzazioni non coperte da fonti a lungo termine"},
    ],
}


def _genera_alert(indici: dict, anni: list[str]) -> list[dict]:
    """Genera alert basati sulle soglie."""
    alert = []
    # Usa l'anno più recente per gli alert
    anno_recente = anni[-1]

    for cat, indici_cat in indici.items():
        for nome, valori in indici_cat.items():
            valore = valori.get(anno_recente)
            if valore is None:
                continue

            soglie_indice = SOGLIE.get(nome, [])
            for s in soglie_indice:
                triggered = False
                if s["condizione"] == "max" and valore > s["soglia"]:
                    triggered = True
                elif s["condizione"] == "min" and valore < s["soglia"]:
                    triggered = True

                if triggered:
                    alert.append({
                        "tipo": s["tipo"],
                        "indice": nome,
                        "valore": round(valore, 4),
                        "soglia": s["soglia"],
                        "anno": anno_recente,
                        "messaggio": s["msg"],
                    })
                    # Solo l'alert più severo per indice
                    break

    return alert


# ---------------------------------------------------------------------------
# Narrative
# ---------------------------------------------------------------------------

def _fmt_pct(val: Optional[float]) -> str:
    """Formatta un valore come percentuale italiana."""
    if val is None:
        return "n/d"
    return f"{val * 100:.1f}%".replace(".", ",")


def _fmt_num(val: Optional[float]) -> str:
    """Formatta un numero intero con separatore migliaia italiano."""
    if val is None:
        return "n/d"
    v = int(val)
    neg = v < 0
    v = abs(v)
    s = f"{v:,}".replace(",", ".")
    return f"({s})" if neg else s


def _fmt_ratio(val: Optional[float], dec: int = 2) -> str:
    """Formatta un ratio con virgola decimale."""
    if val is None:
        return "n/d"
    return f"{val:.{dec}f}".replace(".", ",")


def _genera_narrative_template(indici: dict, trend: list, alert: list,
                                anni: list[str], valori_per_anno: dict,
                                azienda: str) -> dict:
    """Genera narrative template dai dati, senza API call."""
    anno_recente = anni[-1]
    anno_prec = anni[-2] if len(anni) > 1 else None
    v_rec = valori_per_anno[anno_recente]
    idx_rec = {}
    for cat in indici:
        for nome, vals in indici[cat].items():
            idx_rec[nome] = vals.get(anno_recente)

    # --- Sintesi ---
    pfn_status = "positiva (liquidita netta)" if v_rec["pfn"] < 0 else "negativa (indebitamento netto)"
    sintesi = (
        f"{azienda} presenta nel {anno_recente} ricavi netti per {_fmt_num(v_rec['ricavi_netti'])} euro, "
        f"con un EBITDA di {_fmt_num(v_rec['ebitda'])} euro (margine {_fmt_pct(idx_rec.get('EBITDA_margin'))}). "
        f"L'utile netto si attesta a {_fmt_num(v_rec['utile_netto'])} euro, con un ROE del {_fmt_pct(idx_rec.get('ROE'))}. "
        f"La posizione finanziaria netta e {pfn_status} per {_fmt_num(abs(v_rec['pfn']))} euro."
    )

    if anno_prec:
        v_prec = valori_per_anno[anno_prec]
        var_ricavi = variazione_yoy(v_rec["ricavi_netti"], v_prec["ricavi_netti"])
        var_str = f"in crescita del {_fmt_pct(var_ricavi)}" if var_ricavi and var_ricavi > 0 else f"in calo del {_fmt_pct(abs(var_ricavi) if var_ricavi else 0)}"
        sintesi += f" I ricavi sono {var_str} rispetto al {anno_prec}."

    # --- Redditivita ---
    redditivita_parts = [
        f"Nel {anno_recente}, {azienda} registra un ROS del {_fmt_pct(idx_rec.get('ROS'))}, "
        f"un ROI del {_fmt_pct(idx_rec.get('ROI'))} e un ROA del {_fmt_pct(idx_rec.get('ROA'))}. "
        f"L'EBITDA margin si attesta al {_fmt_pct(idx_rec.get('EBITDA_margin'))}."
    ]
    if anno_prec:
        idx_prec = {}
        for cat in indici:
            for nome, vals in indici[cat].items():
                idx_prec[nome] = vals.get(anno_prec)
        ros_var = (idx_rec.get("ROS") or 0) - (idx_prec.get("ROS") or 0)
        dir_ros = "miglioramento" if ros_var > 0 else "peggioramento"
        redditivita_parts.append(
            f"Rispetto al {anno_prec}, il ROS mostra un {dir_ros} di {_fmt_pct(abs(ros_var))} punti percentuali. "
            f"Il ROE passa dal {_fmt_pct(idx_prec.get('ROE'))} al {_fmt_pct(idx_rec.get('ROE'))}."
        )
    redditivita = " ".join(redditivita_parts)

    # --- Struttura finanziaria ---
    struttura_parts = [
        f"L'indice di indipendenza finanziaria si attesta a {_fmt_ratio(idx_rec.get('indice_indipendenza_finanziaria'))}, "
    ]
    indip = idx_rec.get("indice_indipendenza_finanziaria")
    if indip is not None:
        if indip > 0.33:
            struttura_parts.append("indicando una buona patrimonializzazione. ")
        elif indip > 0.20:
            struttura_parts.append("in zona di attenzione. ")
        else:
            struttura_parts.append("a livelli critici. ")

    pfn_ebitda_val = idx_rec.get("pfn_ebitda")
    if pfn_ebitda_val is not None:
        if pfn_ebitda_val < 0:
            struttura_parts.append(
                f"Il rapporto PFN/EBITDA e negativo ({_fmt_ratio(pfn_ebitda_val)}x), "
                f"indicando una posizione di cassa netta positiva (l'azienda non ha debito finanziario netto). "
            )
        elif pfn_ebitda_val < 3:
            struttura_parts.append(
                f"Il rapporto PFN/EBITDA di {_fmt_ratio(pfn_ebitda_val)}x indica un indebitamento sostenibile. "
            )
        else:
            struttura_parts.append(
                f"Il rapporto PFN/EBITDA di {_fmt_ratio(pfn_ebitda_val)}x richiede attenzione. "
            )

    cop = idx_rec.get("copertura_immobilizzazioni")
    if cop is not None:
        struttura_parts.append(
            f"La copertura delle immobilizzazioni con fonti a lungo termine e pari a {_fmt_ratio(cop)}x"
            + (" (adeguata)." if cop >= 1 else " (insufficiente).")
        )

    struttura_finanziaria = "".join(struttura_parts)

    # --- Liquidita ---
    liquidita_parts = [
        f"Il current ratio si attesta a {_fmt_ratio(idx_rec.get('current_ratio'))} "
    ]
    cr = idx_rec.get("current_ratio")
    if cr is not None:
        if cr >= 1.5:
            liquidita_parts.append("(buono). ")
        elif cr >= 1.0:
            liquidita_parts.append("(sufficiente). ")
        else:
            liquidita_parts.append("(critico). ")

    liquidita_parts.append(
        f"Il quick ratio e {_fmt_ratio(idx_rec.get('quick_ratio'))}. "
        f"I tempi medi di incasso sono di {_fmt_ratio(idx_rec.get('giorni_crediti'), 0)} giorni, "
        f"mentre i tempi di pagamento ai fornitori sono di {_fmt_ratio(idx_rec.get('giorni_debiti'), 0)} giorni. "
        f"Il ciclo di magazzino e di {_fmt_ratio(idx_rec.get('giorni_magazzino'), 0)} giorni. "
    )

    ciclo = idx_rec.get("ciclo_cassa")
    if ciclo is not None:
        liquidita_parts.append(
            f"Il ciclo di cassa complessivo e di {_fmt_ratio(ciclo, 0)} giorni"
            + (" (negativo, favorevole)." if ciclo < 0 else ".")
        )

    liquidita_text = "".join(liquidita_parts)

    # --- Conclusioni ---
    punti_forza = []
    aree_attenzione = []

    if indip is not None and indip > 0.33:
        punti_forza.append("buona patrimonializzazione")
    if pfn_ebitda_val is not None and pfn_ebitda_val < 0:
        punti_forza.append("posizione di cassa netta positiva")
    if cr is not None and cr >= 1.5:
        punti_forza.append("liquidita adeguata")
    if idx_rec.get("ROS") and idx_rec["ROS"] > 0.05:
        punti_forza.append(f"marginalita operativa solida (ROS {_fmt_pct(idx_rec['ROS'])})")

    for a in alert:
        aree_attenzione.append(a["messaggio"])

    conclusioni_parts = [f"In sintesi, {azienda} presenta "]
    if punti_forza:
        conclusioni_parts.append("i seguenti punti di forza: " + ", ".join(punti_forza) + ". ")
    if aree_attenzione:
        conclusioni_parts.append("Le aree di attenzione includono: " + "; ".join(aree_attenzione) + ". ")
    if not aree_attenzione:
        conclusioni_parts.append("Non si rilevano criticita significative nell'esercizio analizzato. ")

    conclusioni = "".join(conclusioni_parts)

    return {
        "sintesi": sintesi,
        "redditivita": redditivita,
        "struttura_finanziaria": struttura_finanziaria,
        "liquidita": liquidita_text,
        "conclusioni": conclusioni,
    }


def _genera_narrative_llm(indici: dict, trend: list, alert: list,
                           anni: list[str], valori_per_anno: dict,
                           azienda: str) -> dict | None:
    """Genera narrative usando Claude con chiamata diretta (no agent loop)."""
    import anthropic

    client = anthropic.Anthropic()

    dati = json.dumps({
        "azienda": azienda,
        "anni": anni,
        "indici": indici,
        "trend": trend,
        "alert": alert,
        "valori_chiave": {
            anno: {
                "ricavi_netti": valori_per_anno[anno]["ricavi_netti"],
                "ebitda": valori_per_anno[anno]["ebitda"],
                "ebit": valori_per_anno[anno]["ebit"],
                "utile_netto": valori_per_anno[anno]["utile_netto"],
                "patrimonio_netto": valori_per_anno[anno]["patrimonio_netto"],
                "pfn": valori_per_anno[anno]["pfn"],
                "liquidita": valori_per_anno[anno]["liquidita"],
            }
            for anno in anni
        },
    }, ensure_ascii=False, indent=2)

    system = (
        "Sei un analista finanziario specializzato in PMI italiane. "
        "Genera commenti analitici in italiano per un report di bilancio. "
        "Rispondi ESCLUSIVAMENTE con un JSON valido (nessun testo prima o dopo) "
        "con queste 5 chiavi, ciascuna contenente un paragrafo di 4-8 righe:\n"
        '- "sintesi": overview dell\'azienda, ricavi, margini, utile, posizione finanziaria\n'
        '- "redditivita": andamento ROE, ROI, ROS, EBITDA margin, leve principali\n'
        '- "struttura_finanziaria": equilibrio fonti/impieghi, PFN, copertura immobilizzazioni\n'
        '- "liquidita": current/quick ratio, ciclo commerciale, giorni crediti/debiti/magazzino\n'
        '- "conclusioni": punti di forza, aree di attenzione, outlook\n\n'
        "Regole:\n"
        "- Cita sempre i numeri specifici (valori in euro, percentuali, multipli)\n"
        "- Spiega il 'perché' quando possibile, non solo il 'cosa'\n"
        "- Se un indice è fuori soglia, contestualizza\n"
        "- Usa un tono professionale da relazione finanziaria\n"
        "- NON usare markdown, solo testo piano"
    )

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": dati}],
    )

    text = response.content[0].text.strip()

    # Estrai JSON dalla risposta
    # Potrebbe essere JSON puro o wrapped in ```json ... ```
    if text.startswith("```"):
        lines = text.split("\n")
        json_lines = [l for l in lines if not l.startswith("```")]
        text = "\n".join(json_lines)

    result = json.loads(text)

    sezioni_attese = ["sintesi", "redditivita", "struttura_finanziaria", "liquidita", "conclusioni"]
    if isinstance(result, dict) and all(k in result for k in sezioni_attese):
        return {k: result[k] for k in sezioni_attese}

    return None


def _genera_narrative(indici: dict, trend: list, alert: list,
                       anni: list[str], valori_per_anno: dict,
                       azienda: str) -> dict:
    """Genera narrative, con fallback se API key non disponibile."""
    # Prova con LLM se API key presente
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key:
        try:
            result = _genera_narrative_llm(indici, trend, alert, anni, valori_per_anno, azienda)
            if result is not None:
                return result
            print("[analista] LLM narrative fallback: formato risposta non valido, uso template.")
        except Exception as e:
            print(f"[analista] LLM narrative fallback: {e}")

    # Fallback: template deterministico
    return _genera_narrative_template(indici, trend, alert, anni, valori_per_anno, azienda)


# ---------------------------------------------------------------------------
# Funzione principale
# ---------------------------------------------------------------------------

def esegui_analisi(pipeline_result: dict) -> dict:
    """Esegue l'analisi completa su un pipeline_result.

    Args:
        pipeline_result: Output della pipeline di riclassifica.

    Returns:
        Dict con la struttura completa dell'analisi come da skill_analisi.md.
    """
    azienda = pipeline_result.get("azienda", "Azienda")
    risultati = pipeline_result["riclassifica"]["risultati_per_anno"]

    # 1. Calcola tutti gli indici
    indici, anni, valori_per_anno = _calcola_tutti_indici(risultati)

    # 2. Calcola trend
    trend = _calcola_trend(indici, anni)

    # 3. Calcola variazioni YoY
    variazioni_yoy = _calcola_variazioni_yoy(indici, anni)

    # 4. Genera alert
    alert = _genera_alert(indici, anni)

    # 5. Genera narrative
    narrative = _genera_narrative(indici, trend, alert, anni, valori_per_anno, azienda)

    # 6. Calcola CAGR ricavi ed EBITDA se possibile
    cagr_info = {}
    if len(anni) >= 2:
        n_anni = len(anni) - 1
        ricavi_primo = valori_per_anno[anni[0]]["ricavi_netti"]
        ricavi_ultimo = valori_per_anno[anni[-1]]["ricavi_netti"]
        cagr_ricavi = cagr(ricavi_primo, ricavi_ultimo, n_anni)
        cagr_info["ricavi"] = round(cagr_ricavi, 4) if cagr_ricavi is not None else None

        ebitda_primo = valori_per_anno[anni[0]]["ebitda"]
        ebitda_ultimo = valori_per_anno[anni[-1]]["ebitda"]
        cagr_ebitda = cagr(ebitda_primo, ebitda_ultimo, n_anni)
        cagr_info["ebitda"] = round(cagr_ebitda, 4) if cagr_ebitda is not None else None

    return {
        "azienda": azienda,
        "anni": [int(a) for a in anni],
        "indici": indici,
        "variazioni_yoy": variazioni_yoy,
        "cagr": cagr_info,
        "trend": trend,
        "alert": alert,
        "narrative": narrative,
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python -m agents.analista <pipeline_result_json_path>")
        sys.exit(1)

    data_path = Path(sys.argv[1])
    if not data_path.exists():
        print(f"[ERRORE] File non trovato: {data_path}")
        sys.exit(1)

    print(f"Caricamento dati da: {data_path}")
    pipeline_result = json.loads(data_path.read_text(encoding="utf-8"))

    print(f"Azienda: {pipeline_result['azienda']}")
    print(f"Anni disponibili: {sorted(pipeline_result['riclassifica']['risultati_per_anno'].keys())}")

    analisi = esegui_analisi(pipeline_result)

    # Salva output
    azienda_nome = pipeline_result.get("azienda", "output")
    nome_file = azienda_nome.lower().replace(" ", "_").replace(".", "")
    output_path = ROOT / "data" / "output" / f"{nome_file}_analisi.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(analisi, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nAnalisi salvata in: {output_path}")

    # Stampa riepilogo
    print(f"\n{'='*60}")
    print(f"ANALISI {analisi['azienda']}")
    print(f"{'='*60}")
    print(f"Anni: {analisi['anni']}")

    print(f"\n--- INDICI (anno {analisi['anni'][-1]}) ---")
    anno_str = str(analisi['anni'][-1])
    for cat, indici_cat in analisi["indici"].items():
        print(f"\n  {cat.upper()}:")
        for nome, valori in indici_cat.items():
            val = valori.get(anno_str)
            if val is not None:
                if "giorni" in nome or "ciclo" in nome:
                    print(f"    {nome}: {val:.1f} gg")
                elif nome in ("current_ratio", "quick_ratio", "copertura_immobilizzazioni",
                              "pfn_ebitda", "pfn_pn", "rapporto_indebitamento"):
                    print(f"    {nome}: {val:.2f}x")
                else:
                    print(f"    {nome}: {val*100:.1f}%")
            else:
                print(f"    {nome}: n/d")

    if analisi["cagr"]:
        print(f"\n--- CAGR ---")
        for k, v in analisi["cagr"].items():
            print(f"  {k}: {v*100:.1f}%" if v is not None else f"  {k}: n/d")

    print(f"\n--- TREND ---")
    for t in analisi["trend"]:
        if t["significativo"]:
            print(f"  {t['indice']}: {t['direzione']} ({_fmt_pct(t.get('variazione_percentuale'))})")

    print(f"\n--- ALERT ({len(analisi['alert'])}) ---")
    for a in analisi["alert"]:
        print(f"  [{a['tipo'].upper()}] {a['messaggio']}")

    print(f"\n--- NARRATIVE ---")
    for sezione, testo in analisi["narrative"].items():
        print(f"\n  [{sezione.upper()}]")
        # Stampa prime 200 chars
        print(f"  {testo[:200]}...")
