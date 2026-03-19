"""Agente produttore: genera Excel e Word dai risultati dell'analisi."""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# Aggiungi root al path per import
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.writer import (
    scrivi_excel,
    scrivi_word,
    crea_tabella_serie_storica,
    formatta_numero_it,
    formatta_percentuale,
    formatta_indice,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nome_file_base(azienda: str) -> str:
    """Genera un nome file base sanitizzato dal nome azienda."""
    return azienda.lower().replace(" ", "_").replace(".", "").replace(",", "")


def _fmt_val(val: Optional[float], tipo: str = "numero") -> str:
    """Formatta un valore in base al tipo indicato."""
    if val is None:
        return "n/d"
    if tipo == "numero":
        return formatta_numero_it(val)
    elif tipo == "percentuale":
        return formatta_percentuale(val)
    elif tipo == "indice":
        return formatta_indice(val)
    elif tipo == "giorni":
        return f"{val:.1f}".replace(".", ",")
    elif tipo == "ratio":
        return f"{val:.2f}".replace(".", ",") + "x"
    return str(val)


def _get_anni(pipeline_result: dict) -> list[str]:
    """Estrae la lista degli anni ordinati dal pipeline result."""
    return sorted(pipeline_result["riclassifica"]["risultati_per_anno"].keys())


# ---------------------------------------------------------------------------
# Foglio SP Riclassificato
# ---------------------------------------------------------------------------

# Definizione struttura gerarchica SP.
# Ogni tupla: (label, sezione_key, voce_key, is_totale)
# sezione_key=None e voce_key=None => riga vuota o header puro.
_VOCI_SP_ATTIVO = [
    ("CAPITALE FISSO NETTO", "capitale_fisso_netto", "totale", True),
    ("  Immobilizzazioni materiali nette", "capitale_fisso_netto", "immobilizzazioni_materiali_nette", False),
    ("  Immobilizzazioni immateriali nette", "capitale_fisso_netto", "immobilizzazioni_immateriali_nette", False),
    ("  Immobilizzazioni finanziarie", "capitale_fisso_netto", "immobilizzazioni_finanziarie", False),
    ("", None, None, False),
    ("CCON (Capitale Circolante Operativo Netto)", "ccon", "totale", True),
    ("  Crediti commerciali", "ccon", "crediti_commerciali", False),
    ("  Rimanenze", "ccon", "rimanenze", False),
    ("  Altri crediti operativi", "ccon", "altri_crediti_operativi", False),
    ("  (Debiti operativi)", "ccon", "debiti_operativi_sottratti", False),
    ("", None, None, False),
    ("ALTRE ATTIVITA NON OPERATIVE", "altre_attivita_non_operative", "totale", True),
]

_VOCI_SP_PASSIVO = [
    ("", None, None, False),
    ("FONTI", None, None, True),
    ("PATRIMONIO NETTO", "patrimonio_netto", "totale", True),
    ("  Capitale sociale", "patrimonio_netto", "capitale_sociale", False),
    ("  Riserve", "patrimonio_netto", "riserve", False),
    ("  Utile (perdita) d'esercizio", "patrimonio_netto", "utile_perdita_esercizio", False),
    ("", None, None, False),
    ("POSIZIONE FINANZIARIA NETTA", "pfn", "totale", True),
    ("  Debiti finanziari a lungo termine", "pfn", "debiti_finanziari_lungo", False),
    ("  Debiti finanziari a breve termine", "pfn", "debiti_finanziari_breve", False),
    ("  (Disponibilita liquide)", "pfn", "disponibilita_liquide_sottratte", False),
]

# Voci che vanno mostrate con segno negativo (sottratte)
_VOCI_NEGATIVE = {"debiti_operativi_sottratti", "disponibilita_liquide_sottratte"}


def _get_sp_val(sp: dict, sezione_key: str, voce_key: str) -> Optional[float]:
    """Estrae un valore dalla struttura SP riclassificato, cercando in attivo e passivo."""
    for lato in ("attivo", "passivo"):
        sezione = sp.get(lato, {}).get(sezione_key)
        if sezione is not None:
            if voce_key == "totale":
                return sezione.get("totale")
            return sezione.get("dettaglio", {}).get(voce_key)
    return None


def _prepara_foglio_sp(pipeline_result: dict, anni: list[str]) -> list[list[Any]]:
    """Prepara le righe per il foglio SP Riclassificato."""
    risultati = pipeline_result["riclassifica"]["risultati_per_anno"]
    righe: list[list[Any]] = [["Voce"] + anni]

    tutte_voci = _VOCI_SP_ATTIVO + _VOCI_SP_PASSIVO

    for label, sezione_key, voce_key, _is_totale in tutte_voci:
        # Riga vuota o header puro senza dati
        if sezione_key is None:
            righe.append([label] + [""] * len(anni))
            continue

        riga: list[Any] = [label]
        for anno in anni:
            sp = risultati[anno]["sp_riclassificato"]
            val = _get_sp_val(sp, sezione_key, voce_key)
            # Mostra come negativo le voci sottratte
            if voce_key in _VOCI_NEGATIVE and val is not None:
                val = -abs(val)
            riga.append(formatta_numero_it(val))
        righe.append(riga)

    # Riga vuota separatrice
    righe.append([""] * (1 + len(anni)))

    # Righe quadratura
    riga_tot_att: list[Any] = ["TOTALE ATTIVO"]
    riga_tot_pas: list[Any] = ["TOTALE PASSIVO"]
    for anno in anni:
        q = risultati[anno]["sp_riclassificato"]["quadratura"]
        riga_tot_att.append(formatta_numero_it(q["totale_attivo"]))
        riga_tot_pas.append(formatta_numero_it(q["totale_passivo"]))
    righe.append(riga_tot_att)
    righe.append(riga_tot_pas)

    return righe


# ---------------------------------------------------------------------------
# Foglio CE Riclassificato
# ---------------------------------------------------------------------------

# Tupla: (label, chiave_ce, is_aggregato)
_VOCI_CE = [
    ("Ricavi netti", "ricavi_netti", True),
    ("Costi materie prime e merci", "costi_materie_prime_merci", False),
    ("VALORE AGGIUNTO INDUSTRIALE", "valore_aggiunto_industriale", True),
    ("Costi servizi e godimento beni terzi", "costi_servizi_godimento", False),
    ("Costi del personale", "costi_personale", False),
    ("EBITDA", "ebitda", True),
    ("Ammortamenti e svalutazioni", "ammortamenti_svalutazioni", False),
    ("EBIT", "ebit", True),
    ("Proventi e oneri finanziari", "proventi_oneri_finanziari", False),
    ("EBT (Risultato ante imposte)", "ebt", True),
    ("Imposte", "imposte", False),
    ("UTILE NETTO", "utile_netto", True),
]


def _prepara_foglio_ce(pipeline_result: dict, anni: list[str]) -> list[list[Any]]:
    """Prepara le righe per il foglio CE Riclassificato, con colonne margine %."""
    risultati = pipeline_result["riclassifica"]["risultati_per_anno"]

    # Header: Voce | 2023 | % 2023 | 2024 | % 2024 | ...
    header: list[Any] = ["Voce"]
    for anno in anni:
        header.append(anno)
        header.append(f"% {anno}")
    righe: list[list[Any]] = [header]

    for label, chiave, _is_aggregato in _VOCI_CE:
        riga: list[Any] = [label]
        for anno in anni:
            ce = risultati[anno]["ce_riclassificato"]
            val = ce.get(chiave)
            riga.append(formatta_numero_it(val))
            # Margine percentuale su ricavi netti
            ricavi = ce.get("ricavi_netti", 0)
            if val is not None and ricavi and ricavi != 0:
                riga.append(formatta_percentuale(val / ricavi))
            else:
                riga.append("")
        righe.append(riga)

    return righe


# ---------------------------------------------------------------------------
# Foglio Indici
# ---------------------------------------------------------------------------

_INDICE_META: dict[str, tuple[str, str]] = {
    "ROE": ("percentuale", "Rendimento del capitale proprio"),
    "ROI": ("percentuale", "Rendimento del capitale investito"),
    "ROS": ("percentuale", "Marginalita operativa"),
    "ROA": ("percentuale", "Rendimento delle attivita"),
    "EBITDA_margin": ("percentuale", "Margine operativo lordo"),
    "indice_indipendenza_finanziaria": ("indice", "PN / Totale passivo (> 0,33 buono)"),
    "rapporto_indebitamento": ("ratio", "(PFN + Deb.op.) / PN (< 2 buono)"),
    "copertura_immobilizzazioni": ("ratio", "(PN + Deb.fin.lungo) / CFN (> 1 buono)"),
    "pfn_ebitda": ("ratio", "PFN / EBITDA (< 3 buono)"),
    "pfn_pn": ("ratio", "PFN / PN (< 1 buono)"),
    "current_ratio": ("ratio", "(Cred.+ Rim.+ Liq.) / Deb.breve (> 1,5 buono)"),
    "quick_ratio": ("ratio", "(Cred.+ Liq.) / Deb.breve (> 1 buono)"),
    "giorni_crediti": ("giorni", "Giorni medi di incasso"),
    "giorni_debiti": ("giorni", "Giorni medi di pagamento"),
    "giorni_magazzino": ("giorni", "Giorni di giacenza magazzino"),
    "ciclo_cassa": ("giorni", "GG crediti + GG magazzino - GG debiti"),
    "costo_personale_su_va": ("percentuale", "Costo personale / Valore aggiunto"),
    "incidenza_ammortamenti": ("percentuale", "Ammortamenti / Ricavi"),
    "fatturato_per_dipendente": ("numero", "Ricavi / N. dipendenti"),
}

_CATEGORIA_LABELS: dict[str, str] = {
    "redditivita": "REDDITIVITA",
    "struttura": "STRUTTURA FINANZIARIA",
    "liquidita": "LIQUIDITA E CICLO COMMERCIALE",
    "efficienza": "EFFICIENZA",
}


def _prepara_foglio_indici(analisi: dict, anni: list[str]) -> list[list[Any]]:
    """Prepara le righe per il foglio Indici, raggruppati per categoria."""
    anni_str = [str(a) for a in anni]
    righe: list[list[Any]] = [["Categoria", "Indice", "Descrizione"] + anni_str + ["Trend"]]

    indici_dict = analisi.get("indici", {})
    trend_list = analisi.get("trend", [])

    for cat_key, indici_cat in indici_dict.items():
        # Riga separatore categoria
        cat_label = _CATEGORIA_LABELS.get(cat_key, cat_key.upper())
        righe.append([cat_label] + [""] * (2 + len(anni_str) + 1))

        for nome, valori_per_anno in indici_cat.items():
            meta = _INDICE_META.get(nome, ("indice", ""))
            tipo_fmt, descr = meta

            riga: list[Any] = ["", nome, descr]
            for anno in anni_str:
                val = valori_per_anno.get(anno)
                riga.append(_fmt_val(val, tipo_fmt))

            # Freccia trend
            trend_entry = next((t for t in trend_list if t["indice"] == nome), None)
            if trend_entry:
                freccia = {
                    "crescente": "\u2191",
                    "decrescente": "\u2193",
                    "stabile": "\u2192",
                }.get(trend_entry["direzione"], "")
                riga.append(freccia)
            else:
                riga.append("")

            righe.append(riga)

    return righe


# ---------------------------------------------------------------------------
# Foglio Dati grezzi
# ---------------------------------------------------------------------------

def _prepara_foglio_dati_grezzi(pipeline_result: dict, anni: list[str]) -> list[list[Any]]:
    """Prepara dump dei dati grezzi (SP + CE) per trasparenza e audit."""
    risultati = pipeline_result["riclassifica"]["risultati_per_anno"]
    righe: list[list[Any]] = [["Sezione", "Voce"] + anni]

    # --- SP Attivo ---
    for sezione_nome in ("capitale_fisso_netto", "ccon", "altre_attivita_non_operative"):
        # Totale
        riga: list[Any] = [f"SP.attivo.{sezione_nome}", "TOTALE"]
        for anno in anni:
            sp = risultati[anno]["sp_riclassificato"]["attivo"].get(sezione_nome, {})
            riga.append(sp.get("totale", ""))
        righe.append(riga)

        # Dettaglio: usa il primo anno come riferimento per le chiavi
        primo_anno_sez = risultati[anni[0]]["sp_riclassificato"]["attivo"].get(sezione_nome, {})
        for chiave in primo_anno_sez.get("dettaglio", {}):
            riga = [f"SP.attivo.{sezione_nome}", chiave]
            for anno in anni:
                sp = risultati[anno]["sp_riclassificato"]["attivo"].get(sezione_nome, {})
                riga.append(sp.get("dettaglio", {}).get(chiave, ""))
            righe.append(riga)

    # --- SP Passivo ---
    for sezione_nome in ("patrimonio_netto", "pfn", "debiti_operativi"):
        riga = [f"SP.passivo.{sezione_nome}", "TOTALE"]
        for anno in anni:
            sp = risultati[anno]["sp_riclassificato"]["passivo"].get(sezione_nome, {})
            riga.append(sp.get("totale", ""))
        righe.append(riga)

        primo_anno_sez = risultati[anni[0]]["sp_riclassificato"]["passivo"].get(sezione_nome, {})
        for chiave in primo_anno_sez.get("dettaglio", {}):
            riga = [f"SP.passivo.{sezione_nome}", chiave]
            for anno in anni:
                sp = risultati[anno]["sp_riclassificato"]["passivo"].get(sezione_nome, {})
                riga.append(sp.get("dettaglio", {}).get(chiave, ""))
            righe.append(riga)

    # --- CE ---
    primo_ce = risultati[anni[0]]["ce_riclassificato"]
    for chiave in primo_ce:
        riga = ["CE", chiave]
        for anno in anni:
            ce = risultati[anno]["ce_riclassificato"]
            riga.append(ce.get(chiave, ""))
        righe.append(riga)

    # --- Quadratura ---
    for chiave in ("totale_attivo", "totale_passivo", "delta", "ok"):
        riga = ["Quadratura", chiave]
        for anno in anni:
            q = risultati[anno]["sp_riclassificato"]["quadratura"]
            riga.append(q.get(chiave, ""))
        righe.append(riga)

    return righe


# ---------------------------------------------------------------------------
# Generazione Excel
# ---------------------------------------------------------------------------

def _genera_excel(
    pipeline_result: dict, analisi: Optional[dict], output_dir: Path
) -> str:
    """Genera il file Excel con i fogli richiesti.

    Se analisi e None, il foglio Indici viene omesso.
    """
    azienda = pipeline_result.get("azienda", "azienda")
    anni = _get_anni(pipeline_result)

    fogli: dict[str, list[list[Any]]] = {
        "SP Riclassificato": _prepara_foglio_sp(pipeline_result, anni),
        "CE Riclassificato": _prepara_foglio_ce(pipeline_result, anni),
    }

    # Foglio Indici solo se analisi disponibile
    if analisi is not None:
        fogli["Indici"] = _prepara_foglio_indici(analisi, anni)

    fogli["Dati grezzi"] = _prepara_foglio_dati_grezzi(pipeline_result, anni)

    nome = _nome_file_base(azienda)
    path = str(output_dir / f"{nome}_analisi.xlsx")
    return scrivi_excel(path, fogli)


# ---------------------------------------------------------------------------
# Generazione Word
# ---------------------------------------------------------------------------

def _genera_word(
    pipeline_result: dict, analisi: Optional[dict], output_dir: Path
) -> str:
    """Genera il file Word con il report completo.

    Se analisi e None, le sezioni narrative, alert e indici vengono omesse.
    """
    azienda = pipeline_result.get("azienda", "azienda")
    anni = _get_anni(pipeline_result)
    oggi = datetime.now().strftime("%d/%m/%Y")

    sezioni: list[dict[str, Any]] = []

    # ---------------------------------------------------------------
    # 1. Title page
    # ---------------------------------------------------------------
    sezioni.append({
        "tipo": "titolo",
        "contenuto": f"Analisi di Bilancio - {azienda}",
        "livello": 0,
    })
    sezioni.append({
        "tipo": "paragrafo",
        "contenuto": f"Periodo analizzato: {anni[0]} - {anni[-1]}",
    })
    sezioni.append({
        "tipo": "paragrafo",
        "contenuto": f"Data report: {oggi}",
    })

    # ---------------------------------------------------------------
    # 2. Dati anagrafici
    # ---------------------------------------------------------------
    sezioni.append({
        "tipo": "titolo",
        "contenuto": "Dati anagrafici e perimetro analisi",
        "livello": 1,
    })
    sezioni.append({
        "tipo": "lista",
        "contenuto": [
            f"Azienda: {azienda}",
            f"Anni analizzati: {', '.join(anni)}",
            f"Numero esercizi: {len(anni)}",
            f"Qualita dati: {pipeline_result.get('severity_finale', 'n/d')}",
        ],
    })

    # ---------------------------------------------------------------
    # 3. Tabella SP
    # ---------------------------------------------------------------
    sezioni.append({
        "tipo": "titolo",
        "contenuto": "Stato Patrimoniale Riclassificato",
        "livello": 1,
    })
    sp_righe = _prepara_foglio_sp(pipeline_result, anni)
    sezioni.append({"tipo": "tabella", "contenuto": sp_righe})

    # ---------------------------------------------------------------
    # 4. Tabella CE
    # ---------------------------------------------------------------
    sezioni.append({
        "tipo": "titolo",
        "contenuto": "Conto Economico Riclassificato",
        "livello": 1,
    })
    ce_righe = _prepara_foglio_ce(pipeline_result, anni)
    sezioni.append({"tipo": "tabella", "contenuto": ce_righe})

    # ---------------------------------------------------------------
    # 5. Tabella Indici (solo se analisi disponibile)
    # ---------------------------------------------------------------
    if analisi is not None:
        sezioni.append({
            "tipo": "titolo",
            "contenuto": "Indici di Bilancio",
            "livello": 1,
        })
        indici_righe = _prepara_foglio_indici(analisi, anni)
        sezioni.append({"tipo": "tabella", "contenuto": indici_righe})

    # ---------------------------------------------------------------
    # 6. Analisi e commenti / narrative (solo se analisi disponibile)
    # ---------------------------------------------------------------
    if analisi is not None:
        narrative = analisi.get("narrative", {})

        sezioni.append({
            "tipo": "titolo",
            "contenuto": "Analisi e Commenti",
            "livello": 1,
        })

        sottosezioni_narrative = [
            ("Sintesi", "sintesi"),
            ("Redditivita", "redditivita"),
            ("Struttura Finanziaria", "struttura_finanziaria"),
            ("Liquidita e Ciclo Commerciale", "liquidita"),
            ("Conclusioni", "conclusioni"),
        ]
        for titolo_sub, chiave_narr in sottosezioni_narrative:
            sezioni.append({
                "tipo": "sottotitolo",
                "contenuto": titolo_sub,
                "livello": 1,
            })
            sezioni.append({
                "tipo": "paragrafo",
                "contenuto": narrative.get(chiave_narr, "Non disponibile."),
            })

    # ---------------------------------------------------------------
    # 7. Alert (solo se analisi disponibile)
    # ---------------------------------------------------------------
    if analisi is not None:
        sezioni.append({
            "tipo": "titolo",
            "contenuto": "Alert e Punti di Attenzione",
            "livello": 1,
        })
        alert_list = analisi.get("alert", [])
        if alert_list:
            alert_items = []
            for a in alert_list:
                livello_alert = a.get("tipo", "info").upper()
                indice = a.get("indice", "")
                messaggio = a.get("messaggio", "")
                valore = _fmt_val(a.get("valore"), "indice")
                soglia = a.get("soglia", "")
                alert_items.append(
                    f"[{livello_alert}] {indice}: {messaggio} "
                    f"(valore: {valore}, soglia: {soglia})"
                )
            sezioni.append({"tipo": "lista", "contenuto": alert_items})
        else:
            sezioni.append({
                "tipo": "paragrafo",
                "contenuto": "Nessun alert significativo rilevato.",
            })

        # CAGR (sotto-sezione degli alert/trend)
        cagr_info = analisi.get("cagr", {})
        if cagr_info:
            sezioni.append({
                "tipo": "titolo",
                "contenuto": "Tassi di Crescita (CAGR)",
                "livello": 1,
            })
            cagr_items = []
            for chiave, valore in cagr_info.items():
                cagr_items.append(
                    f"CAGR {chiave}: "
                    f"{formatta_percentuale(valore) if valore is not None else 'n/d'}"
                )
            sezioni.append({"tipo": "lista", "contenuto": cagr_items})

    # ---------------------------------------------------------------
    # 8. Note metodologiche
    # ---------------------------------------------------------------
    sezioni.append({
        "tipo": "titolo",
        "contenuto": "Note Metodologiche e Limitazioni",
        "livello": 1,
    })
    note = [
        "Lo Stato Patrimoniale e stato riclassificato secondo lo schema funzionale (impieghi/fonti).",
        "Il Conto Economico e stato riclassificato a valore aggiunto.",
        "La PFN e calcolata come: debiti finanziari a lungo + debiti finanziari a breve "
        "- disponibilita liquide. PFN positiva = indebitamento netto.",
        "Il ROE e calcolato sul patrimonio netto medio tra inizio e fine periodo "
        "(quando disponibile).",
        "I giorni debiti sono calcolati sugli acquisti di materie prime "
        "(proxy per acquisti totali).",
        "I giorni magazzino sono calcolati sul costo del venduto approssimato "
        "(materie prime + servizi).",
    ]

    # Aggiungi note da checker pre-riclassifica
    checker_pre = pipeline_result.get("checker_pre", {})
    for anno, checks_anno in checker_pre.get("risultati_per_anno", {}).items():
        for check in checks_anno.get("checks", []):
            if check["esito"] == "warn":
                note.append(f"[{anno}] {check['dettaglio']}")

    sezioni.append({"tipo": "lista", "contenuto": note})

    # ---------------------------------------------------------------
    # 9. Appendice: flags qualita
    # ---------------------------------------------------------------
    sezioni.append({
        "tipo": "titolo",
        "contenuto": "Appendice: Risultati Check Qualita",
        "livello": 1,
    })
    checker_items = []
    checker_post = pipeline_result.get("checker_post", {})
    for anno, checks_anno in checker_post.get("risultati_per_anno", {}).items():
        for check in checks_anno.get("checks", []):
            checker_items.append(
                f"[{anno}] {check['codice']}: {check['esito']} - {check['dettaglio']}"
            )
    if checker_items:
        sezioni.append({"tipo": "lista", "contenuto": checker_items})
    else:
        sezioni.append({
            "tipo": "paragrafo",
            "contenuto": "Nessun check post-riclassifica disponibile.",
        })

    nome = _nome_file_base(azienda)
    path = str(output_dir / f"{nome}_report.docx")
    return scrivi_word(path, sezioni)


# ---------------------------------------------------------------------------
# Funzione principale
# ---------------------------------------------------------------------------

def esegui_produzione(pipeline_result: dict, analisi: Optional[dict] = None) -> dict:
    """Genera i file Excel e Word di output.

    Args:
        pipeline_result: Output della pipeline di riclassifica (dict con chiavi
            azienda, riclassifica, checker_pre, checker_post, ecc.).
        analisi: Output dell'agente analista (esegui_analisi). Puo essere None:
            in tal caso vengono omessi il foglio Indici nell'Excel e le sezioni
            narrative/alert nel Word.

    Returns:
        Dict con i path dei file generati:
            - excel_path: percorso del file .xlsx
            - word_path: percorso del file .docx
            - azienda: nome azienda
    """
    output_dir = ROOT / "data" / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    excel_path = _genera_excel(pipeline_result, analisi, output_dir)
    print(f"[produttore] Excel generato: {excel_path}")

    word_path = _genera_word(pipeline_result, analisi, output_dir)
    print(f"[produttore] Word generato: {word_path}")

    return {
        "excel_path": excel_path,
        "word_path": word_path,
        "azienda": pipeline_result.get("azienda", ""),
    }


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Carica pipeline result
    data_path = ROOT / "data" / "output" / "enervit_pipeline_result.json"
    print(f"Caricamento pipeline result da: {data_path}")
    pipeline_result = json.loads(data_path.read_text(encoding="utf-8"))
    print(f"Azienda: {pipeline_result['azienda']}")

    # Prova a caricare analisi (se disponibile)
    analisi: Optional[dict] = None
    analisi_path = ROOT / "data" / "output" / "enervit_analisi.json"
    if analisi_path.exists():
        print(f"Caricamento analisi da: {analisi_path}")
        analisi = json.loads(analisi_path.read_text(encoding="utf-8"))
    else:
        print("File analisi non trovato, generazione senza indici/narrative.")

    # Genera output
    print("\n--- Generazione output ---")
    risultato = esegui_produzione(pipeline_result, analisi)

    print(f"\n{'=' * 60}")
    print("OUTPUT GENERATI")
    print(f"{'=' * 60}")
    print(f"  Excel: {risultato['excel_path']}")
    print(f"  Word:  {risultato['word_path']}")
