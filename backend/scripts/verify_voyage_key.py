"""
verify_voyage_key.py
----------------------
A tiny, standalone script to confirm VOYAGE_API_KEY actually works before
building the real RAG ingestion pipeline on top of it.

This does NOT touch graph.py, conversation.py, or compliance.py - it's a
one-off sanity check, run manually, not part of the application itself.

Run with:
    cd backend
    python scripts/verify_voyage_key.py
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

# Load variables from the real .env file (never .env.example) sitting at
# the repo root, one level up from backend/.
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))


def main() -> int:
    api_key = os.getenv("VOYAGE_API_KEY")

    if not api_key:
        print("FAILED: VOYAGE_API_KEY is not set in your .env file.")
        print("Check that:")
        print("  1. A real '.env' file exists at the repo root (not just .env.example).")
        print("  2. It contains a line like: VOYAGE_API_KEY=pa-xxxxxxxxxxxx")
        return 1

    try:
        import voyageai
    except ImportError:
        print("FAILED: the 'voyageai' package is not installed.")
        print("Run: pip install voyageai")
        return 1

    print("VOYAGE_API_KEY found. Attempting a real embedding call...")

    try:
        client = voyageai.Client(api_key=api_key)
        result = client.embed(
            texts=["This is a test sentence for the hotel policy RAG pipeline."],
            model="voyage-4-lite",
            input_type="document",
        )
    except Exception as exc:  # noqa: BLE001 - this is a diagnostic script, not production code
        print(f"FAILED: the API call itself raised an error: {exc}")
        print("Common causes: invalid/expired key, no internet, or a typo in the key.")
        return 1

    vector = result.embeddings[0]
    print("SUCCESS.")
    print(f"  Model used:        voyage-4-lite")
    print(f"  Vector dimensions: {len(vector)}")
    print(f"  Tokens used:       {result.total_tokens}")

    if len(vector) != 1024:
        print()
        print(
            f"WARNING: expected 1024 dimensions (to match schema.sql's "
            f"vector(1024) column), but got {len(vector)}. Double-check the "
            f"model name/dimension settings before building the ingestion pipeline."
        )
        return 1

    print()
    print("Your Voyage AI key works, and the vector size matches schema.sql exactly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())