"""Base agent: logica condivisa per tutti i subagenti."""

import json
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv(override=True)

import anthropic


def carica_skill(nome_agente: str) -> str:
    """Carica il contenuto del file SKILL.md per un agente.

    Args:
        nome_agente: Nome del file skill senza estensione (es. "skill_riclassifica").

    Returns:
        Contenuto del file SKILL.md come stringa.
    """
    skill_path = Path(__file__).parent.parent / "skills" / f"{nome_agente}.md"
    return skill_path.read_text(encoding="utf-8")


def carica_stato(azienda: str) -> dict | None:
    """Carica il documento di stato persistente per un'azienda.

    Returns:
        Dict stato o None se non esiste.
    """
    stato_path = (
        Path(__file__).parent.parent / "data" / "stato" / f"{azienda}_stato.json"
    )
    if stato_path.exists():
        return json.loads(stato_path.read_text(encoding="utf-8"))
    return None


def salva_stato(azienda: str, stato: dict) -> str:
    """Salva il documento di stato persistente.

    Returns:
        Path del file salvato.
    """
    stato_path = (
        Path(__file__).parent.parent / "data" / "stato" / f"{azienda}_stato.json"
    )
    stato_path.parent.mkdir(parents=True, exist_ok=True)
    stato_path.write_text(json.dumps(stato, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(stato_path)


def crea_client() -> anthropic.Anthropic:
    """Crea un client Anthropic."""
    return anthropic.Anthropic()


def definisci_tools_per_agente(nome_agente: str) -> list[dict]:
    """Restituisce le definizioni dei tools disponibili per un agente.

    Ogni agente ha accesso solo ai tools specificati nel suo SKILL.md.
    I tools sono funzioni Python esposte come tool use all'LLM.
    """
    tools_registry = {
        "skill_estrazione_pdf": [
            {
                "name": "estrai_tabelle_pdf",
                "description": "Estrae tabelle da un PDF di bilancio con pdfplumber. Restituisce lista di tabelle con righe. Le celle possono contenere newline (valori multipli raggruppati).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path al file PDF"},
                        "pagine": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Numeri pagina (0-based). Omettere per tutte.",
                        },
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "estrai_testo_pdf",
                "description": "Estrae testo grezzo da pagine di un PDF. Utile quando le tabelle non sono ben strutturate.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path al file PDF"},
                        "pagine": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Numeri pagina (0-based). Omettere per tutte.",
                        },
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "identifica_sezione",
                "description": "Identifica se un testo contiene SP, CE, Nota Integrativa o Relazione sulla gestione.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "testo": {"type": "string"},
                        "tipo": {
                            "type": "string",
                            "enum": ["sp", "ce", "nota_integrativa", "relazione_gestione"],
                        },
                    },
                    "required": ["testo"],
                },
            },
            {
                "name": "conta_pagine_pdf",
                "description": "Restituisce il numero totale di pagine del PDF.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path al file PDF"},
                    },
                    "required": ["path"],
                },
            },
        ],
        "skill_estrazione_numerica": [
            {
                "name": "normalizza_numero",
                "description": "Converte stringa numerica italiana in intero. Es: '1.250.000' → 1250000, '(350.000)' → -350000.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "stringa": {"type": "string"},
                    },
                    "required": ["stringa"],
                },
            },
            {
                "name": "genera_id",
                "description": "Genera ID normalizzato da label voce bilancio.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string"},
                    },
                    "required": ["label"],
                },
            },
            {
                "name": "calcola_subtotale",
                "description": "Somma valori di un subset di voci per un dato anno.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "voci": {"type": "array", "description": "Lista voci bilancio JSON"},
                        "ids": {"type": "array", "items": {"type": "string"}},
                        "anno": {"type": "string"},
                    },
                    "required": ["voci", "ids", "anno"],
                },
            },
        ],
        "skill_estrazione_qualitativa": [
            {
                "name": "estrai_testo_pdf",
                "description": "Estrae testo grezzo da pagine di un PDF.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Path al file PDF"},
                        "pagine": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Numeri pagina (0-based). Omettere per tutte.",
                        },
                    },
                    "required": ["path"],
                },
            },
            {
                "name": "identifica_sezione",
                "description": "Identifica se un testo contiene SP, CE, Nota Integrativa o Relazione sulla gestione.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "testo": {"type": "string"},
                        "tipo": {
                            "type": "string",
                            "enum": ["sp", "ce", "nota_integrativa", "relazione_gestione"],
                        },
                    },
                    "required": ["testo"],
                },
            },
            {
                "name": "cerca_pattern_testo",
                "description": "Cerca pattern regex nel testo e restituisce i match con contesto (±100 chars).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "testo": {"type": "string", "description": "Testo in cui cercare"},
                        "patterns": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Lista di pattern regex da cercare",
                        },
                    },
                    "required": ["testo", "patterns"],
                },
            },
        ],
        "skill_checker": [
            {
                "name": "verifica_quadratura",
                "description": "Verifica quadratura SP: totale attivo vs totale passivo.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "totale_attivo": {"type": "integer"},
                        "totale_passivo": {"type": "integer"},
                        "tolleranza": {"type": "integer", "default": 1},
                    },
                    "required": ["totale_attivo", "totale_passivo"],
                },
            },
            {
                "name": "calcola_variazione_yoy",
                "description": "Calcola variazione percentuale Year-over-Year.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "valore_n": {"type": "number"},
                        "valore_n1": {"type": "number"},
                    },
                    "required": ["valore_n", "valore_n1"],
                },
            },
        ],
        "skill_riclassifica": [
            {
                "name": "calcola_subtotale",
                "description": "Somma valori di un subset di voci per un dato anno.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "voci": {"type": "array", "description": "Lista voci bilancio JSON"},
                        "ids": {"type": "array", "items": {"type": "string"}},
                        "anno": {"type": "string"},
                    },
                    "required": ["voci", "ids", "anno"],
                },
            },
            {
                "name": "verifica_quadratura",
                "description": "Verifica quadratura SP.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "totale_attivo": {"type": "integer"},
                        "totale_passivo": {"type": "integer"},
                        "tolleranza": {"type": "integer", "default": 1},
                    },
                    "required": ["totale_attivo", "totale_passivo"],
                },
            },
            {
                "name": "calcola_ccon",
                "description": "Calcola il Capitale Circolante Operativo Netto (CCON = crediti comm. + rimanenze + altri crediti op. - debiti operativi).",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "crediti_commerciali": {"type": "integer"},
                        "rimanenze": {"type": "integer"},
                        "altri_crediti_operativi": {"type": "integer"},
                        "debiti_operativi": {"type": "integer"},
                    },
                    "required": ["crediti_commerciali", "rimanenze", "altri_crediti_operativi", "debiti_operativi"],
                },
            },
            {
                "name": "calcola_pfn",
                "description": "Calcola la Posizione Finanziaria Netta (PFN = debiti fin. lungo + debiti fin. breve - disponibilita liquide). PFN positiva = indebitamento.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "debiti_fin_lungo": {"type": "integer"},
                        "debiti_fin_breve": {"type": "integer"},
                        "disponibilita_liquide": {"type": "integer"},
                    },
                    "required": ["debiti_fin_lungo", "debiti_fin_breve", "disponibilita_liquide"],
                },
            },
        ],
        "skill_analisi": [
            {
                "name": "calcola_indice",
                "description": "Calcola un indice di bilancio dato nome e valori.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "nome": {"type": "string", "description": "Nome indice (es. 'roe', 'ros', 'pfn_su_ebitda')"},
                        "valori": {"type": "object", "description": "Valori necessari per il calcolo"},
                    },
                    "required": ["nome", "valori"],
                },
            },
            {
                "name": "calcola_variazione_yoy",
                "description": "Calcola variazione percentuale Year-over-Year.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "valore_n": {"type": "number"},
                        "valore_n1": {"type": "number"},
                    },
                    "required": ["valore_n", "valore_n1"],
                },
            },
        ],
    }

    return tools_registry.get(nome_agente, [])


def esegui_tool(nome_tool: str, input_args: dict) -> Any:
    """Esegue un tool Python e restituisce il risultato.

    Dispatcher centrale che mappa i nomi tool alle funzioni Python.
    """
    from tools.pdf_parser import (
        estrai_tabelle_pdf,
        estrai_testo_pdf,
        identifica_sezione,
        normalizza_numero,
        genera_id,
        cerca_pattern_testo,
    )
    from tools.calcolatori import (
        calcola_subtotale,
        calcola_ccon,
        calcola_pfn,
        verifica_quadratura,
        variazione_yoy,
    )

    def conta_pagine_pdf(path):
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return len(pdf.pages)

    dispatch = {
        "estrai_tabelle_pdf": lambda args: estrai_tabelle_pdf(
            args["path"], args.get("pagine")
        ),
        "estrai_testo_pdf": lambda args: estrai_testo_pdf(
            args["path"], args.get("pagine")
        ),
        "identifica_sezione": lambda args: identifica_sezione(
            args["testo"], args.get("tipo")
        ),
        "conta_pagine_pdf": lambda args: conta_pagine_pdf(args["path"]),
        "normalizza_numero": lambda args: normalizza_numero(args["stringa"]),
        "genera_id": lambda args: genera_id(args["label"]),
        "calcola_subtotale": lambda args: calcola_subtotale(
            args["voci"], args["ids"], args["anno"]
        ),
        "verifica_quadratura": lambda args: verifica_quadratura(
            args["totale_attivo"], args["totale_passivo"], args.get("tolleranza", 1)
        ),
        "calcola_variazione_yoy": lambda args: variazione_yoy(
            args["valore_n"], args["valore_n1"]
        ),
        "cerca_pattern_testo": lambda args: cerca_pattern_testo(
            args["testo"], args["patterns"]
        ),
        "calcola_ccon": lambda args: calcola_ccon(
            args["crediti_commerciali"], args["rimanenze"],
            args["altri_crediti_operativi"], args["debiti_operativi"]
        ),
        "calcola_pfn": lambda args: calcola_pfn(
            args["debiti_fin_lungo"], args["debiti_fin_breve"],
            args["disponibilita_liquide"]
        ),
    }

    handler = dispatch.get(nome_tool)
    if handler is None:
        return {"error": f"Tool sconosciuto: {nome_tool}"}

    result = handler(input_args)
    return result


def agent_loop(
    nome_agente: str,
    task_input: dict,
    model: str = "claude-sonnet-4-20250514",
    max_turns: int = 20,
) -> dict:
    """Esegue il loop agentivo per un subagente.

    1. Carica SKILL.md come system prompt
    2. Invia task_input come primo messaggio utente
    3. Loop: se il modello chiama tools → esegui → rispondi
    4. Quando il modello risponde con testo → return

    Args:
        nome_agente: Nome del file skill (es. "skill_estrazione_numerica").
        task_input: Dict con i dati di input per il task.
        model: Modello Anthropic da usare.
        max_turns: Numero massimo di turni tool use.

    Returns:
        Dict con il risultato strutturato dell'agente.
    """
    client = crea_client()
    skill = carica_skill(nome_agente)
    tools = definisci_tools_per_agente(nome_agente)

    messages = [
        {
            "role": "user",
            "content": json.dumps(task_input, ensure_ascii=False),
        }
    ]

    for _ in range(max_turns):
        kwargs = {
            "model": model,
            "max_tokens": 8192,
            "system": skill,
            "messages": messages,
        }
        if tools:
            kwargs["tools"] = tools

        response = client.messages.create(**kwargs)

        # Raccoglie testo e tool_use dal response
        text_parts = []
        tool_uses = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_uses.append(block)

        # Se nessun tool_use, il loop è completo
        if not tool_uses:
            testo_finale = "\n".join(text_parts)
            # Prova a parsare JSON dalla risposta
            try:
                return json.loads(testo_finale)
            except json.JSONDecodeError:
                return {"raw_response": testo_finale}

        # Aggiungi la risposta dell'assistente ai messaggi
        messages.append({"role": "assistant", "content": response.content})

        # Esegui i tools e aggiungi i risultati
        tool_results = []
        for tool_use in tool_uses:
            result = esegui_tool(tool_use.name, tool_use.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result,
            })

        messages.append({"role": "user", "content": tool_results})

    # Max turns raggiunto
    return {"error": "Max turns raggiunto", "max_turns": max_turns}
