"""Tool per estrazione dati da PDF di bilanci italiani.

Usa pdfplumber come parser primario, con fallback a pymupdf.
"""

import re
from pathlib import Path
from typing import Optional

import pdfplumber


def estrai_tabelle_pdf(
    path: str, pagine: Optional[list[int]] = None
) -> list[dict]:
    """Estrae tabelle da un PDF di bilancio.

    Args:
        path: Path al file PDF.
        pagine: Lista di numeri pagina (0-based). Se None, tutte le pagine.

    Returns:
        Lista di dict con chiavi: pagina, righe (lista di liste di stringhe).
    """
    risultati = []
    with pdfplumber.open(path) as pdf:
        target_pages = (
            [pdf.pages[i] for i in pagine] if pagine else pdf.pages
        )
        for page in target_pages:
            tables = page.extract_tables()
            for table in tables:
                righe = []
                for row in table:
                    righe.append([cell.strip() if cell else "" for cell in row])
                if righe:
                    risultati.append(
                        {"pagina": page.page_number, "righe": righe}
                    )
    return risultati


def estrai_testo_pdf(path: str, pagine: Optional[list[int]] = None) -> list[dict]:
    """Estrae testo grezzo da pagine specifiche di un PDF.

    Args:
        path: Path al file PDF.
        pagine: Lista di numeri pagina (0-based). Se None, tutte le pagine.

    Returns:
        Lista di dict con chiavi: pagina, testo.
    """
    risultati = []
    with pdfplumber.open(path) as pdf:
        target_pages = (
            [pdf.pages[i] for i in pagine] if pagine else pdf.pages
        )
        for page in target_pages:
            testo = page.extract_text() or ""
            risultati.append({"pagina": page.page_number, "testo": testo})
    return risultati


def identifica_sezione(testo: str, tipo: Optional[str] = None) -> str | None:
    """Identifica se un testo contiene SP, CE, Nota Integrativa, o Relazione.

    Args:
        testo: Testo estratto da una pagina.
        tipo: Se specificato, verifica solo quel tipo.

    Returns:
        Tipo sezione identificata o None.
    """
    testo_lower = testo.lower()

    patterns = {
        "sp": [
            r"stato\s+patrimoniale",
            r"attivo\b.*\bpassivo\b",
            r"immobilizzazioni",
            r"patrimonio\s+netto",
        ],
        "ce": [
            r"conto\s+economico",
            r"valore\s+della\s+produzione",
            r"costi\s+della\s+produzione",
            r"risultato\s+prima\s+delle\s+imposte",
        ],
        "nota_integrativa": [
            r"nota\s+integrativa",
            r"criteri\s+di\s+valutazione",
            r"principi\s+contabili",
        ],
        "relazione_gestione": [
            r"relazione\s+sulla\s+gestione",
            r"relazione\s+del.*amministrat",
        ],
    }

    if tipo:
        for pattern in patterns.get(tipo, []):
            if re.search(pattern, testo_lower):
                return tipo
        return None

    for sezione, pats in patterns.items():
        for pattern in pats:
            if re.search(pattern, testo_lower):
                return sezione
    return None


def normalizza_numero(stringa: str) -> int | None:
    """Converte una stringa numerica in formato italiano in intero.

    Gestisce:
    - Separatore migliaia: punto (1.250.000)
    - Negativi tra parentesi: (350.000) → -350000
    - Trattino o vuoto → 0
    - Caratteri non parsabili → None

    Args:
        stringa: Stringa contenente il numero.

    Returns:
        Intero o None se non parsabile.
    """
    if not stringa:
        return 0

    s = stringa.strip()

    # Trattino = zero
    if s in ("-", "–", "—", ""):
        return 0

    # Asterischi = dato mancante
    if re.match(r"^\*+$", s):
        return None

    # Rileva negativi tra parentesi
    negativo = False
    if s.startswith("(") and s.endswith(")"):
        negativo = True
        s = s[1:-1].strip()

    # Rileva segno meno esplicito
    if s.startswith("-"):
        negativo = True
        s = s[1:].strip()

    # Rimuovi separatori migliaia (punti)
    s = s.replace(".", "")

    # Gestisci decimali (virgola) — arrotonda
    if "," in s:
        parti = s.split(",")
        s = parti[0]

    # Rimuovi spazi e caratteri non numerici residui
    s = re.sub(r"[^\d]", "", s)

    if not s:
        return None

    valore = int(s)
    return -valore if negativo else valore


def genera_id(label: str) -> str:
    """Genera un ID normalizzato da una label di voce di bilancio.

    Args:
        label: Label testuale (es. "Immobilizzazioni materiali").

    Returns:
        ID normalizzato (es. "immobilizzazioni_materiali").
    """
    # Lowercase
    s = label.lower().strip()
    # Rimuovi riferimenti articolo (es. "II -", "B.I.1")
    s = re.sub(r"^[A-Z]\.?[IVX]*\.?\d*\s*[-–—]\s*", "", s, flags=re.IGNORECASE)
    # Rimuovi parentesi e contenuto
    s = re.sub(r"\([^)]*\)", "", s)
    # Sostituisci caratteri non alfanumerici con underscore
    s = re.sub(r"[^a-z0-9àèéìòù]+", "_", s)
    # Rimuovi underscore iniziali/finali e multipli
    s = re.sub(r"_+", "_", s).strip("_")
    return s
