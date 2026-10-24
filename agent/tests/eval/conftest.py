"""Make `merchant_eval` importable regardless of how pytest is invoked."""

import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parents[2]
if str(AGENT_DIR) not in sys.path:
    sys.path.insert(0, str(AGENT_DIR))
