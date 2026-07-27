"""
conftest.py
-----------
Pytest configuration for the `backend/` package. Ensures `backend/` itself
is on `sys.path` so `import app.agents.graph` resolves correctly no
matter which directory `pytest` is invoked from, without requiring
contributors to manually set PYTHONPATH.

Also loads the repo-root `.env` file automatically, so environment
variables like DATABASE_URL_INGEST and VOYAGE_API_KEY are available to
every test without each test file needing its own load_dotenv() call.
Without this, `.env` having the right values means nothing when running
`pytest` directly - nothing else in a bare pytest run ever reads that
file into the process environment.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

try:
    from dotenv import load_dotenv

    # .env sits at the repo root, one level up from backend/.
    load_dotenv(Path(__file__).parent.parent / ".env")
except ImportError:
    # python-dotenv not installed - tests that need real env vars (e.g.
    # test_ingest.py's DATABASE_URL_INGEST-dependent tests) will simply
    # skip, per their own pytest.skip() checks, rather than fail here.
    pass