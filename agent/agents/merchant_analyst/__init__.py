"""ADK discovery shim: `uv run adk web agents` / `uv run adk run agents/merchant_analyst`.

ADK's AgentLoader inserts the agents dir at the front of sys.path and imports the folder name
as a top-level module, so this folder would shadow the real `merchant_analyst` package and
`from merchant_analyst.agent import root_agent` would hit a circular import. Pointing this
package's `__path__` at the real source tree makes `merchant_analyst.*` resolve correctly
whether this folder is imported as `merchant_analyst` (ADK) or `agents.merchant_analyst`.
"""

from pathlib import Path

_REAL_PACKAGE = Path(__file__).resolve().parents[2] / "merchant_analyst"
if _REAL_PACKAGE.is_dir():
    __path__ = [str(_REAL_PACKAGE)]  # read by the import system

from merchant_analyst.agent import root_agent  # noqa: F401
