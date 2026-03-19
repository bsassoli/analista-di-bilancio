"""Test per le funzioni di agents/base.py."""

import json
import pytest
from unittest.mock import MagicMock, patch

from agents.base import agent_loop, esegui_tool, definisci_tools_per_agente


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------

def _make_text_response(text):
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    return response


def _make_tool_use_response(tool_name, tool_input, tool_id="test_id"):
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = ""
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.name = tool_name
    tool_block.input = tool_input
    tool_block.id = tool_id
    response = MagicMock()
    response.content = [text_block, tool_block]
    return response


# ---------------------------------------------------------------------------
# TestEseguiTool
# ---------------------------------------------------------------------------

class TestEseguiTool:

    def test_normalizza_numero(self):
        result = esegui_tool("normalizza_numero", {"stringa": "1.250.000"})
        assert result == 1_250_000

    def test_normalizza_numero_negativo(self):
        result = esegui_tool("normalizza_numero", {"stringa": "(350.000)"})
        assert result == -350_000

    def test_genera_id(self):
        result = esegui_tool("genera_id", {"label": "Totale Attivo"})
        assert isinstance(result, str)
        assert "totale_attivo" in result

    def test_verifica_quadratura_ok(self):
        result = esegui_tool("verifica_quadratura", {
            "totale_attivo": 1_000_000,
            "totale_passivo": 1_000_000,
        })
        assert result["ok"] is True
        assert result["delta"] == 0

    def test_verifica_quadratura_fail(self):
        result = esegui_tool("verifica_quadratura", {
            "totale_attivo": 1_000_000,
            "totale_passivo": 900_000,
        })
        assert result["ok"] is False

    def test_unknown_tool_returns_error(self):
        result = esegui_tool("tool_inesistente", {})
        assert "error" in result


# ---------------------------------------------------------------------------
# TestDefinisciToolsPerAgente
# ---------------------------------------------------------------------------

class TestDefinisciToolsPerAgente:

    def test_skill_estrazione_pdf(self):
        tools = definisci_tools_per_agente("skill_estrazione_pdf")
        assert len(tools) > 0
        names = [t["name"] for t in tools]
        assert "estrai_tabelle_pdf" in names

    def test_skill_estrazione_numerica(self):
        tools = definisci_tools_per_agente("skill_estrazione_numerica")
        assert len(tools) > 0
        names = [t["name"] for t in tools]
        assert "normalizza_numero" in names

    def test_skill_riclassifica(self):
        tools = definisci_tools_per_agente("skill_riclassifica")
        assert len(tools) > 0

    def test_skill_checker(self):
        tools = definisci_tools_per_agente("skill_checker")
        assert len(tools) > 0

    def test_skill_analisi(self):
        tools = definisci_tools_per_agente("skill_analisi")
        assert len(tools) > 0

    def test_unknown_agent_empty_list(self):
        tools = definisci_tools_per_agente("agente_inesistente")
        assert tools == []


# ---------------------------------------------------------------------------
# TestAgentLoop
# ---------------------------------------------------------------------------

class TestAgentLoop:

    @patch("agents.base.crea_client")
    @patch("agents.base.carica_skill")
    def test_text_only_response_returns_json(self, mock_skill, mock_client):
        mock_skill.return_value = "You are a test agent."
        client_instance = MagicMock()
        mock_client.return_value = client_instance

        json_text = json.dumps({"risultato": "ok", "valore": 42})
        client_instance.messages.create.return_value = _make_text_response(json_text)

        result = agent_loop("skill_checker", {"task": "test"})
        assert result == {"risultato": "ok", "valore": 42}

    @patch("agents.base.crea_client")
    @patch("agents.base.carica_skill")
    def test_tool_use_then_text(self, mock_skill, mock_client):
        mock_skill.return_value = "You are a test agent."
        client_instance = MagicMock()
        mock_client.return_value = client_instance

        # First call: tool use (normalizza_numero)
        tool_response = _make_tool_use_response(
            "normalizza_numero", {"stringa": "1.000.000"}, "tool_1"
        )
        # Second call: text response with JSON
        json_text = json.dumps({"risultato": "completato"})
        text_response = _make_text_response(json_text)

        client_instance.messages.create.side_effect = [tool_response, text_response]

        result = agent_loop("skill_estrazione_numerica", {"task": "test"})
        assert result == {"risultato": "completato"}
        assert client_instance.messages.create.call_count == 2

    @patch("agents.base.crea_client")
    @patch("agents.base.carica_skill")
    def test_max_turns_reached(self, mock_skill, mock_client):
        mock_skill.return_value = "You are a test agent."
        client_instance = MagicMock()
        mock_client.return_value = client_instance

        # Always returns tool use, never text
        tool_response = _make_tool_use_response(
            "normalizza_numero", {"stringa": "100"}, "tool_loop"
        )
        client_instance.messages.create.return_value = tool_response

        result = agent_loop("skill_estrazione_numerica", {"task": "test"}, max_turns=3)
        assert "error" in result
        assert result["max_turns"] == 3

    @patch("agents.base.crea_client")
    @patch("agents.base.carica_skill")
    def test_non_json_text_returns_raw_response(self, mock_skill, mock_client):
        mock_skill.return_value = "You are a test agent."
        client_instance = MagicMock()
        mock_client.return_value = client_instance

        client_instance.messages.create.return_value = _make_text_response(
            "This is not valid JSON at all"
        )

        result = agent_loop("skill_checker", {"task": "test"})
        assert "raw_response" in result
        assert "not valid JSON" in result["raw_response"]
