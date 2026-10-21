"""pytest configuration for the m4-prediction test suite.

Adds the m4-prediction directory to sys.path so that ``from api import ...``
and ``from inference import ...`` resolve correctly regardless of the working
directory from which pytest is invoked (e.g. the repo root).
"""
import sys
from pathlib import Path

# Ensure the m4-prediction package root is on the path.
M4_ROOT = Path(__file__).resolve().parent.parent
if str(M4_ROOT) not in sys.path:
    sys.path.insert(0, str(M4_ROOT))
