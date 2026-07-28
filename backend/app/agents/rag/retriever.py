"""
retriever.py
--------------
Real pgvector similarity search over the ingested policy corpus.

Given a guest query, embeds it (input_type="query" - see embedder.py's
`embed_query`) and returns the most semantically similar sections from
`policy_chunks`, using pgvector's cosine-distance operator (`<=>`).

This module ONLY reads from the database - it uses the `app_readonly`
role (least privilege: retrieval never needs to write anything), not
`app_ingest` (write-only, scoped to ingestion) or `app_writer` (no access
to policy_* tables at all - see db/roles.sql).

NOT YET WIRED INTO compliance.py - see "KNOWN GAP" below before doing so.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import psycopg2
from langsmith import traceable
from psycopg2.extensions import connection as PGConnection

from app.agents.rag.embedder import embed_query


class RetrievalError(Exception):
    """Raised for any failure specific to real-database retrieval (missing
    connection string, a database error, etc.)."""


@dataclass(frozen=True)
class RetrievedChunk:
    """One real policy section, ranked by semantic similarity to a query."""

    policy_id: str          # e.g. "POL-CXL-002"
    document_title: str     # e.g. "Cancellation Policy"
    category: str           # e.g. "cancellation"
    content: str            # the actual policy section text
    similarity: float       # 0.0-1.0, higher = more similar (1 - cosine distance)


def get_readonly_connection(database_url: str | None = None) -> PGConnection:
    """Open a connection using the app_readonly role.

    Args:
        database_url: an explicit connection string, or None to read
            DATABASE_URL_RO from the environment (see .env.example).
    """
    url = database_url or os.getenv("DATABASE_URL_RO")
    if not url:
        raise RetrievalError(
            "DATABASE_URL_RO is not set. Check your .env file - it should "
            "look like: postgresql://app_readonly:<password>@localhost:5432/hotel"
        )
    try:
        return psycopg2.connect(url)
    except psycopg2.OperationalError as exc:
        raise RetrievalError(f"Could not connect to the database: {exc}") from exc


def _vector_literal(embedding: list[float]) -> str:
    """Same pgvector text format used by ingest.py - "[0.1,0.2,...]"."""
    return "[" + ",".join(repr(value) for value in embedding) + "]"


@traceable(name="retrieve_top_k", run_type="retriever")
def retrieve_top_k(
    query: str,
    conn: PGConnection | None = None,
    voyage_client=None,
    top_k: int = 3,
) -> list[RetrievedChunk]:
    """Retrieve the top-k most semantically similar policy sections to `query`.

    Args:
        query: the guest's question / the Compliance Agent's search text.
        conn: an existing database connection, or None to open one via
            get_readonly_connection(). Accepting an injected connection
            is what makes this testable against a real temporary schema.
        voyage_client: passed through to embed_query() - None uses a real
            Voyage AI client built from VOYAGE_API_KEY.
        top_k: how many results to return, ranked by similarity descending.

    Returns:
        Up to `top_k` RetrievedChunk objects, most similar first. May
        return fewer than top_k (or an empty list) if the corpus is small
        or nothing is meaningfully similar - this is expected, not an error.
    """
    should_close = conn is None
    connection = conn or get_readonly_connection()

    try:
        query_vector = embed_query(query, client=voyage_client)
        vector_literal = _vector_literal(query_vector)

        with connection.cursor() as cur:
            cur.execute(
                """
                select pd.policy_id, pd.title, pc.category, pc.content,
                       1 - (pc.embedding <=> %s::vector) as similarity
                from policy_chunks pc
                join policy_documents pd on pd.id = pc.document_id
                where pc.embedding is not null
                order by pc.embedding <=> %s::vector
                limit %s;
                """,
                (vector_literal, vector_literal, top_k),
            )
            rows = cur.fetchall()

        return [
            RetrievedChunk(
                policy_id=row[0],
                document_title=row[1],
                category=row[2],
                content=row[3],
                similarity=float(row[4]),
            )
            for row in rows
        ]
    finally:
        if should_close:
            connection.close()


# =============================================================================
# KNOWN GAP - read before wiring this into compliance.py
# =============================================================================
# compliance.py's current `check_for_policy_violation()` detects a
# contradiction by checking a draft response against a fixed list of
# `contradiction_phrases` hand-written per fake policy (e.g. "pets are
# welcome" for the fake pet policy). Real policy_chunks rows ingested by
# ingest.py have NO such field - just raw section `content` text. A fixed
# phrase list cannot meaningfully check arbitrary real policy text for
# contradiction; that requires actual reasoning (a real Claude Sonnet
# call), which is a separate, larger piece of work than this retriever.
#
# This module is complete and independently useful (it correctly finds
# the most relevant real policy sections for a query), but swapping
# compliance.py's fake `retrieve_relevant_policies` for this module's
# `retrieve_top_k` should happen TOGETHER WITH replacing
# `check_for_policy_violation` with a real LLM call - not before, since
# doing so alone would leave the Compliance Agent retrieving real
# content but still checking it against fake, hand-written phrases that
# don't correspond to what was actually retrieved.