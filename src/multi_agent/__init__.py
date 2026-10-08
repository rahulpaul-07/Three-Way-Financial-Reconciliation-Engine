"""
A multi-agent front door over the existing investigator and SQL agents.

The engine's modules are flat files in src/ (agent, sql_ask, tools), so src/ is
put on the path here once rather than in every module of the package.
"""

import sys
from pathlib import Path

_SRC = str(Path(__file__).resolve().parents[1])
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
