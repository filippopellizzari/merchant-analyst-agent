"""root_agent wiring."""

from __future__ import annotations

import importlib
import sys

from google.adk.agents import LlmAgent

EXPECTED_TOOLS = [
    "get_dataset_info",
    "get_sales_summary",
    "get_top_products",
    "get_daily_trend",
    "get_traffic_by_source",
    "get_funnel",
    "get_geo_breakdown",
]


def _reload_agent(monkeypatch, model: str | None):
    if model is None:
        monkeypatch.delenv("GEMINI_MODEL", raising=False)
    else:
        monkeypatch.setenv("GEMINI_MODEL", model)
    sys.modules.pop("merchant_analyst.agent", None)
    return importlib.import_module("merchant_analyst.agent")


def test_root_agent_has_seven_tools(monkeypatch):
    mod = _reload_agent(monkeypatch, None)
    agent = mod.root_agent
    assert isinstance(agent, LlmAgent)
    assert agent.name == "merchant_analyst"
    assert [t.__name__ for t in agent.tools] == EXPECTED_TOOLS
    assert agent.model == "gemini-3.5-flash"
    assert agent.description
    for phrase in ("ALWAYS call a tool", "2020-11-01", "2021-01-31", "clamped", "two decimals"):
        assert phrase in agent.instruction


def test_model_comes_from_env(monkeypatch):
    mod = _reload_agent(monkeypatch, "gemini-2.5-pro")
    assert mod.root_agent.model == "gemini-2.5-pro"
    _reload_agent(monkeypatch, None)  # restore default for other tests


def test_discovery_shim_exposes_root_agent():
    sys.modules.pop("merchant_analyst.agent", None)
    import agents.merchant_analyst as shim
    import merchant_analyst.agent as real

    assert shim.root_agent is real.root_agent


def test_adk_agent_loader_discovers_agent():
    """Exactly what `adk web agents` / `adk run agents/merchant_analyst` do."""
    from google.adk.cli.utils.agent_loader import AgentLoader

    loader = AgentLoader("agents")
    assert loader.list_agents() == ["merchant_analyst"]
    loaded = loader.load_agent("merchant_analyst")
    assert isinstance(loaded, LlmAgent)
    assert loaded.name == "merchant_analyst"
    assert [t.__name__ for t in loaded.tools] == EXPECTED_TOOLS

    single = AgentLoader("agents/merchant_analyst")
    assert single.list_agents() == ["merchant_analyst"]
    assert isinstance(single.load_agent("merchant_analyst"), LlmAgent)


def test_tool_declarations_render(monkeypatch):
    from google.adk.tools.function_tool import FunctionTool

    mod = _reload_agent(monkeypatch, None)
    for fn in mod.root_agent.tools:
        decl = FunctionTool(fn)._get_declaration()
        assert decl.name == fn.__name__
        assert decl.description and "YYYY-MM-DD" in decl.description or fn.__name__ == "get_dataset_info"
