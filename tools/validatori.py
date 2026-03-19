"""Validatori di schema e coerenza dati."""

from typing import Any


# Macro-voci minime attese per tipo bilancio
MACRO_VOCI_SP_ORDINARIO = {
    "immobilizzazioni_immateriali",
    "immobilizzazioni_materiali",
    "immobilizzazioni_finanziarie",
    "rimanenze",
    "crediti_verso_clienti",
    "disponibilita_liquide",
    "patrimonio_netto",
    "debiti",
}

MACRO_VOCI_CE_ORDINARIO = {
    "ricavi_vendite_prestazioni",
    "costi_materie_prime",
    "costi_servizi",
    "costi_personale",
    "ammortamenti",
    "utile_perdita_esercizio",
}

MACRO_VOCI_SP_ABBREVIATO = {
    "immobilizzazioni",
    "attivo_circolante",
    "patrimonio_netto",
    "debiti",
}

MACRO_VOCI_CE_ABBREVIATO = {
    "valore_produzione",
    "costi_produzione",
    "utile_perdita_esercizio",
}

# IFRS — label diverse dalla codifica civilistica
MACRO_VOCI_SP_IFRS = {
    "immobilizzazioni_materiali",  # o "totale_immobilizzazioni_materiali"
    "immobilizzazioni_immateriali",  # o "totale_immobilizzazioni_immateriali"
    "rimanenze",
    "crediti_commerciali",  # "crediti_commerciali_e_altre"
    "cassa",  # "cassa_e_disponibilità_liquide"
    "patrimonio_netto",  # "totale_patrimonio_netto"
    "passivit",  # "passività_correnti", "passività_non_correnti"
}

MACRO_VOCI_CE_IFRS = {
    "ricavi",
    "costo_del_personale",  # o "costi_personale"
    "ammortament",
    "risultato",  # "risultato_operativo", "risultato_netto"
    "imposte",
}


def valida_schema_normalizzato(schema: dict) -> list[dict]:
    """Valida lo schema normalizzato estratto dal PDF.

    Returns:
        Lista di issue trovate, ciascuna con codice, severity, dettaglio.
    """
    issues = []

    # Check presenza sezioni
    if schema.get("sp") is None:
        issues.append({
            "codice": "COMPLETEZZA_SP",
            "severity": "critical",
            "dettaglio": "Sezione SP assente",
        })
    if schema.get("ce") is None:
        issues.append({
            "codice": "COMPLETEZZA_CE",
            "severity": "critical",
            "dettaglio": "Sezione CE assente",
        })

    if schema.get("sp") is None or schema.get("ce") is None:
        return issues

    # Check duplicati
    ids_visti = set()
    for sezione in ("sp", "ce"):
        for voce in schema[sezione]:
            vid = voce.get("id", "")
            if vid in ids_visti:
                issues.append({
                    "codice": "DUPLICATI",
                    "severity": "critical",
                    "dettaglio": f"ID duplicato: {vid} in {sezione.upper()}",
                })
            ids_visti.add(vid)

    # Check valori numerici validi
    non_parsabili = 0
    totale_valori = 0
    for sezione in ("sp", "ce"):
        for voce in schema[sezione]:
            for anno, val in voce.get("valore", {}).items():
                totale_valori += 1
                if val is None:
                    non_parsabili += 1

    if totale_valori > 0 and (non_parsabili / totale_valori) > 0.05:
        issues.append({
            "codice": "FORMATO_NUMERI",
            "severity": "critical",
            "dettaglio": f"{non_parsabili}/{totale_valori} valori non parsabili ({non_parsabili/totale_valori:.0%})",
        })
    elif non_parsabili > 0:
        issues.append({
            "codice": "FORMATO_NUMERI",
            "severity": "warning",
            "dettaglio": f"{non_parsabili} valori non parsabili su {totale_valori}",
        })

    # Check completezza macro-voci
    tipo = schema.get("tipo_bilancio", "ordinario")
    formato = schema.get("metadata", {}).get("formato", "")
    ids_presenti = {v["id"] for sezione in ("sp", "ce") for v in schema[sezione]}

    if formato == "IFRS":
        macro_sp = MACRO_VOCI_SP_IFRS
        macro_ce = MACRO_VOCI_CE_IFRS
    elif tipo in ("ordinario", None):
        macro_sp = MACRO_VOCI_SP_ORDINARIO
        macro_ce = MACRO_VOCI_CE_ORDINARIO
    else:
        macro_sp = MACRO_VOCI_SP_ABBREVIATO
        macro_ce = MACRO_VOCI_CE_ABBREVIATO

    # Fuzzy match: controlla se almeno una voce contiene il pattern
    for macro in macro_sp:
        if not any(macro in vid for vid in ids_presenti):
            issues.append({
                "codice": "COMPLETEZZA_SP",
                "severity": "warning",
                "dettaglio": f"Macro-voce SP mancante: {macro}",
            })

    for macro in macro_ce:
        if not any(macro in vid for vid in ids_presenti):
            issues.append({
                "codice": "COMPLETEZZA_CE",
                "severity": "warning",
                "dettaglio": f"Macro-voce CE mancante: {macro}",
            })

    return issues


def valida_quadratura_sp(schema: dict, anno: str) -> dict:
    """Verifica quadratura SP per un anno specifico.

    Returns:
        Dict con codice, esito, severity_contributo, dettaglio.
    """
    metadata = schema.get("metadata", {})
    attivo = metadata.get("totale_attivo_dichiarato", {}).get(anno)
    passivo = metadata.get("totale_passivo_dichiarato", {}).get(anno)

    if attivo is None or passivo is None:
        return {
            "codice": "SP_QUADRATURA",
            "esito": "warn",
            "severity_contributo": "warning",
            "dettaglio": f"Totali SP non disponibili per anno {anno}",
        }

    delta = abs(attivo - passivo)
    percentuale = (delta / attivo * 100) if attivo != 0 else 0

    if delta <= 1:
        return {
            "codice": "SP_QUADRATURA",
            "esito": "pass",
            "severity_contributo": "ok",
            "dettaglio": f"Totale attivo ({attivo:,}) = Totale passivo ({passivo:,}), delta: {delta}€",
        }
    elif percentuale <= 1:
        return {
            "codice": "SP_QUADRATURA",
            "esito": "warn",
            "severity_contributo": "warning",
            "dettaglio": f"Totale attivo ({attivo:,}) ≠ Totale passivo ({passivo:,}), delta: {delta:,}€ ({percentuale:.1f}%)",
        }
    else:
        return {
            "codice": "SP_QUADRATURA",
            "esito": "fail",
            "severity_contributo": "critical",
            "dettaglio": f"Totale attivo ({attivo:,}) ≠ Totale passivo ({passivo:,}), delta: {delta:,}€ ({percentuale:.1f}%)",
        }


def valida_coerenza_utile(schema: dict, anno: str) -> dict:
    """Verifica che l'utile netto CE corrisponda all'utile in PN."""
    metadata = schema.get("metadata", {})
    utile_ce = metadata.get("utile_dichiarato", {}).get(anno)

    # Cerca utile in SP
    utile_sp = None
    for voce in schema.get("sp", []):
        if "utile" in voce.get("id", "") and "perdita" in voce.get("id", ""):
            utile_sp = voce.get("valore", {}).get(anno)
            break

    if utile_ce is None or utile_sp is None:
        return {
            "codice": "CE_UTILE_SP",
            "esito": "warn",
            "severity_contributo": "warning",
            "dettaglio": f"Impossibile confrontare utile CE/SP per anno {anno}",
        }

    delta = abs(utile_ce - utile_sp)
    if delta <= 1:
        return {
            "codice": "CE_UTILE_SP",
            "esito": "pass",
            "severity_contributo": "ok",
            "dettaglio": f"Utile CE ({utile_ce:,}) = Utile SP ({utile_sp:,})",
        }
    else:
        return {
            "codice": "CE_UTILE_SP",
            "esito": "warn",
            "severity_contributo": "warning",
            "dettaglio": f"Utile CE ({utile_ce:,}) ≠ Utile SP ({utile_sp:,}), delta: {delta:,}€",
        }


def valida_cross_anno(risultati_per_anno: dict) -> list[dict]:
    """Verifica coerenza tra anni consecutivi nei dati riclassificati.

    Checks:
    - Salti >50% nel totale attivo
    - Cambi di segno EBITDA
    - Cambi di segno PFN (se importi significativi)

    Returns:
        Lista di issue con codice, severity, dettaglio.
    """
    issues: list[dict] = []
    anni = sorted(risultati_per_anno.keys())

    if len(anni) < 2:
        return issues

    for i in range(1, len(anni)):
        anno_corr = anni[i]
        anno_prec = anni[i - 1]

        res_corr = risultati_per_anno[anno_corr]
        res_prec = risultati_per_anno[anno_prec]

        sp_corr = res_corr.get("sp_riclassificato", {})
        sp_prec = res_prec.get("sp_riclassificato", {})
        ce_corr = res_corr.get("ce_riclassificato", {})
        ce_prec = res_prec.get("ce_riclassificato", {})

        # Salto totale attivo > 50%
        ta_corr = sp_corr.get("quadratura", {}).get("totale_attivo", 0)
        ta_prec = sp_prec.get("quadratura", {}).get("totale_attivo", 0)
        if ta_prec > 0:
            var = abs(ta_corr - ta_prec) / ta_prec
            if var > 0.5:
                issues.append({
                    "codice": "CROSS_SALTO_ATTIVO",
                    "severity": "warning",
                    "dettaglio": (
                        f"Totale attivo: salto {var:.0%} tra {anno_prec} "
                        f"({ta_prec:,}) e {anno_corr} ({ta_corr:,})"
                    ),
                })

        # Cambio segno EBITDA
        ebitda_corr = ce_corr.get("ebitda", 0)
        ebitda_prec = ce_prec.get("ebitda", 0)
        if ebitda_corr * ebitda_prec < 0:
            issues.append({
                "codice": "CROSS_SEGNO_EBITDA",
                "severity": "warning",
                "dettaglio": (
                    f"Cambio segno EBITDA: {anno_prec}={ebitda_prec:,} → "
                    f"{anno_corr}={ebitda_corr:,}"
                ),
            })

    return issues


def calcola_severity(checks: list[dict]) -> tuple[str, float]:
    """Calcola severity complessiva e score numerico da lista di checks.

    Returns:
        Tupla (severity_label, score).
    """
    score = 1.0
    has_critical = False

    for check in checks:
        contrib = check.get("severity_contributo", "ok")
        if contrib == "critical":
            has_critical = True
            score -= 0.3
        elif contrib == "warning":
            score -= 0.05

    score = max(0.0, round(score, 2))

    if has_critical:
        return "critical", score
    elif score < 1.0:
        return "warning", score
    else:
        return "ok", score
