"""
embedder.py
------------
Turns policy chunks (produced by chunker.py) into embedding vectors,
using Voyage AI - the same API `scripts/verify_voyage_key.py` already
proved works against your real account.

This module does NOT touch the database and does NOT read policy files
directly - it only knows how to turn text into vectors. `ingest.py` is
the one that calls `chunk_all_policies()` (chunker.py), then
`embed_chunks()` (this module), then writes the results into
`policy_documents` / `policy_chunks`.

WHY "input_type" MATTERS (asymmetric embeddings)
--------------------------------------------------
Voyage AI's models support two distinct embedding modes for the same
underlying model:
  - input_type="document" - used when embedding the policy TEXT ITSELF,
    at ingestion time (this module).
  - input_type="query"    - used when embedding a GUEST'S QUESTION, at
    search time (retriever.py, not yet built).
Using the wrong one for either side measurably hurts retrieval quality -
Voyage's models are specifically trained to produce better matches when
each side uses its correct mode. This module only ever uses "document";
retriever.py will be the only place "query" is used.

MODEL CONSISTENCY
------------------
Every embedding in this project must come from the exact same model
(`voyage-4-lite`) and produce the exact same dimension (1024, matching
schema.sql's `vector(1024)` column - already verified live by
scripts/verify_voyage_key.py). Mixing models or dimensions within the
same `policy_chunks` table would make similarity search meaningless
(comparing vectors from different embedding spaces).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import voyageai
from voyageai.error import (
    APIConnectionError,
    AuthenticationError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)

from app.agents.rag.chunker import PolicyChunkRecord

logger = logging.getLogger(__name__)

# Must match the model verified live in scripts/verify_voyage_key.py, and
# the vector(1024) column in schema.sql.
EMBEDDING_MODEL = "voyage-4-lite"
EXPECTED_DIMENSION = 1024

# Voyage AI accepts many texts per request, but a very large batch risks
# hitting the model's total-token-per-request ceiling and makes a single
# failure more expensive to retry. 100 is a conservative, safe batch size
# for a corpus this size (117 chunks total = 2 batches, not 117 calls).
_DEFAULT_BATCH_SIZE = 100


class EmbeddingError(Exception):
    """Raised when embedding a batch fails for a reason worth surfacing
    distinctly from a generic exception (auth, rate limit, connectivity,
    or an unexpected dimension mismatch)."""


@dataclass(frozen=True)
class EmbeddedChunk:
    """A policy chunk paired with its embedding vector, ready for
    `ingest.py` to write into `policy_chunks.embedding`."""

    chunk: PolicyChunkRecord
    embedding: list[float]


def create_voyage_client() -> voyageai.Client:
    """Construct a Voyage AI client from the VOYAGE_API_KEY environment
    variable. Raises a clear error immediately if the key is missing,
    rather than letting a confusing failure surface deep inside a batch
    embedding call."""
    api_key = os.getenv("VOYAGE_API_KEY")
    if not api_key:
        raise EmbeddingError(
            "VOYAGE_API_KEY is not set. Check your .env file - see "
            "scripts/verify_voyage_key.py for how to confirm it's working."
        )
    return voyageai.Client(api_key=api_key)


def build_embedding_text(chunk: PolicyChunkRecord) -> str:
    """Build the text actually sent to the embedding model for one chunk.

    Prepending the document title and section title to the raw section
    content (rather than embedding `chunk.content` alone) gives the
    embedding model context it would otherwise lose - a section titled
    "3. How Cancellations Are Processed" reads very differently once you
    know it's from the "Cancellation Policy" document. This measurably
    improves retrieval quality for short sections whose content alone is
    ambiguous out of context.
    """
    return f"{chunk.document_title} - {chunk.section_title}\n\n{chunk.content}"


def _batched(items: list, batch_size: int):
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def embed_chunks(
    chunks: list[PolicyChunkRecord],
    client: voyageai.Client | None = None,
    batch_size: int = _DEFAULT_BATCH_SIZE,
) -> list[EmbeddedChunk]:
    """Embed a list of policy chunks, in batches, using Voyage AI.

    Args:
        chunks: chunks produced by chunker.py's chunk_all_policies().
        client: an existing voyageai.Client, or None to create one from
            VOYAGE_API_KEY (see create_voyage_client). Accepting an
            injected client is what makes this function testable without
            a real API key or network access - see tests/test_embedder.py.
        batch_size: how many chunks to send per API request.

    Returns:
        One EmbeddedChunk per input chunk, in the same order.

    Raises:
        EmbeddingError: if the API key is missing, the API call fails for
            any reason (auth, rate limit, connectivity), or a returned
            vector's dimension doesn't match EXPECTED_DIMENSION - this
            project would rather fail loudly at ingestion time than
            silently write mismatched-dimension vectors into pgvector.
    """
    if not chunks:
        return []

    voyage_client = client or create_voyage_client()
    embedded: list[EmbeddedChunk] = []

    total_batches = (len(chunks) + batch_size - 1) // batch_size
    for batch_number, batch in enumerate(_batched(chunks, batch_size), start=1):
        logger.info(
            "Embedding batch %d/%d (%d chunks)", batch_number, total_batches, len(batch)
        )
        texts = [build_embedding_text(chunk) for chunk in batch]

        try:
            result = voyage_client.embed(
                texts=texts,
                model=EMBEDDING_MODEL,
                input_type="document",
            )
        except AuthenticationError as exc:
            raise EmbeddingError(f"Voyage AI rejected the API key: {exc}") from exc
        except RateLimitError as exc:
            raise EmbeddingError(
                f"Voyage AI rate limit hit on batch {batch_number}/{total_batches}: {exc}"
            ) from exc
        except (APIConnectionError, ServiceUnavailableError, Timeout) as exc:
            raise EmbeddingError(
                f"Voyage AI was unreachable on batch {batch_number}/{total_batches}: {exc}"
            ) from exc

        if len(result.embeddings) != len(batch):
            raise EmbeddingError(
                f"Voyage AI returned {len(result.embeddings)} embeddings for a "
                f"batch of {len(batch)} chunks - counts must match exactly."
            )

        for chunk, vector in zip(batch, result.embeddings):
            if len(vector) != EXPECTED_DIMENSION:
                raise EmbeddingError(
                    f"Chunk {chunk.source_file}#{chunk.chunk_index} embedded to "
                    f"{len(vector)} dimensions, expected {EXPECTED_DIMENSION} "
                    f"(schema.sql's vector(1024) column). Check EMBEDDING_MODEL "
                    f"and schema.sql are still in agreement."
                )
            embedded.append(EmbeddedChunk(chunk=chunk, embedding=vector))

    logger.info("Embedded %d chunks total across %d batch(es)", len(embedded), total_batches)
    return embedded


def embed_query(query: str, client: voyageai.Client | None = None) -> list[float]:
    """Embed a single guest query at SEARCH time (input_type="query").

    This is what retriever.py will call to embed the guest's question
    before running a pgvector similarity search against the vectors
    `embed_chunks` produced at ingestion time. It is deliberately a
    separate function (not a batch-size-1 call to embed_chunks) because
    it uses input_type="query", not "document" - the two are not
    interchangeable even though they call the same underlying model.
    """
    voyage_client = client or create_voyage_client()

    try:
        result = voyage_client.embed(
            texts=[query],
            model=EMBEDDING_MODEL,
            input_type="query",
        )
    except AuthenticationError as exc:
        raise EmbeddingError(f"Voyage AI rejected the API key: {exc}") from exc
    except RateLimitError as exc:
        raise EmbeddingError(f"Voyage AI rate limit hit embedding query: {exc}") from exc
    except (APIConnectionError, ServiceUnavailableError, Timeout) as exc:
        raise EmbeddingError(f"Voyage AI was unreachable embedding query: {exc}") from exc

    vector = result.embeddings[0]
    if len(vector) != EXPECTED_DIMENSION:
        raise EmbeddingError(
            f"Query embedded to {len(vector)} dimensions, expected {EXPECTED_DIMENSION}."
        )
    return vector