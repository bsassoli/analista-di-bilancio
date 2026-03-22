"""Parser PDF basato su Docling — estrazione strutturale di tabelle e testo.

Sostituisce pdfplumber come layer di estrazione strutturale.
Docling usa modelli ML per layout detection e table extraction.
"""

import re
from pathlib import Path
from typing import Optional

from docling.document_converter import DocumentConverter

# Cache del converter (il modello si carica una volta)
_converter: DocumentConverter | None = None


def _get_converter() -> DocumentConverter:
    """Restituisce il converter Docling (singleton)."""
    global _converter
    if _converter is None:
        _converter = DocumentConverter()
    return _converter


def converti_documento(path: str) -> "DoclingDocument":
    """Converte un PDF in DoclingDocument.

    Args:
        path: Path al file PDF.

    Returns:
        DoclingDocument con tabelle, testi, metadata.
    """
    converter = _get_converter()
    result = converter.convert(path)
    return result.document


def estrai_tabelle_docling(
    path: str, pagine: Optional[list[int]] = None
) -> list[dict]:
    """Estrae tabelle da un PDF con Docling.

    Args:
        path: Path al file PDF.
        pagine: Numeri pagina (1-based). Se None, tutte.

    Returns:
        Lista di dict con: pagina (1-based), righe (lista di liste),
        dataframe (pandas DataFrame), n_righe, n_colonne.
    """
    doc = converti_documento(path)
    risultati = []

    for table in doc.tables:
        if not table.prov:
            continue

        page_no = table.prov[0].page_no
        if pagine and page_no not in pagine:
            continue

        df = table.export_to_dataframe(doc=doc)
        # Converti DataFrame in lista di liste (come pdfplumber)
        righe = []
        # Header come prima riga
        righe.append([str(c).strip() for c in df.columns])
        for _, row in df.iterrows():
            righe.append([str(c).strip() if c else "" for c in row])

        risultati.append({
            "pagina": page_no,
            "righe": righe,
            "dataframe": df,
            "n_righe": len(df),
            "n_colonne": len(df.columns),
        })

    return risultati


def estrai_testo_docling(
    path: str, pagine: Optional[list[int]] = None
) -> list[dict]:
    """Estrae testo da un PDF con Docling, organizzato per pagina.

    Args:
        path: Path al file PDF.
        pagine: Numeri pagina (1-based). Se None, tutte.

    Returns:
        Lista di dict con: pagina (1-based), testo.
    """
    doc = converti_documento(path)
    testi_per_pagina: dict[int, list[str]] = {}

    for text_item in doc.texts:
        if not text_item.prov:
            continue
        page_no = text_item.prov[0].page_no
        if pagine and page_no not in pagine:
            continue
        testi_per_pagina.setdefault(page_no, []).append(text_item.text)

    risultati = []
    for page_no in sorted(testi_per_pagina.keys()):
        risultati.append({
            "pagina": page_no,
            "testo": "\n".join(testi_per_pagina[page_no]),
        })

    return risultati


def identifica_tabelle_prospetto(path: str) -> dict:
    """Identifica le tabelle che sono prospetti di bilancio (SP, CE).

    Usa Docling per estrarre tutte le tabelle, poi classifica ciascuna
    in base al contenuto (keywords + struttura).

    Returns:
        Dict con:
        - sp_tabelle: lista tabelle SP (con pagina e dataframe)
        - ce_tabelle: lista tabelle CE
        - altre_tabelle: lista tabelle non classificate
        - formato: "IFRS" o "OIC_ordinario"
    """
    doc = converti_documento(path)

    sp_tabelle = []
    ce_tabelle = []
    rf_tabelle = []
    altre_tabelle = []
    segnali_ifrs = 0
    segnali_oic = 0

    for table in doc.tables:
        if not table.prov:
            continue

        df = table.export_to_dataframe(doc=doc)
        page_no = table.prov[0].page_no

        # Converte tutto in stringa lowercase per matching
        testo_tabella = " ".join(
            str(c).lower()
            for c in list(df.columns) + df.values.flatten().tolist()
            if c and str(c).strip()
        )

        # Classifica formato
        if any(kw in testo_tabella for kw in [
            "attività non correnti", "attività correnti",
            "passività non correnti", "ifrs", "ias ",
        ]):
            segnali_ifrs += 1
        if any(kw in testo_tabella for kw in [
            "valore della produzione", "costi della produzione",
            "immobilizzazioni", "a) crediti verso soci",
        ]):
            segnali_oic += 1

        # Classifica tipo tabella
        # Rendiconto finanziario (da escludere dal CE)
        is_rendiconto = any(kw in testo_tabella for kw in [
            "rendiconto finanziario", "flusso di cassa",
            "cash flow", "flussi finanziari",
            "disponibilità liquide iniziali", "disponibilità liquide finali",
            "flusso monetario", "flussi di cassa",
            "incremento delle disponibilit", "decremento delle disponibilit",
        ])

        # SP: contiene "totale attivo" o "totale patrimonio netto" o "attività non correnti"
        is_sp = any(kw in testo_tabella for kw in [
            "totale attivo", "totale attivit",
            "totale patrimonio netto",
            "totale passiv",
            "attività non correnti",
            "passività non correnti",
        ])
        # CE: contiene "risultato operativo" o "ebitda" o "conto economico"
        # Ma esclude tabelle che iniziano con voci SP (misclassificazione)
        is_ce = not is_rendiconto and any(kw in testo_tabella for kw in [
            "risultato operativo", "ebitda", " ebit ",
            "risultato netto", "conto economico",
            "valore della produzione",
            "risultato prima delle imposte",
        ])
        # Escludi tabelle classificate CE ma che iniziano con voci SP o PFN
        if is_ce and len(df) > 0:
            prima_label = str(df.iloc[0, 0]).lower().strip() if len(df.columns) > 0 else ""
            if any(kw in prima_label for kw in [
                "attività non correnti", "attivo", "immobilizzazion",
                "attività correnti", "disponibilità di cassa",
                "posizione finanziaria", "patrimonio netto", "passivo",
            ]):
                is_ce = False

        # Deve avere abbastanza righe per essere un prospetto
        if len(df) < 5:
            altre_tabelle.append({"pagina": page_no, "dataframe": df})
            continue

        # Deve avere colonne numeriche (almeno una colonna con numeri)
        has_numeri = False
        for col_idx in range(len(df.columns)):
            serie = df.iloc[:, col_idx].astype(str)
            n_numeri = serie.str.contains(r'\d{3,}', regex=True).sum()
            if n_numeri >= 3:
                has_numeri = True
                break

        if not has_numeri:
            altre_tabelle.append({"pagina": page_no, "dataframe": df})
            continue

        entry = {"pagina": page_no, "dataframe": df, "n_righe": len(df)}

        if is_rendiconto and has_numeri:
            rf_tabelle.append(entry)
        elif is_sp and not is_ce:
            sp_tabelle.append(entry)
        elif is_ce and not is_sp:
            ce_tabelle.append(entry)
        elif is_sp and is_ce:
            # Ambiguo: guardare se ha più segnali SP o CE
            sp_score = sum(1 for kw in ["attivo", "passivo", "patrimonio"] if kw in testo_tabella)
            ce_score = sum(1 for kw in ["ricavi", "costi", "ebitda", "risultato"] if kw in testo_tabella)
            if sp_score >= ce_score:
                sp_tabelle.append(entry)
            else:
                ce_tabelle.append(entry)
        else:
            altre_tabelle.append({"pagina": page_no, "dataframe": df})

    # Post-filtering: se ci sono troppi prospetti (>4), teniamo solo quelli
    # con più righe e sulla stessa pagina (il prospetto vero è la tabella grande)
    if len(sp_tabelle) > 4:
        sp_tabelle.sort(key=lambda t: t["n_righe"], reverse=True)
        sp_tabelle = sp_tabelle[:4]
    if len(ce_tabelle) > 3:
        ce_tabelle.sort(key=lambda t: t["n_righe"], reverse=True)
        ce_tabelle = ce_tabelle[:3]
    if len(rf_tabelle) > 3:
        rf_tabelle.sort(key=lambda t: t["n_righe"], reverse=True)
        rf_tabelle = rf_tabelle[:3]

    formato = "IFRS" if segnali_ifrs > segnali_oic else "OIC_ordinario"

    return {
        "sp_tabelle": sp_tabelle,
        "ce_tabelle": ce_tabelle,
        "rf_tabelle": rf_tabelle,
        "altre_tabelle": altre_tabelle,
        "formato": formato,
        "n_tabelle_totali": len(list(doc.tables)),
    }


def tabella_a_righe_bilancio(
    df, formato: str = "IFRS", source_page: int | None = None,
) -> list[dict]:
    """Converte un DataFrame Docling in righe di bilancio strutturate.

    Fase deterministica: estrae label, valori, gerarchia dalla tabella.
    Non fa mapping semantico (quello lo fa il LLM).

    Args:
        df: DataFrame pandas da Docling.
        formato: "IFRS" o "OIC_ordinario" per guidare il parsing.
        source_page: 1-based page number where this table was found.

    Returns:
        Lista di dict con: label, valori (dict anno→stringa), livello,
        nota_ref, genitore, source_page.
    """
    righe = []
    cols = list(df.columns)

    # Identifica colonne: prima colonna = label, ultime = valori per anno
    # Cerca colonne con anni (4 cifre) nell'header
    col_anni = {}
    col_note = None
    col_label = 0

    for i, col in enumerate(cols):
        col_str = str(col).strip()
        # Cerca anno (es. "31 dicembre 2024", "2024", "31/12/2024")
        anno_match = re.search(r'20[12]\d', col_str)
        if anno_match:
            anno = anno_match.group()
            col_anni[anno] = i
        elif col_str.lower() in ("note", "nota", "rif.", "rif"):
            col_note = i

    if not col_anni:
        # Fallback: assume ultime 2 colonne sono anni
        if len(cols) >= 3:
            # Prova a estrarre anno dai valori della prima riga
            for i in range(len(cols) - 1, 0, -1):
                col_str = str(cols[i]).strip()
                if re.search(r'\d', col_str):
                    # Potrebbe essere un anno
                    anno_match = re.search(r'20[12]\d', col_str)
                    if anno_match:
                        col_anni[anno_match.group()] = i

    if not col_anni:
        return righe  # Non riusciamo a identificare le colonne anno

    anni_ordinati = sorted(col_anni.keys(), reverse=True)

    for _, row in df.iterrows():
        label = str(row.iloc[col_label]).strip() if col_label < len(row) else ""

        if not label or label.lower() in ("nan", "none", ""):
            continue

        # Valori per anno
        valori = {}
        for anno in anni_ordinati:
            idx = col_anni[anno]
            val_raw = str(row.iloc[idx]).strip() if idx < len(row) else ""
            if val_raw.lower() in ("nan", "none"):
                val_raw = ""
            valori[anno] = val_raw

        # Nota ref
        nota_ref = None
        if col_note is not None and col_note < len(row):
            nota_ref = str(row.iloc[col_note]).strip()
            if nota_ref.lower() in ("nan", "none", ""):
                nota_ref = None

        # Determina livello dalla formattazione
        livello = "dettaglio"
        label_lower = label.lower()

        # Totali
        if label_lower.startswith("totale") or label_lower.startswith("total"):
            livello = "totale"
        # Subtotali
        elif any(kw in label_lower for kw in [
            "totale immobilizzazioni", "totale attivit",
            "totale passivit", "totale patrimonio",
        ]):
            livello = "totale"
        # Sezioni (senza valori numerici, solo header)
        elif all(not v or not re.search(r'\d', v) for v in valori.values()):
            livello = "sezione"
        # "di cui" → informativo
        elif "di cui" in label_lower:
            livello = "di_cui"
        # Aggregati intermedi (EBITDA, EBIT, ecc.)
        elif any(kw in label_lower for kw in [
            "ebitda", "ebit", "risultato operativo",
            "risultato prima", "risultato netto",
            "valore aggiunto", "valore della produzione",
        ]):
            livello = "subtotale"

        righe.append({
            "label": label,
            "valori": valori,
            "livello": livello,
            "nota_ref": nota_ref,
            "genitore": None,
            "source_page": source_page,
        })

    return righe
