"""Actual isolated Neo4j reads; generation and embedding are explicitly disabled."""

from __future__ import annotations

from typing import TYPE_CHECKING, Never, override

from src.domain.llm_providers.llm_types import LLMClient, LLMConfig
from src.infrastructure.graph.embedding.embedding_service import EmbeddingService
from src.infrastructure.graph.native_graph_adapter import NativeGraphAdapter
from src.infrastructure.graph.neo4j_client import Neo4jClient

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

QA_NEO4J_URI = "bolt://127.0.0.1:17687"


class QaGenerationDisabled(LLMClient):
    @override
    async def _generate_response(self, *_args: object, **_kwargs: object) -> Never:
        raise RuntimeError("LLM generation is disabled in the Cloud knowledge QA API")

    @override
    async def generate(self, *_args: object, **_kwargs: object) -> Never:
        raise RuntimeError("LLM generation is disabled in the Cloud knowledge QA API")

    @override
    def generate_stream(self, *_args: object, **_kwargs: object) -> AsyncGenerator[object, None]:
        raise RuntimeError("LLM generation is disabled in the Cloud knowledge QA API")


class QaEmbedderDisabled:
    embedding_dim = 0

    async def create(self, input_data: str | list[str]) -> Never:
        raise RuntimeError("Embedding is disabled in the Cloud knowledge QA API")


class QaEmbeddingDisabled(EmbeddingService):
    @override
    async def embed_text(self, text: str) -> Never:
        raise RuntimeError("Embedding is disabled in the Cloud knowledge QA API")

    @override
    async def embed_text_safe(self, text: str) -> Never:
        raise RuntimeError("Embedding is disabled in the Cloud knowledge QA API")

    @override
    async def embed_batch(self, *_args: object, **_kwargs: object) -> Never:
        raise RuntimeError("Embedding is disabled in the Cloud knowledge QA API")

    @override
    async def embed_batch_safe(self, *_args: object, **_kwargs: object) -> Never:
        raise RuntimeError("Embedding is disabled in the Cloud knowledge QA API")


async def create_qa_graph(neo4j_uri: str) -> NativeGraphAdapter:
    if neo4j_uri != QA_NEO4J_URI:
        raise ValueError("Only the explicitly isolated QA Neo4j address is accepted")
    # The isolated loopback container has NEO4J_AUTH=none. No global Neo4j settings
    # or LLM/provider factories are consulted by this entrypoint.
    client = Neo4jClient(uri=neo4j_uri, user="", password="", database="neo4j")
    try:
        await client.initialize()
    except BaseException:
        await client.close()
        raise
    return NativeGraphAdapter(
        neo4j_client=client,
        llm_client=QaGenerationDisabled(LLMConfig(model="qa-generation-disabled")),
        embedding_service=QaEmbeddingDisabled(QaEmbedderDisabled()),
        enable_reflexion=False,
        auto_clear_embeddings=False,
    )
