"""
verify_anthropic_key.py
--------------------------
A tiny, standalone script to confirm ANTHROPIC_API_KEY actually works
before wiring real Claude Sonnet reasoning into compliance.py.

This does NOT touch graph.py, conversation.py, or compliance.py - it's a
one-off sanity check, run manually, same pattern as
scripts/verify_voyage_key.py.

Run with:
    cd backend
    python scripts/verify_anthropic_key.py
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

# The current Claude Sonnet model - matches technology_decisions.md and
# graph_entry_contracts.md's "Claude Sonnet" requirement.
CLAUDE_MODEL = "claude-sonnet-5"


def main() -> int:
    api_key = os.getenv("ANTHROPIC_API_KEY")

    if not api_key:
        print("FAILED: ANTHROPIC_API_KEY is not set in your .env file.")
        print("Check that a real '.env' file exists at the repo root with a line like:")
        print("  ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxx")
        return 1

    try:
        import anthropic
    except ImportError:
        print("FAILED: the 'anthropic' package is not installed.")
        print("Run: pip install anthropic")
        return 1

    print(f"ANTHROPIC_API_KEY found. Attempting a real call to {CLAUDE_MODEL}...")

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=50,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Reply with exactly this JSON and nothing else: "
                        '{"status": "ok"}'
                    ),
                }
            ],
        )
    except anthropic.AuthenticationError as exc:
        print(f"FAILED: Anthropic rejected the API key: {exc}")
        return 1
    except anthropic.APIConnectionError as exc:
        print(f"FAILED: could not reach Anthropic's API: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001 - diagnostic script, not production code
        print(f"FAILED: unexpected error calling Claude: {exc}")
        return 1

    reply_text = response.content[0].text if response.content else ""
    print("SUCCESS.")
    print(f"  Model used: {CLAUDE_MODEL}")
    print(f"  Reply:      {reply_text!r}")
    print(f"  Input tokens:  {response.usage.input_tokens}")
    print(f"  Output tokens: {response.usage.output_tokens}")
    print()
    print("Your Anthropic API key works and can reach Claude Sonnet.")
    return 0


if __name__ == "__main__":
    sys.exit(main())