"""
test_chunker.py
-----------------
Tests for app.agents.rag.chunker - proving the policy document chunker
correctly splits real policy files into retrieval-ready sections, not
just that it runs without crashing.

These tests run against the REAL 20 policy files in data/policies/, not
synthetic fixtures - if a real file's structure ever breaks the parser
(e.g. someone edits a policy and removes its Policy ID line), these
tests will fail and say exactly which file and why.

Run with:
    cd backend && pytest tests/test_chunker.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agents.rag.chunker import PolicyChunkRecord, chunk_all_policies, chunk_policy_file

# data/policies/ sits at the repo root, two levels up from backend/tests/.
_POLICIES_DIR = Path(__file__).parent.parent.parent / "data" / "policies"


def _require_policies_dir() -> Path:
    if not _POLICIES_DIR.exists():
        pytest.skip(f"data/policies/ not found at {_POLICIES_DIR} - skipping real-corpus tests")
    return _POLICIES_DIR


# =============================================================================
# 1. Single-file chunking correctness
# =============================================================================
def test_chunks_the_cancellation_policy_correctly():
    policies_dir = _require_policies_dir()
    chunks = chunk_policy_file(policies_dir / "02_cancellation_policy.md")

    assert len(chunks) == 7, "Expected 7 sections (1. Purpose through 7. Compliance Notes)"
    assert all(c.policy_id == "POL-CXL-002" for c in chunks)
    assert all(c.version == "2.3" for c in chunks)
    assert all(c.document_title == "Cancellation Policy" for c in chunks)
    assert chunks[0].section_title == "1. Purpose"
    assert chunks[-1].section_title == "7. Compliance Notes for Automated Agents"


def test_chunk_indices_are_sequential_and_zero_based():
    policies_dir = _require_policies_dir()
    chunks = chunk_policy_file(policies_dir / "11_pet_policy.md")
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_section_content_excludes_the_heading_line_itself():
    policies_dir = _require_policies_dir()
    chunks = chunk_policy_file(policies_dir / "11_pet_policy.md")
    for chunk in chunks:
        assert not chunk.content.startswith("##"), (
            f"Chunk content should not include the '## ...' heading line itself: {chunk.content[:50]!r}"
        )


# =============================================================================
# 2. Malformed input is rejected loudly, not silently accepted
# =============================================================================
def test_missing_policy_id_raises_value_error(tmp_path):
    bad_file = tmp_path / "bad_policy.md"
    bad_file.write_text("# A Policy With No ID\n\n**Version:** 1.0\n\n## 1. Section\nSome text.\n")
    with pytest.raises(ValueError, match="Policy ID"):
        chunk_policy_file(bad_file)


def test_missing_version_raises_value_error(tmp_path):
    bad_file = tmp_path / "bad_policy.md"
    bad_file.write_text("# A Policy\n\n**Policy ID:** POL-TEST-999\n\n## 1. Section\nSome text.\n")
    with pytest.raises(ValueError, match="Version"):
        chunk_policy_file(bad_file)


def test_missing_section_headers_raises_value_error(tmp_path):
    bad_file = tmp_path / "bad_policy.md"
    bad_file.write_text(
        "# A Policy\n\n**Policy ID:** POL-TEST-999 | **Version:** 1.0\n\nJust a paragraph, no sections.\n"
    )
    with pytest.raises(ValueError, match="section headers"):
        chunk_policy_file(bad_file)


def test_missing_title_raises_value_error(tmp_path):
    bad_file = tmp_path / "bad_policy.md"
    bad_file.write_text("**Policy ID:** POL-TEST-999 | **Version:** 1.0\n\n## 1. Section\nSome text.\n")
    with pytest.raises(ValueError, match="Title"):
        chunk_policy_file(bad_file)


# =============================================================================
# 3. Whole-corpus (all 20 real files) integration test
# =============================================================================
def test_chunks_all_twenty_real_policy_files():
    policies_dir = _require_policies_dir()
    all_chunks = chunk_all_policies(policies_dir)

    distinct_policy_ids = {c.policy_id for c in all_chunks}
    assert len(distinct_policy_ids) == 20, (
        f"Expected exactly 20 distinct policies, found {len(distinct_policy_ids)}: {sorted(distinct_policy_ids)}"
    )


def test_readme_index_is_excluded_from_ingestion():
    """00_README_index.md documents the corpus itself and must never be
    ingested as if it were real hotel policy content - see chunker.py's
    docstring for why."""
    policies_dir = _require_policies_dir()
    all_chunks = chunk_all_policies(policies_dir)
    assert all(c.source_file != "00_README_index.md" for c in all_chunks)


def test_no_chunk_has_empty_content_or_section_title():
    policies_dir = _require_policies_dir()
    all_chunks = chunk_all_policies(policies_dir)
    for chunk in all_chunks:
        assert chunk.content.strip(), f"{chunk.source_file} chunk {chunk.chunk_index} has empty content"
        assert chunk.section_title.strip(), f"{chunk.source_file} chunk {chunk.chunk_index} has empty section title"


def test_empty_policies_directory_raises_value_error(tmp_path):
    with pytest.raises(ValueError, match="No policy .md files"):
        chunk_all_policies(tmp_path)


def test_policy_chunk_record_is_immutable():
    """PolicyChunkRecord is frozen - a chunk's metadata should never be
    mutated after parsing, since ingest.py and embedder.py both read
    from it without expecting it to change underneath them."""
    record = PolicyChunkRecord(
        source_file="x.md", policy_id="POL-X", document_title="X",
        version="1.0", chunk_index=0, section_title="1. X", content="text",
    )
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
        record.policy_id = "POL-Y"  # type: ignore[misc]