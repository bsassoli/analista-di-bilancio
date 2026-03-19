"""Calcolatori deterministici per indici di bilancio e aggregati."""

from typing import Optional


# --- Aggregati SP ---

def calcola_subtotale(voci: list[dict], ids: list[str], anno: str) -> int:
    """Somma i valori di un subset di voci per un dato anno.

    Args:
        voci: Lista di voci bilancio (schema normalizzato).
        ids: Lista di ID voci da sommare.
        anno: Anno di riferimento (es. "2023").

    Returns:
        Somma dei valori.
    """
    totale = 0
    for voce in voci:
        if voce["id"] in ids:
            totale += voce.get("valore", {}).get(anno, 0)
    return totale


def calcola_ccon(
    crediti_commerciali: int,
    rimanenze: int,
    altri_crediti_operativi: int,
    debiti_operativi: int,
) -> int:
    """Calcola il Capitale Circolante Operativo Netto."""
    return crediti_commerciali + rimanenze + altri_crediti_operativi - debiti_operativi


def calcola_pfn(
    debiti_fin_lungo: int,
    debiti_fin_breve: int,
    disponibilita_liquide: int,
) -> int:
    """Calcola la Posizione Finanziaria Netta.

    Convenzione: PFN positiva = indebitamento netto.
    """
    return debiti_fin_lungo + debiti_fin_breve - disponibilita_liquide


def verifica_quadratura(
    totale_attivo: int, totale_passivo: int, tolleranza: int = 1
) -> dict:
    """Verifica quadratura dello Stato Patrimoniale.

    Returns:
        Dict con delta, ok (bool), percentuale.
    """
    delta = abs(totale_attivo - totale_passivo)
    percentuale = (delta / totale_attivo * 100) if totale_attivo != 0 else 0
    return {
        "totale_attivo": totale_attivo,
        "totale_passivo": totale_passivo,
        "delta": delta,
        "percentuale": round(percentuale, 4),
        "ok": delta <= tolleranza,
    }


# --- Indici di bilancio ---

def _safe_div(numeratore: float, denominatore: float) -> Optional[float]:
    """Divisione sicura: restituisce None se denominatore è 0."""
    if denominatore == 0:
        return None
    return numeratore / denominatore


def roe(utile_netto: float, patrimonio_netto_medio: float) -> Optional[float]:
    """ROE = Utile netto / Patrimonio netto medio."""
    return _safe_div(utile_netto, patrimonio_netto_medio)


def roi(ebit: float, capitale_investito_netto: float) -> Optional[float]:
    """ROI = EBIT / Capitale investito netto."""
    return _safe_div(ebit, capitale_investito_netto)


def ros(ebit: float, ricavi_netti: float) -> Optional[float]:
    """ROS = EBIT / Ricavi netti."""
    return _safe_div(ebit, ricavi_netti)


def roa(ebit: float, totale_attivo: float) -> Optional[float]:
    """ROA = EBIT / Totale attivo."""
    return _safe_div(ebit, totale_attivo)


def ebitda_margin(ebitda: float, ricavi_netti: float) -> Optional[float]:
    """EBITDA margin = EBITDA / Ricavi netti."""
    return _safe_div(ebitda, ricavi_netti)


def indice_indipendenza_finanziaria(
    patrimonio_netto: float, totale_passivo: float
) -> Optional[float]:
    """PN / Totale passivo."""
    return _safe_div(patrimonio_netto, totale_passivo)


def rapporto_indebitamento(
    pfn: float, debiti_operativi: float, patrimonio_netto: float
) -> Optional[float]:
    """(PFN + Debiti operativi) / PN."""
    return _safe_div(pfn + debiti_operativi, patrimonio_netto)


def copertura_immobilizzazioni(
    patrimonio_netto: float, debiti_fin_lungo: float, capitale_fisso_netto: float
) -> Optional[float]:
    """(PN + Debiti fin. lungo) / CFN."""
    return _safe_div(patrimonio_netto + debiti_fin_lungo, capitale_fisso_netto)


def pfn_su_ebitda(pfn: float, ebitda: float) -> Optional[float]:
    """PFN / EBITDA."""
    return _safe_div(pfn, ebitda)


def pfn_su_pn(pfn: float, patrimonio_netto: float) -> Optional[float]:
    """PFN / PN."""
    return _safe_div(pfn, patrimonio_netto)


def current_ratio(
    crediti_comm: float,
    rimanenze: float,
    liquidita: float,
    debiti_breve: float,
) -> Optional[float]:
    """(Crediti comm. + Rimanenze + Liquidità) / Debiti breve."""
    return _safe_div(crediti_comm + rimanenze + liquidita, debiti_breve)


def quick_ratio(
    crediti_comm: float, liquidita: float, debiti_breve: float
) -> Optional[float]:
    """(Crediti comm. + Liquidità) / Debiti breve."""
    return _safe_div(crediti_comm + liquidita, debiti_breve)


def giorni_crediti(crediti_comm: float, ricavi: float) -> Optional[float]:
    """(Crediti comm. / Ricavi) × 365."""
    r = _safe_div(crediti_comm, ricavi)
    return round(r * 365, 1) if r is not None else None


def giorni_debiti(debiti_fornitori: float, acquisti: float) -> Optional[float]:
    """(Debiti fornitori / Acquisti) × 365."""
    r = _safe_div(debiti_fornitori, acquisti)
    return round(r * 365, 1) if r is not None else None


def giorni_magazzino(rimanenze: float, costo_venduto: float) -> Optional[float]:
    """(Rimanenze / Costo venduto) × 365."""
    r = _safe_div(rimanenze, costo_venduto)
    return round(r * 365, 1) if r is not None else None


def ciclo_cassa(
    gg_crediti: Optional[float],
    gg_magazzino: Optional[float],
    gg_debiti: Optional[float],
) -> Optional[float]:
    """GG crediti + GG magazzino - GG debiti."""
    if any(v is None for v in (gg_crediti, gg_magazzino, gg_debiti)):
        return None
    return round(gg_crediti + gg_magazzino - gg_debiti, 1)


# --- Trend ---

def variazione_yoy(valore_n: float, valore_n1: float) -> Optional[float]:
    """Calcola variazione percentuale Year-over-Year.

    Returns:
        Variazione come decimale (es. 0.15 = +15%) o None se base = 0.
    """
    if valore_n1 == 0:
        return None
    return (valore_n - valore_n1) / abs(valore_n1)


def cagr(valore_iniziale: float, valore_finale: float, anni: int) -> Optional[float]:
    """Calcola il CAGR (Compound Annual Growth Rate).

    Returns:
        CAGR come decimale o None se non calcolabile.
    """
    if anni <= 0 or valore_iniziale <= 0 or valore_finale <= 0:
        return None
    return (valore_finale / valore_iniziale) ** (1 / anni) - 1
