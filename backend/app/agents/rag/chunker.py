"""
chunker.py
----------
Splits Amogh's 20 policy Markdown files (in data/policies/) into
retrieval-sized chunks, ready to be embedded and inserted into
`policy_documents` + `policy_chunks`.

This module does NOT call Voyage AI and does NOT touch the database - it
is pure text processing, deliberately kept separate and independently
testable (see tests/test_chunker.py). `embedder.py` will call Voyage AI
on the chunks this module produces; `ingest.py` will insert the results
into Postgres.

CHUNKING STRATEGY (per data/policies/00_README_index.md's own suggestion)
---------------------------------------------------------------------------
Chunk by `##` (level-2 Markdown header) section boundaries, not by a fixed
token window. Every one of the 20 policy files follows the same
structure: a `#` title, a metadata line with `**Policy ID:**` and
`**Version:**`, then a series of `## N. Section Name` sections. Splitting
on `##` keeps each section (including its numbered lists and tables)
intact as one coherent retrieval unit, exactly as the README recommends -
a fixed-size token window would risk cutting a table or a numbered list
in half.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Matches: "**Policy ID:** POL-CXL-002" (captures "POL-CXL-002")
_POLICY_ID_PATTERN = re.compile(r"\*\*Policy ID:\*\*\s*([A-Z0-9-]+)")

# Matches: "**Version:** 2.3" (captures "2.3")
_VERSION_PATTERN = re.compile(r"\*\*Version:\*\*\s*([0-9]+(?:\.[0-9]+)?)")

# Matches a level-2 Markdown header line: "## 1. Purpose" (captures "1. Purpose")
_SECTION_HEADER_PATTERN = re.compile(r"^##\s+(.+)$", re.MULTILINE)

# Matches the document title: the first "# ..." (level-1 header) line.
_TITLE_PATTERN = re.compile(r"^#\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class PolicyChunkRecord:
    """One retrieval-sized chunk, ready for embedding + insertion.

    Field names deliberately mirror schema.sql's `policy_documents` and
    `policy_chunks` tables, so `ingest.py` can map this dataclass to a
    database row with minimal translation:
      - policy_id, document_title, version, category -> policy_documents row
      - section_title, chunk_index, content, category -> policy_chunks row
    """

    source_file: str        # e.g. "02_cancellation_policy.md" (for traceability/debugging)
    policy_id: str          # e.g. "POL-CXL-002"
    document_title: str     # e.g. "Cancellation Policy"
    version: str            # e.g. "2.3"
    category: str           # e.g. "cancellation" - derived from the filename, see _derive_category
    chunk_index: int        # 0-based position of this section within the document
    section_title: str      # e.g. "1. Purpose"
    content: str            # the section's full text (heading line excluded)


def _derive_category(source_file: str) -> str:
    """Derive a short, machine-readable category slug from a policy
    file's name.

    None of the 20 policy files have an explicit "Category:" metadata
    line - only Policy ID, Effective Date, Version, Owner, and Review
    Cycle. But every filename already encodes a clean category (e.g.
    "02_cancellation_policy.md" -> "cancellation"), so rather than ask
    Amogh to add a metadata line that would just duplicate the filename,
    this derives the category from the filename itself: strip the
    leading "NN_" number prefix and the trailing "_policy" / ".md".
    """
    name = source_file
    if name.endswith(".md"):
        name = name[: -len(".md")]
    # Strip a leading "NN_" numeric prefix (e.g. "02_").
    match = re.match(r"^\d+_(.+)$", name)
    if match:
        name = match.group(1)
    # Strip a trailing "_policy" suffix, if present.
    if name.endswith("_policy"):
        name = name[: -len("_policy")]
    return name


def _extract_policy_id(text: str, source_file: str) -> str:
    match = _POLICY_ID_PATTERN.search(text)
    if not match:
        raise ValueError(f"No '**Policy ID:**' line found in {source_file}")
    return match.group(1)


def _extract_version(text: str, source_file: str) -> str:
    match = _VERSION_PATTERN.search(text)
    if not match:
        raise ValueError(f"No '**Version:**' line found in {source_file}")
    return match.group(1)


def _extract_title(text: str, source_file: str) -> str:
    match = _TITLE_PATTERN.search(text)
    if not match:
        raise ValueError(f"No top-level '# Title' line found in {source_file}")
    return match.group(1).strip()


def chunk_policy_file(file_path: Path) -> list[PolicyChunkRecord]:
    """Parse one policy Markdown file into a list of section-level chunks.

    Raises:
        ValueError: if the file doesn't match the expected structure
            (missing Policy ID, Version, or title) - this is deliberate:
            a malformed policy file should stop ingestion loudly, not
            silently produce a chunk with missing metadata.
    """
    text = file_path.read_text(encoding="utf-8")
    source_file = file_path.name

    policy_id = _extract_policy_id(text, source_file)
    version = _extract_version(text, source_file)
    document_title = _extract_title(text, source_file)
    category = _derive_category(source_file)

    # Find every "## Section Name" header and its position in the text,
    # so we can slice out everything between one header and the next.
    headers = list(_SECTION_HEADER_PATTERN.finditer(text))
    if not headers:
        raise ValueError(f"No '##' section headers found in {source_file}")

    chunks: list[PolicyChunkRecord] = []
    for index, header_match in enumerate(headers):
        section_title = header_match.group(1).strip()
        content_start = header_match.end()
        content_end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        section_content = text[content_start:content_end].strip()

        chunks.append(
            PolicyChunkRecord(
                source_file=source_file,
                policy_id=policy_id,
                document_title=document_title,
                version=version,
                category=category,
                chunk_index=index,
                section_title=section_title,
                content=section_content,
            )
        )

    return chunks


def chunk_all_policies(policies_dir: Path) -> list[PolicyChunkRecord]:
    """Chunk every policy file in `policies_dir`.

    Skips `00_README_index.md` deliberately - it documents the corpus
    itself (chunking suggestions, file index, cross-references) and is
    not a real hotel policy; ingesting it as if it were guest-facing
    policy content would let the Compliance Agent retrieve and
    potentially cite meta-commentary about the corpus as if it were an
    actual hotel rule.
    """
    all_chunks: list[PolicyChunkRecord] = []

    policy_files = sorted(
        f for f in policies_dir.glob("*.md") if not f.name.startswith("00_README")
    )

    if not policy_files:
        raise ValueError(f"No policy .md files found in {policies_dir}")

    for file_path in policy_files:
        all_chunks.extend(chunk_policy_file(file_path))

    return all_chunks