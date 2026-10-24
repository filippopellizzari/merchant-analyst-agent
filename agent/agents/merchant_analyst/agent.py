"""Marker + convenience re-export for ADK single-agent mode (`adk run agents/merchant_analyst`).

ADK decides a folder is a single agent by the presence of `agent.py`; the actual module
resolution goes through the facade in `__init__.py`, which points `merchant_analyst.agent`
at the real package.
"""

from merchant_analyst.agent import root_agent  # noqa: F401
