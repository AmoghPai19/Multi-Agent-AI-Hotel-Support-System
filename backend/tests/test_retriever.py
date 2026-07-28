"""
test_retriever.py
--------------------
Tests for app.agents.rag.retriever, run against a REAL Postgres +
pgvector database - proving the actual SQL similarity search, join, and
ordering logic are correct, not just that the code reads plausibly.

Uses controlled, hand-crafted embedding vectors (not real Voyage AI
calls) so the tests can assert on EXACT expected ordering: a query
vector identical to one chunk's embedding must rank that chunk first
with similarity ~1.0, regardless of what real semantic content means -
this isolates "is the SQL/ranking logic correct" from "does Voyage AI
produce good embeddings" (the latter is scripts/verify_voyage_key.py's
job, not this file's).

Every test runs inside its own transaction that is rolled back
afterward - see the `db_connection` fixture - so running this file never
leaves test data behind in whatever database DATABASE_URL_RO points to.

If DATABASE_URL_RO is not set, every test in this file is skipped.

Run with:
    cd backend && pytest tests/test_retriever.py -v
(requires: docker compose up -d, and DATABASE_URL_RO + DATABASE_URL_INGEST set in .env)
"""

from __future__ import annotations

import os

import pytest

pytest.importorskip("psycopg2")
import psycopg2  # noqa: E402

from app.agents.rag.retriever import RetrievalError, get_readonly_connection, retrieve_top_k  # noqa: E402


class _FixedVectorVoyageClient:
    """A fake Voyage client that always returns the same, caller-specified
    vector - lets tests control exactly what "the embedded query" is,
    so similarity results are deterministic and assertable."""

    def __init__(self, vector: list[float]):
        self.vector = vector

    def embed(self, texts, model=None, input_type=None, **kwargs):
        class _Result:
            embeddings = None
            total_tokens = 5

        result = _Result()
        result.embeddings = [self.vector for _ in texts]
        return result


def _unit_vector(dimension: int, size: int = 1024) -> list[float]:
    """A vector with a 1.0 in position `dimension` and 0.0 elsewhere -
    lets tests construct exactly-known cosine similarities/distances."""
    vector = [0.0] * size
    vector[dimension] = 1.0
    return vector


@pytest.fixture
def db_connection():
    """A real database connection (via app_ingest, since these tests need
    to insert their own controlled test rows) wrapped so every test's
    changes are rolled back automatically."""
    database_url = os.getenv("DATABASE_URL_INGEST")
    if not database_url:
        pytest.skip("DATABASE_URL_INGEST not set - skipping real-database retriever tests")

    conn = psycopg2.connect(database_url)
    yield conn
    conn.rollback()
    conn.close()


def _insert_test_chunk(conn, policy_id: str, content: str, embedding: list[float]) -> None:
    vector_literal = "[" + ",".join(repr(v) for v in embedding) + "]"
    with conn.cursor() as cur:
        cur.execute(
            "insert into policy_documents (policy_id, title, category, version) "
            "values (%s, %s, 'test', '1.0') returning id",
            (policy_id, f"Test Policy {policy_id}"),
        )
        document_id = cur.fetchone()[0]
        cur.execute(
            "insert into policy_chunks (document_id, chunk_index, content, category, embedding) "
            "values (%s, 0, %s, 'test', %s::vector)",
            (document_id, content, vector_literal),
        )


# =============================================================================
# 1. Correct similarity ordering (the core guarantee of this module)
# =============================================================================
def test_identical_vector_ranks_first_with_similarity_near_one(db_connection):
    _insert_test_chunk(db_connection, "POL-RETR-CLOSE", "Close content.", _unit_vector(0))
    _insert_test_chunk(db_connection, "POL-RETR-FAR", "Far content.", _unit_vector(1))

    query_vector = _unit_vector(0)  # identical to POL-RETR-CLOSE's embedding
    results = retrieve_top_k(
        "irrelevant query text", conn=db_connection,
        voyage_client=_FixedVectorVoyageClient(query_vector), top_k=2,
    )

    assert len(results) == 2
    assert results[0].policy_id == "POL-RETR-CLOSE"
    assert results[0].similarity > results[1].similarity
    assert abs(results[0].similarity - 1.0) < 0.001


def test_orthogonal_vector_has_similarity_near_zero(db_connection):
    """Uses a wide top_k and searches for the specific test row by
    policy_id, rather than assuming it's the only (or top) result - a
    real database may already contain other chunks whose embeddings
    happen to score higher against an arbitrary query vector, and this
    test should hold regardless of what else is in the table."""
    _insert_test_chunk(db_connection, "POL-RETR-ORTHO", "Orthogonal content.", _unit_vector(5))

    query_vector = _unit_vector(10)  # orthogonal to position 5
    results = retrieve_top_k(
        "irrelevant query text", conn=db_connection,
        voyage_client=_FixedVectorVoyageClient(query_vector), top_k=1000,
    )

    matching = [r for r in results if r.policy_id == "POL-RETR-ORTHO"]
    assert matching, "The inserted test chunk should be findable at a wide enough top_k"
    assert abs(matching[0].similarity - 0.0) < 0.001


# =============================================================================
# 2. top_k is honored, results include the right fields
# =============================================================================
def test_top_k_limits_result_count(db_connection):
    for i in range(5):
        _insert_test_chunk(db_connection, f"POL-RETR-K{i}", f"Content {i}.", _unit_vector(i))

    results = retrieve_top_k(
        "query", conn=db_connection,
        voyage_client=_FixedVectorVoyageClient(_unit_vector(0)), top_k=3,
    )
    assert len(results) == 3


def test_result_includes_policy_id_title_category_content(db_connection):
    _insert_test_chunk(db_connection, "POL-RETR-FIELDS", "Specific content here.", _unit_vector(0))

    results = retrieve_top_k(
        "query", conn=db_connection,
        voyage_client=_FixedVectorVoyageClient(_unit_vector(0)), top_k=1,
    )

    assert results[0].policy_id == "POL-RETR-FIELDS"
    assert results[0].document_title == "Test Policy POL-RETR-FIELDS"
    assert results[0].category == "test"
    assert results[0].content == "Specific content here."


# =============================================================================
# 3. Least-privilege: app_readonly can read but genuinely cannot write
# =============================================================================
def test_app_readonly_role_cannot_write_to_policy_chunks():
    readonly_url = os.getenv("DATABASE_URL_RO")
    if not readonly_url:
        pytest.skip("DATABASE_URL_RO not set - skipping least-privilege check")

    conn = get_readonly_connection(readonly_url)
    try:
        with pytest.raises(psycopg2.errors.InsufficientPrivilege):
            with conn.cursor() as cur:
                cur.execute("update policy_chunks set content = 'unauthorized' where chunk_index = 0")
    finally:
        conn.rollback()
        conn.close()


# =============================================================================
# 4. Connection handling
# =============================================================================
def test_get_readonly_connection_missing_url_raises_clear_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL_RO", raising=False)
    with pytest.raises(RetrievalError, match="DATABASE_URL_RO is not set"):
        get_readonly_connection(database_url=None)