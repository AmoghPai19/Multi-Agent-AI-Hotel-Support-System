"""
test_embedder.py
------------------
Tests for app.agents.rag.embedder.

These tests use a FAKE Voyage client (a small stand-in class matching
the real voyageai.Client's .embed() interface) rather than calling the
real API - this keeps the test suite fast, free, and runnable without
network access or a real VOYAGE_API_KEY, while still genuinely
exercising embed_chunks()'s and embed_query()'s actual logic (batching,
error handling, dimension checking) rather than mocking those away too.

scripts/verify_voyage_key.py remains the one place that calls the REAL
API - these tests deliberately do not duplicate that.

Run with:
    cd backend && pytest tests/test_embedder.py -v
"""

from __future__ import annotations

import pytest
from voyageai.error import AuthenticationError, RateLimitError

from app.agents.rag.chunker import PolicyChunkRecord
from app.agents.rag.embedder import (
    EmbeddingError,
    build_embedding_text,
    embed_chunks,
    embed_query,
)


def _make_chunk(index: int, section_title: str = "1. Section") -> PolicyChunkRecord:
    return PolicyChunkRecord(
        source_file="test_policy.md",
        policy_id="POL-TEST-001",
        document_title="Test Policy",
        version="1.0",
        category="test",
        chunk_index=index,
        section_title=section_title,
        content=f"Content for chunk {index}.",
    )


class _FakeEmbeddingsResult:
    """Mimics voyageai.object.embeddings.EmbeddingsObject's shape."""

    def __init__(self, embeddings: list[list[float]]):
        self.embeddings = embeddings
        self.total_tokens = len(embeddings) * 10


class _FakeVoyageClient:
    """A fake client matching the real voyageai.Client's .embed() signature.

    Always returns a deterministic 1024-dimension vector per text (just
    `[float(i)] * 1024`, unique per call index) so tests can assert on
    exact values without needing a real embedding model.
    """

    def __init__(self, dimension: int = 1024, raise_on_call: Exception | None = None):
        self.dimension = dimension
        self.raise_on_call = raise_on_call
        self.calls: list[dict] = []

    def embed(self, texts, model=None, input_type=None, **kwargs):
        self.calls.append({"texts": texts, "model": model, "input_type": input_type})
        if self.raise_on_call is not None:
            raise self.raise_on_call
        return _FakeEmbeddingsResult([[float(i)] * self.dimension for i in range(len(texts))])


# =============================================================================
# 1. build_embedding_text - includes context, not just raw content
# =============================================================================
def test_build_embedding_text_includes_title_and_section():
    chunk = _make_chunk(0, section_title="3. How Cancellations Are Processed")
    text = build_embedding_text(chunk)
    assert "Test Policy" in text
    assert "3. How Cancellations Are Processed" in text
    assert "Content for chunk 0." in text


# =============================================================================
# 2. embed_chunks - batching, ordering, input_type correctness
# =============================================================================
def test_embed_chunks_returns_one_embedded_chunk_per_input_chunk():
    chunks = [_make_chunk(i) for i in range(5)]
    fake_client = _FakeVoyageClient()

    result = embed_chunks(chunks, client=fake_client, batch_size=100)

    assert len(result) == 5
    for original, embedded in zip(chunks, result):
        assert embedded.chunk == original
        assert len(embedded.embedding) == 1024


def test_embed_chunks_splits_into_correct_number_of_batches():
    chunks = [_make_chunk(i) for i in range(250)]
    fake_client = _FakeVoyageClient()

    result = embed_chunks(chunks, client=fake_client, batch_size=100)

    assert len(result) == 250
    # 250 chunks at batch_size=100 -> 3 calls (100, 100, 50)
    assert len(fake_client.calls) == 3
    assert [len(call["texts"]) for call in fake_client.calls] == [100, 100, 50]


def test_embed_chunks_uses_document_input_type():
    """Critical: ingestion must use input_type='document', never 'query' -
    using the wrong mode measurably hurts retrieval quality."""
    chunks = [_make_chunk(0)]
    fake_client = _FakeVoyageClient()

    embed_chunks(chunks, client=fake_client)

    assert fake_client.calls[0]["input_type"] == "document"


def test_embed_chunks_uses_the_correct_model_name():
    chunks = [_make_chunk(0)]
    fake_client = _FakeVoyageClient()

    embed_chunks(chunks, client=fake_client)

    assert fake_client.calls[0]["model"] == "voyage-4-lite"


def test_embed_chunks_on_empty_list_makes_no_api_call():
    fake_client = _FakeVoyageClient()
    result = embed_chunks([], client=fake_client)
    assert result == []
    assert fake_client.calls == []


# =============================================================================
# 3. embed_chunks - error handling (each real Voyage error type covered)
# =============================================================================
def test_embed_chunks_wraps_authentication_error():
    chunks = [_make_chunk(0)]
    fake_client = _FakeVoyageClient(raise_on_call=AuthenticationError("bad key"))

    with pytest.raises(EmbeddingError, match="rejected the API key"):
        embed_chunks(chunks, client=fake_client)


def test_embed_chunks_wraps_rate_limit_error():
    chunks = [_make_chunk(0)]
    fake_client = _FakeVoyageClient(raise_on_call=RateLimitError("slow down"))

    with pytest.raises(EmbeddingError, match="rate limit"):
        embed_chunks(chunks, client=fake_client)


def test_embed_chunks_rejects_wrong_dimension():
    """If Voyage ever returns a vector of the wrong size (e.g. a model
    name typo slipped through), embedding must fail loudly rather than
    silently writing a mismatched vector into pgvector."""
    chunks = [_make_chunk(0)]
    fake_client = _FakeVoyageClient(dimension=512)  # wrong on purpose

    with pytest.raises(EmbeddingError, match="expected 1024"):
        embed_chunks(chunks, client=fake_client)


def test_embed_chunks_missing_api_key_raises_clear_error(monkeypatch):
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    with pytest.raises(EmbeddingError, match="VOYAGE_API_KEY is not set"):
        embed_chunks([_make_chunk(0)], client=None)


# =============================================================================
# 4. embed_query - the search-time counterpart, uses input_type="query"
# =============================================================================
def test_embed_query_uses_query_input_type_not_document():
    fake_client = _FakeVoyageClient()
    embed_query("What is the cancellation policy?", client=fake_client)
    assert fake_client.calls[0]["input_type"] == "query"


def test_embed_query_returns_correct_dimension():
    fake_client = _FakeVoyageClient()
    vector = embed_query("Can I bring my dog?", client=fake_client)
    assert len(vector) == 1024


def test_embed_query_rejects_wrong_dimension():
    fake_client = _FakeVoyageClient(dimension=256)
    with pytest.raises(EmbeddingError, match="expected 1024"):
        embed_query("test", client=fake_client)