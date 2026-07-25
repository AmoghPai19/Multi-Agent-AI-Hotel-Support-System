"""
conftest.py
-----------
Pytest configuration for the `backend/` package. Ensures `backend/` itself
is on `sys.path` so `import app.agents.graph` resolves correctly no
matter which directory `pytest` is invoked from, without requiring
contributors to manually set PYTHONPATH.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))