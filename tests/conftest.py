"""Test configuration.

Puts ``src/`` on ``sys.path`` so the suite runs without an editable install. This keeps
unit tests independent of the heavy CrewAI/LiteLLM dependencies (which are lazily imported
by the package and faked via ``sys.modules`` in individual tests).
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
