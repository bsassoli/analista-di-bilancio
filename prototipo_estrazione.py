"""Prototipo estrazione bilancio Enervit S.p.A. 2024 (IFRS).

Estrae SP e CE dal bilancio separato, normalizza nello schema di progetto.
Serve come base per il subagente estrattore numerico.
"""

import json
from pathlib import Path

from tools.pdf_parser import normalizza_numero, genera_id, identifica_sezione
from tools.validatori import valida_schema_normalizzato, valida_quadratura_sp, calcola_severity
from tools.schema import crea_voce

import pdfplumber


PDF_PATH = "data/input/Relazione_finanziaria_al_bilancio_d_esercizio_al_31_dicembre_2024_e_al_Bilancio_consolidato_al_31_dicembre_2024.pdf"

# Pagine del bilancio separato Enervit (0-indexed)
PAG_SP_ATTIVO = 51   # pag. 52
PAG_SP_PASSIVO = 52  # pag. 53
PAG_CE = 53          # pag. 54


def split_multiline_cells(table: list[list[str]]) -> list[list[str]]:
    """Espande righe con celle multi-linea in righe singole.

    pdfplumber a volte raggruppa più voci in una sola cella separata da \\n.
    Questa funzione le espande in righe indipendenti.
    """
    expanded = []
    for row in table:
        # Controlla se qualche cella contiene newline
        max_lines = 1
        split_cells = []
        for cell in row:
            cell_str = cell.strip() if cell else ""
            lines = cell_str.split("\n") if cell_str else [""]
            split_cells.append(lines)
            max_lines = max(max_lines, len(lines))

        if max_lines == 1:
            expanded.append([c[0] if c else "" for c in split_cells])
        else:
            # Espandi: la prima colonna ha le label, le altre i valori
            for i in range(max_lines):
                new_row = []
                for cells in split_cells:
                    if i < len(cells):
                        new_row.append(cells[i].strip())
                    else:
                        new_row.append("")
                expanded.append(new_row)

    return expanded


def estrai_voci_da_tabelle(tables: list[list[list[str]]], anni: list[str]) -> list[dict]:
    """Converte tabelle estratte in voci normalizzate.

    Args:
        tables: Lista di tabelle (ciascuna = lista di righe).
        anni: Es. ["2024", "2023"].

    Returns:
        Lista di voci normalizzate.
    """
    voci = []

    for table in tables:
        rows = split_multiline_cells(table)

        for row in rows:
            if not row or len(row) < 3:
                continue

            label = row[0].strip() if row[0] else ""

            # Salta intestazioni e righe vuote
            if not label or label in ("", "Note"):
                continue
            if label.upper() in ("ATTIVITA'", "ATTIVITÀ", "PATRIMONIO NETTO E PASSIVITA'",
                                  "PATRIMONIO NETTO E PASSIVITÀ"):
                continue
            if label in ("Attività non correnti", "Attività correnti",
                         "Passività non correnti", "Passività correnti",
                         "Immobilizzazioni materiali", "Immobilizzazioni immateriali",
                         "Patrimonio netto"):
                continue

            # Salta righe "di cui" (informative, non sommabili)
            if label.lower().startswith("di cui"):
                continue

            # Estrai valori numerici
            # Struttura: [label, note_ref, val_2024, val_2023] oppure [label, val_2024, val_2023]
            val_cols = []
            for cell in row[1:]:
                cell = cell.strip() if cell else ""
                if not cell:
                    continue
                # Salta i riferimenti alle note (numeri piccoli senza punti)
                if cell.isdigit() and len(cell) <= 2:
                    continue
                val_cols.append(cell)

            if len(val_cols) < 2:
                # Potrebbe essere un totale con meno colonne
                if len(val_cols) == 0:
                    continue

            # Parsa valori
            valori = {}
            for i, anno in enumerate(anni):
                if i < len(val_cols):
                    valori[anno] = normalizza_numero(val_cols[i])
                else:
                    valori[anno] = None

            # Determina se è un totale
            is_totale = label.upper().startswith("TOTALE") or label.upper().startswith("TOTALE ")

            voce = crea_voce(
                id=genera_id(label),
                label=label,
                livello=1 if is_totale else 2,
                aggregato="",  # Da mappare successivamente
                valore=valori,
                fonte_riga_bilancio="",
                non_standard=False,
                flags=[],
                note="",
            )
            voci.append(voce)

    return voci


def estrai_ce_da_testo(text: str, anni: list[str]) -> list[dict]:
    """Estrae il CE dal testo della pagina (più affidabile delle tabelle per il CE).

    Il CE di Enervit ha una struttura che pdfplumber fatica a tabulare.
    Parsing riga per riga dal testo.
    """
    voci = []
    lines = text.strip().split("\n")
    pending_label = None  # Per gestire label spezzate su 2 righe
    skip_next_text_line = False  # Salta la continuazione testo dopo label spezzata

    # Pattern: le righe del CE hanno label + valori numerici
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Salta intestazioni
        skip_patterns = [
            "Enervit S.p.A.", "Prospetto di conto economico",
            "PROSPETTO DI CONTO ECONOMICO", "Al 31 dicembre",
            "(valori espressi", "Relazione finanziaria",
            "Informazioni per azioni", "Accantonamenti per dismissioni",
            "Imposte su effetto", "Imposte su altre componenti",
        ]
        if any(pat in line for pat in skip_patterns):
            continue

        # Cerca pattern: label seguita da numeri (con punti e parentesi)
        # Es: "Ricavi 48 95.096.607 85.448.742"
        # Es: "Materie prime, materiali di confezionamento e di consumo 50 (35.135.275) (27.230.355)"
        # Strategia: splitta dal fondo, gli ultimi 2-3 token sono numeri

        parts = line.split()
        if len(parts) < 2:
            continue

        # Trova dove iniziano i valori numerici (da destra)
        num_values = []
        label_parts = list(parts)

        while label_parts:
            last = label_parts[-1]
            # Un valore numerico: contiene cifre e punti, o è tra parentesi
            cleaned = last.strip("()")
            if cleaned.replace(".", "").replace(",", "").replace("-", "").isdigit() and "." in last:
                num_values.insert(0, last)
                label_parts.pop()
            elif last == "-":
                num_values.insert(0, last)
                label_parts.pop()
            else:
                break

        # Caso speciale: riga con solo numeri e nessuna label → label pendente
        if not label_parts and num_values and pending_label:
            label = pending_label
            pending_label = None
            skip_next_text_line = True
            valori = {}
            for i, anno in enumerate(anni):
                if i < len(num_values):
                    valori[anno] = normalizza_numero(num_values[i])
            voce = crea_voce(
                id=genera_id(label),
                label=label,
                livello=2,
                aggregato="",
                valore=valori,
                non_standard=False,
                flags=[],
                note="",
            )
            voci.append(voce)
            continue

        if len(num_values) < 2:
            # Riga di solo testo senza numeri
            if not num_values:
                if skip_next_text_line:
                    skip_next_text_line = False
                    continue
                pending_label = line.strip()
            continue

        # Riga normale con label + numeri
        skip_next_text_line = False

        # Se avevamo una label pendente, ignoriamola (non era una label spezzata)
        pending_label = None

        # Rimuovi eventuale riferimento nota (ultimo numero senza punti nella label)
        if label_parts and label_parts[-1].isdigit() and len(label_parts[-1]) <= 2:
            label_parts.pop()

        label = " ".join(label_parts).strip()
        if not label:
            continue

        valori = {}
        for i, anno in enumerate(anni):
            if i < len(num_values):
                valori[anno] = normalizza_numero(num_values[i])

        is_totale = any(k in label.upper() for k in (
            "EBITDA", "EBIT", "RISULTATO", "TOTALE"
        ))

        voce = crea_voce(
            id=genera_id(label),
            label=label,
            livello=1 if is_totale else 2,
            aggregato="",
            valore=valori,
            non_standard=False,
            flags=[],
            note="",
        )
        voci.append(voce)

    return voci


def main():
    print("=" * 70)
    print("PROTOTIPO ESTRAZIONE — Enervit S.p.A. Bilancio Separato 2024")
    print("=" * 70)
    print()

    pdf = pdfplumber.open(PDF_PATH)
    anni = ["2024", "2023"]

    # --- Estrai SP ---
    print(">>> Estrazione Stato Patrimoniale...")

    sp_tables_attivo = pdf.pages[PAG_SP_ATTIVO].extract_tables()
    sp_tables_passivo = pdf.pages[PAG_SP_PASSIVO].extract_tables()

    voci_sp = estrai_voci_da_tabelle(sp_tables_attivo + sp_tables_passivo, anni)

    print(f"    Voci SP estratte: {len(voci_sp)}")
    for v in voci_sp:
        val24 = v["valore"].get("2024")
        val23 = v["valore"].get("2023")
        marker = "  **" if v["livello"] == 1 else "    "
        print(f"{marker}{v['label']:<60} {val24:>15,}  {val23:>15,}" if val24 is not None and val23 is not None
              else f"{marker}{v['label']:<60} {val24}  {val23}")
    print()

    # --- Estrai CE ---
    print(">>> Estrazione Conto Economico...")

    ce_text = pdf.pages[PAG_CE].extract_text() or ""
    voci_ce = estrai_ce_da_testo(ce_text, anni)

    print(f"    Voci CE estratte: {len(voci_ce)}")
    for v in voci_ce:
        val24 = v["valore"].get("2024")
        val23 = v["valore"].get("2023")
        marker = "  **" if v["livello"] == 1 else "    "
        if val24 is not None and val23 is not None:
            print(f"{marker}{v['label']:<60} {val24:>15,}  {val23:>15,}")
        else:
            print(f"{marker}{v['label']:<60} {val24}  {val23}")
    print()

    # --- Costruisci schema normalizzato ---
    # Trova totali dichiarati
    totale_attivo = None
    totale_passivo = None
    utile = None

    for v in voci_sp:
        if "totale_attivo" in v["id"] or v["label"] == "TOTALE ATTIVO":
            totale_attivo = v["valore"]
        if "totale_passivo" in v["id"] or v["label"] == "TOTALE PASSIVO":
            totale_passivo = v["valore"]
        if "utile" in v["id"].lower() and "perdita" in v["id"].lower():
            utile = v["valore"]

    # Cerca utile nel CE se non trovato in SP
    if utile is None:
        for v in voci_ce:
            if "risultato_netto_d_esercizio" in v["id"]:
                utile = v["valore"]
                break

    schema = {
        "azienda": "Enervit S.p.A.",
        "anni_estratti": [2024, 2023],
        "tipo_bilancio": "ordinario",  # IFRS quotata
        "sp": voci_sp,
        "ce": voci_ce,
        "metadata": {
            "pagine_sp": [52, 53],
            "pagine_ce": [54],
            "totale_attivo_dichiarato": totale_attivo or {},
            "totale_passivo_dichiarato": totale_passivo or {},
            "utile_dichiarato": utile or {},
            "formato": "IFRS",
            "nota": "Bilancio separato Enervit S.p.A. — società quotata, principi IAS/IFRS",
        },
    }

    # --- Validazione ---
    print(">>> Validazione...")
    issues = valida_schema_normalizzato(schema)
    for anno in ["2024", "2023"]:
        issues.append(valida_quadratura_sp(schema, anno))

    severity, score = calcola_severity(issues)

    print(f"    Severity: {severity} (score: {score})")
    for issue in issues:
        print(f"    [{issue.get('severity', issue.get('severity_contributo', '?'))}] "
              f"{issue.get('codice', '?')}: {issue.get('dettaglio', '')}")
    print()

    # --- Salva output ---
    output_path = Path("data/output/enervit_schema_normalizzato.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f">>> Schema salvato in: {output_path}")

    # --- Riepilogo ---
    print()
    print("=" * 70)
    print("RIEPILOGO")
    print("=" * 70)
    ta = (totale_attivo or {}).get("2024")
    tp = (totale_passivo or {}).get("2023")
    print(f"  Totale Attivo 2024:  {ta:>15,}" if ta else "  Totale Attivo 2024:  N/D")
    ta_23 = (totale_attivo or {}).get("2023")
    print(f"  Totale Attivo 2023:  {ta_23:>15,}" if ta_23 else "  Totale Attivo 2023:  N/D")
    tp_24 = (totale_passivo or {}).get("2024")
    print(f"  Totale Passivo 2024: {tp_24:>15,}" if tp_24 else "  Totale Passivo 2024: N/D")
    tp_23 = (totale_passivo or {}).get("2023")
    print(f"  Totale Passivo 2023: {tp_23:>15,}" if tp_23 else "  Totale Passivo 2023: N/D")
    u24 = (utile or {}).get("2024")
    u23 = (utile or {}).get("2023")
    print(f"  Utile 2024:          {u24:>15,}" if u24 else "  Utile 2024:          N/D")
    print(f"  Utile 2023:          {u23:>15,}" if u23 else "  Utile 2023:          N/D")
    print(f"  Voci SP: {len(voci_sp)}, Voci CE: {len(voci_ce)}")
    print(f"  Qualità: {severity} ({score})")


if __name__ == "__main__":
    main()
