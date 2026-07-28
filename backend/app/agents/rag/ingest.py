"""
ingest.py
----------
The real RAG ingestion pipeline: chunk -> embed -> write to the database.

Ties together chunker.py (splits policy Markdown files into sections),
embedder.py (turns those sections into Voyage AI vectors), and a
Postgres connection using the app_ingest role (least-privilege, scoped
to only policy_documents/policy_chunks - see db/roles.sql), to populate
those two tables with the real, embedded policy corpus.

This is the ONLY module in the RAG pipeline that writes to the database.
retriever.py (not yet built) will read from it.

IDEMPOTENCY
------------
Running this script twice must not duplicate rows. This is achieved
entirely through UPSERTs (`INSERT ... ON CONFLICT DO UPDATE`), not
delete-then-insert:
  - `policy_documents` upserts on the unique `policy_id` column.
  - `policy_chunks` upserts on the unique `(document_id, chunk_index)`
    constraint already defined in schema.sql.
This deliberately avoids using DELETE at all - `app_ingest` (per
db/roles.sql) is only granted SELECT/INSERT/UPDATE, matching this
project's consistent least-privilege philosophy (the same reasoning
behind `app_writer` having no DELETE grant: a cancellation is a status
change, not a row delete). This was confirmed the hard way: an earlier
version of this module used DELETE to clear a document's old chunks
before re-inserting, and failed with `InsufficientPrivilege` against the
real database - not a bug to work around by widening the role's grants,
but a signal that the DELETE-based design didn't fit this project's
security model.

KNOWN LIMITATION: if a section is entirely REMOVED from a policy's
source Markdown file (not just edited), the old chunk row for that
now-gone section_index is NOT automatically cleaned up by an UPSERT -
it would need an explicit DELETE, which this role cannot perform. For
the current corpus (sections are edited, not typically removed), this is
an acceptable gap; if it becomes a real problem, the fix is a
periodic admin-run cleanup script using a role that IS granted DELETE,
not widening app_ingest's own permissions.

TRANSACTION SAFETY
--------------------
The entire ingestion run is one transaction: if embedding or inserting
any single document fails partway through, everything is rolled back -
we never want a database left in a state where some policies are fully
ingested and others are half-written.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extensions import connection as PGConnection
from psycopg2.extras import execute_values

from app.agents.rag.chunker import PolicyChunkRecord, chunk_all_policies
from app.agents.rag.embedder import EmbeddedChunk, embed_chunks

logger = logging.getLogger(__name__)


class IngestionError(Exception):
    """Raised for any failure specific to the ingestion pipeline itself
    (missing connection string, a database error, etc.) - distinct from
    ChunkingError-style ValueErrors raised by chunker.py or EmbeddingError
    raised by embedder.py, which propagate through unchanged."""


def get_ingest_connection(database_url: str | None = None) -> PGConnection:
    """Open a connection using the app_ingest role.

    Args:
        database_url: an explicit connection string, or None to read
            DATABASE_URL_INGEST from the environment (the normal path -
            see .env.example).
    """
    url = database_url or os.getenv("DATABASE_URL_INGEST")
    if not url:
        raise IngestionError(
            "DATABASE_URL_INGEST is not set. Check your .env file - it should "
            "look like: postgresql://app_ingest:<password>@localhost:5432/hotel"
        )
    try:
        return psycopg2.connect(url)
    except psycopg2.OperationalError as exc:
        raise IngestionError(f"Could not connect to the database: {exc}") from exc


def _upsert_policy_document(
    conn: PGConnection, policy_id: str, title: str, category: str, version: str
) -> str:
    """Insert a policy_documents row, or update it in place if policy_id
    already exists (idempotent re-ingestion). Returns the row's `id`
    (uuid, as a string)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            insert into policy_documents (policy_id, title, category, version)
            values (%s, %s, %s, %s)
            on conflict (policy_id) do update
                set title = excluded.title,
                    category = excluded.category,
                    version = excluded.version
            returning id;
            """,
            (policy_id, title, category, version),
        )
        row = cur.fetchone()
        return str(row[0])


def _vector_literal(embedding: list[float]) -> str:
    """Format a Python float list as pgvector's text input format, e.g.
    "[0.1,0.2,0.3]" - pgvector's `vector` type accepts this bracketed,
    comma-separated string form and casts it automatically on insert
    into a `vector(N)` column."""
    return "[" + ",".join(repr(value) for value in embedding) + "]"


def _upsert_chunks(conn: PGConnection, document_id: str, embedded_chunks: list[EmbeddedChunk]) -> None:
    """Insert a document's chunks, or update them in place if a row
    already exists for the same (document_id, chunk_index) - see module
    docstring, IDEMPOTENCY, for why this is an UPSERT rather than a
    delete-then-insert."""
    with conn.cursor() as cur:
        rows = [
            (
                document_id,
                ec.chunk.chunk_index,
                ec.chunk.content,
                ec.chunk.category,
                _vector_literal(ec.embedding),
            )
            for ec in embedded_chunks
        ]
        execute_values(
            cur,
            """
            insert into policy_chunks (document_id, chunk_index, content, category, embedding)
            values %s
            on conflict (document_id, chunk_index) do update
                set content = excluded.content,
                    category = excluded.category,
                    embedding = excluded.embedding;
            """,
            rows,
        )


def _group_by_policy(chunks: list[PolicyChunkRecord]) -> dict[str, list[PolicyChunkRecord]]:
    """Group flat chunk list back into one list per policy_id (one
    policy_documents row per source file, many policy_chunks rows each)."""
    grouped: dict[str, list[PolicyChunkRecord]] = {}
    for chunk in chunks:
        grouped.setdefault(chunk.policy_id, []).append(chunk)
    return grouped


def ingest_all_policies(
    policies_dir: Path,
    conn: PGConnection | None = None,
    voyage_client: Any = None,
) -> dict[str, int]:
    """Run the full ingestion pipeline: chunk -> embed -> write to DB.

    Args:
        policies_dir: directory containing the policy .md files (chunker.py's input).
        conn: an existing database connection, or None to open one from
            DATABASE_URL_INGEST. IMPORTANT: when a connection is
            injected, this function does NOT commit or roll back on
            success - the caller owns that connection's transaction and
            decides when to commit/rollback (this is what lets
            tests/test_ingest.py wrap each test in a transaction that is
            always rolled back, regardless of whether the ingestion
            itself "succeeded"). When conn is None (the normal CLI/production
            path), this function opens its own connection and commits on
            success / rolls back on failure, since there is no other
            caller to hand that responsibility to.
        voyage_client: passed through to embed_chunks() - None uses a
            real Voyage AI client built from VOYAGE_API_KEY.

    Returns:
        {"documents": N, "chunks": M} - counts of what was written.

    On any failure, the current transaction is rolled back before the
    exception propagates - see module docstring, TRANSACTION SAFETY. This
    happens regardless of who owns the connection, since leaving a failed
    transaction dangling (neither committed nor rolled back) would block
    any further use of that connection.
    """
    should_close = conn is None
    connection = conn or get_ingest_connection()

    try:
        all_chunks = chunk_all_policies(policies_dir)
        grouped = _group_by_policy(all_chunks)
        logger.info(
            "Chunked %d policy documents into %d total sections",
            len(grouped), len(all_chunks),
        )

        total_documents = 0
        total_chunks = 0

        for policy_id, chunks in grouped.items():
            first_chunk = chunks[0]
            logger.info("Ingesting %s (%s)", policy_id, first_chunk.document_title)

            document_id = _upsert_policy_document(
                connection,
                policy_id=policy_id,
                title=first_chunk.document_title,
                category=first_chunk.category,
                version=first_chunk.version,
            )

            embedded_chunks = embed_chunks(chunks, client=voyage_client)
            _upsert_chunks(connection, document_id, embedded_chunks)

            total_documents += 1
            total_chunks += len(embedded_chunks)

        if should_close:
            # Only commit when we opened the connection ourselves - if a
            # connection was injected (e.g. by a test), the caller
            # decides whether/when to commit.
            connection.commit()
        logger.info(
            "Ingestion complete: %d documents, %d chunks", total_documents, total_chunks
        )
        return {"documents": total_documents, "chunks": total_chunks}

    except Exception:
        connection.rollback()
        logger.exception("Ingestion failed - transaction rolled back, no partial writes.")
        raise
    finally:
        if should_close:
            connection.close()


def main() -> int:
    """CLI entrypoint: `python -m app.agents.rag.ingest` from backend/."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parents[4] / ".env")

    policies_dir = Path(__file__).parents[4] / "data" / "policies"

    try:
        summary = ingest_all_policies(policies_dir)
    except (IngestionError, ValueError) as exc:
        logger.error("Ingestion failed: %s", exc)
        return 1

    logger.info("Done: %s", summary)
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())