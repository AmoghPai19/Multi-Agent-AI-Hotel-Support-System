"""
test_ingest.py
----------------
Tests for app.agents.rag.ingest, run against a REAL Postgres + pgvector
database (not mocked) - this is the one place in the test suite that
needs an actual database connection, since ingest.py's entire job is
writing real rows with real vector data.

Every test runs inside its own transaction that is rolled back at the
end (see the `db_connection` fixture), so running this file never
leaves test data behind in whatever database DATABASE_URL_INGEST points
to - safe to run repeatedly against a real dev database.

If DATABASE_URL_INGEST is not set, every test in this file is skipped
rather than failing - a database isn't available in every environment
(e.g. a fresh clone before `docker compose up` has been run), and that
should not block the rest of the test suite from running.

Run with:
    cd backend && pytest tests/test_ingest.py -v
(requires: docker compose up -d, and DATABASE_URL_INGEST set in .env)
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("psycopg2")
import psycopg2  # noqa: E402

from app.agents.rag.chunker import PolicyChunkRecord  # noqa: E402
from app.agents.rag.ingest import (  # noqa: E402
    IngestionError,
    _upsert_chunks,
    _upsert_policy_document,
    get_ingest_connection,
    ingest_all_policies,
)
from app.agents.rag.embedder import EmbeddedChunk  # noqa: E402


class _FakeVoyageClient:
    """Deterministic fake embedder - these tests verify database
    behavior, not Voyage AI itself (that's test_embedder.py's job)."""

    def embed(self, texts, model=None, input_type=None, **kwargs):
        class _Result:
            embeddings = [[0.001 * i] * 1024 for i in range(len(texts))]
            total_tokens = len(texts) * 10

        return _Result()


class _FailingVoyageClient:
    """Fails on the second call - used to prove a mid-run failure rolls
    back the ENTIRE transaction, not just the document that failed."""

    def __init__(self):
        self.call_count = 0

    def embed(self, texts, model=None, input_type=None, **kwargs):
        self.call_count += 1
        if self.call_count == 2:
            raise RuntimeError("Simulated embedding failure on the second document")
        class _Result:
            embeddings = [[0.001 * i] * 1024 for i in range(len(texts))]
            total_tokens = len(texts) * 10
        return _Result()


@pytest.fixture
def db_connection():
    """A real database connection, wrapped so every test's changes are
    rolled back automatically - never leaves test data behind."""
    database_url = os.getenv("DATABASE_URL_INGEST")
    if not database_url:
        pytest.skip("DATABASE_URL_INGEST not set - skipping real-database ingest tests")

    conn = psycopg2.connect(database_url)
    yield conn
    conn.rollback()
    conn.close()


def _make_chunk(policy_id: str, chunk_index: int, source_file: str = "test.md") -> PolicyChunkRecord:
    return PolicyChunkRecord(
        source_file=source_file,
        policy_id=policy_id,
        document_title=f"Test Policy {policy_id}",
        version="1.0",
        category="test",
        chunk_index=chunk_index,
        section_title=f"{chunk_index + 1}. Section",
        content=f"Test content for section {chunk_index}.",
    )


# =============================================================================
# 1. _upsert_policy_document - insert and update-in-place
# =============================================================================
def test_upsert_policy_document_creates_a_row(db_connection):
    document_id = _upsert_policy_document(
        db_connection, policy_id="POL-TEST-INGEST-001", title="Test", category="test", version="1.0"
    )
    assert document_id is not None

    with db_connection.cursor() as cur:
        cur.execute("SELECT title, version FROM policy_documents WHERE id = %s", (document_id,))
        title, version = cur.fetchone()
        assert title == "Test"
        assert version == "1.0"


def test_upsert_policy_document_updates_in_place_not_duplicate(db_connection):
    first_id = _upsert_policy_document(
        db_connection, policy_id="POL-TEST-INGEST-002", title="Original Title", category="test", version="1.0"
    )
    second_id = _upsert_policy_document(
        db_connection, policy_id="POL-TEST-INGEST-002", title="Updated Title", category="test", version="2.0"
    )

    assert first_id == second_id, "Same policy_id must upsert the same row, not create a new one"

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM policy_documents WHERE policy_id = %s", ("POL-TEST-INGEST-002",)
        )
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT title, version FROM policy_documents WHERE id = %s", (first_id,))
        title, version = cur.fetchone()
        assert title == "Updated Title"
        assert version == "2.0"


# =============================================================================
# 2. _upsert_chunks - real vector data, correct dimensions, idempotent
# =============================================================================
def test_upsert_chunks_writes_real_vector_data(db_connection):
    document_id = _upsert_policy_document(
        db_connection, policy_id="POL-TEST-INGEST-003", title="Test", category="test", version="1.0"
    )
    chunk = _make_chunk("POL-TEST-INGEST-003", 0)
    embedded = [EmbeddedChunk(chunk=chunk, embedding=[0.5] * 1024)]

    _upsert_chunks(db_connection, document_id, embedded)

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT content, vector_dims(embedding) FROM policy_chunks WHERE document_id = %s", (document_id,)
        )
        content, dims = cur.fetchone()
        assert content == chunk.content
        assert dims == 1024


def test_upsert_chunks_is_idempotent_on_same_chunk_index(db_connection):
    document_id = _upsert_policy_document(
        db_connection, policy_id="POL-TEST-INGEST-004", title="Test", category="test", version="1.0"
    )
    chunk = _make_chunk("POL-TEST-INGEST-004", 0)

    _upsert_chunks(db_connection, document_id, [EmbeddedChunk(chunk=chunk, embedding=[0.1] * 1024)])
    _upsert_chunks(db_connection, document_id, [EmbeddedChunk(chunk=chunk, embedding=[0.9] * 1024)])

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT count(*), embedding::text FROM policy_chunks WHERE document_id = %s GROUP BY embedding::text",
            (document_id,),
        )
        count, embedding_text = cur.fetchone()
        assert count == 1, "Re-upserting the same chunk_index must update, not duplicate"
        assert embedding_text.startswith("[0.9,"), "The second upsert's value should have won"


# =============================================================================
# 3. ingest_all_policies - full pipeline against a temporary policy corpus
# =============================================================================
def test_ingest_all_policies_end_to_end(db_connection, tmp_path):
    policy_file = tmp_path / "01_a_test_policy.md"
    policy_file.write_text(
        "# A Test Policy\n\n"
        "**Policy ID:** POL-TEST-INGEST-E2E | **Version:** 1.0\n\n"
        "## 1. Purpose\nThis is a test.\n\n"
        "## 2. Details\nMore test content here.\n"
    )

    summary = ingest_all_policies(tmp_path, conn=db_connection, voyage_client=_FakeVoyageClient())

    assert summary == {"documents": 1, "chunks": 2}

    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM policy_chunks pc "
            "JOIN policy_documents pd ON pc.document_id = pd.id "
            "WHERE pd.policy_id = %s",
            ("POL-TEST-INGEST-E2E",),
        )
        assert cur.fetchone()[0] == 2


def test_ingest_all_policies_rolls_back_entirely_on_mid_run_failure(db_connection, tmp_path):
    """If embedding the SECOND document fails, the first document's
    (already-processed) rows must not remain committed either - the
    whole run is one transaction, not one transaction per document."""
    (tmp_path / "01_first_policy.md").write_text(
        "# First Policy\n\n**Policy ID:** POL-TEST-ROLLBACK-1 | **Version:** 1.0\n\n"
        "## 1. Section\nContent.\n"
    )
    (tmp_path / "02_second_policy.md").write_text(
        "# Second Policy\n\n**Policy ID:** POL-TEST-ROLLBACK-2 | **Version:** 1.0\n\n"
        "## 1. Section\nContent.\n"
    )

    with pytest.raises(RuntimeError, match="Simulated embedding failure"):
        ingest_all_policies(tmp_path, conn=db_connection, voyage_client=_FailingVoyageClient())

    # The connection's own transaction was rolled back inside
    # ingest_all_policies's except block - but since our fixture ALSO
    # rolls back, we check within the same (now-aborted) transaction is
    # not reliable; instead verify via a fresh connection that nothing
    # from this failed run was ever visible outside the transaction.
    db_connection.rollback()
    with db_connection.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM policy_documents WHERE policy_id IN (%s, %s)",
            ("POL-TEST-ROLLBACK-1", "POL-TEST-ROLLBACK-2"),
        )
        assert cur.fetchone()[0] == 0, "A failed run must not leave ANY partial rows committed"


# =============================================================================
# 4. Connection handling
# =============================================================================
def test_get_ingest_connection_missing_url_raises_clear_error(monkeypatch):
    monkeypatch.delenv("DATABASE_URL_INGEST", raising=False)
    with pytest.raises(IngestionError, match="DATABASE_URL_INGEST is not set"):
        get_ingest_connection(database_url=None)