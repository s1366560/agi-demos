"""LLM-driven auto-capture postprocessor for agent memory.

Uses the LLM to decide which parts of a conversation are worth
remembering, extracting structured memory items with categories.
Replaces the previous rule-based regex approach with semantic
understanding (aligned with Moltbot's LLM-driven design).
"""

from __future__ import annotations

import contextlib
import json
import logging
import uuid
from typing import TYPE_CHECKING, Any

from src.infrastructure.memory.prompt_safety import looks_like_prompt_injection

if TYPE_CHECKING:
    from src.domain.llm_providers.llm_types import LLMClient
    from src.infrastructure.adapters.secondary.persistence.sql_chunk_repository import (
        SqlChunkRepository,
    )
    from src.infrastructure.graph.embedding.embedding_service import EmbeddingService

logger = logging.getLogger(__name__)

MEMORY_EXTRACT_SYSTEM_PROMPT = """\
You are a memory extraction assistant. Analyze the conversation and \
extract durable facts worth remembering for future conversations.

Extract ONLY information useful in future sessions:
- User preferences and habits (e.g. "prefers dark mode")
- Personal facts (name, role, location, team)
- Technical decisions and constraints
- Important entities (emails, project names, tools)
- Explicit requests to remember something

Rules:
- Do NOT extract transient task details or ephemeral questions.
- Do NOT extract information the assistant knows from training data.
- Each memory should be a concise, self-contained statement.
- If nothing worth remembering, return empty array.

Respond ONLY with a JSON array. Each item: {"content": "...", "category": "..."}.
Category must be one of: preference, fact, decision, entity.
If nothing to remember: []"""

MEMORY_EXTRACT_USER_TEMPLATE = """\
Conversation to analyze:

User: {user_message}
Assistant: {assistant_response}"""

VALID_CATEGORIES = {"preference", "fact", "decision", "entity"}


class MemoryCapturePostprocessor:
    """Extracts memorable information from conversations via LLM.

    Uses a lightweight LLM call to semantically determine what is
    worth remembering, then stores extracted items as memory chunks
    with deduplication and prompt injection filtering.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        chunk_repo: SqlChunkRepository = None,
        embedding_service: EmbeddingService = None,
        session_factory: Any = None,
    ) -> None:
        self._llm_client = llm_client
        self._chunk_repo = chunk_repo
        self._embedding = embedding_service
        self._session_factory = session_factory
        # Populated after capture for event emission
        self.last_categories: list[str] = []
        logger.info(
            f"MemoryCapturePostprocessor initialized "
            f"(llm={type(llm_client).__name__}, "
            f"embedding={'yes' if embedding_service else 'no'}, "
            f"session_factory={'yes' if session_factory else 'no'})"
        )

    async def _get_chunk_repo(self) -> Any:
        """Get or create a chunk repository with a fresh DB session."""
        if self._chunk_repo is not None:
            return self._chunk_repo
        if self._session_factory is None:
            return None
        try:
            from src.infrastructure.adapters.secondary.persistence.sql_chunk_repository import (
                SqlChunkRepository,
            )

            session = self._session_factory()
            return SqlChunkRepository(session)
        except Exception as e:
            logger.debug(f"Failed to create chunk repo: {e}")
            return None

    async def capture(
        self,
        user_message: str,
        assistant_response: str,
        project_id: str,
        conversation_id: str = "unknown",
    ) -> int:
        """Extract and store memorable items from a conversation turn.

        Args:
            user_message: The user's message content.
            assistant_response: The assistant's response content.
            project_id: Project scope for storage.
            conversation_id: Source conversation ID.

        Returns:
            Number of memory items captured.
        """
        self.last_categories = []

        if not user_message or not isinstance(user_message, str):
            return 0

        if looks_like_prompt_injection(user_message):
            logger.info("Skipping message with prompt injection pattern")
            return 0

        # Ask LLM what's worth remembering
        items = await self._extract_memories(user_message, assistant_response)
        if not items:
            return 0

        # Get chunk repo (may create a new DB session)
        chunk_repo = await self._get_chunk_repo()

        captured = 0
        categories = []
        session_to_close = None
        try:
            # Track if we created a new session that needs commit/close
            if chunk_repo and chunk_repo is not self._chunk_repo:
                session_to_close = getattr(chunk_repo, "_session", None)

            for item in items:
                content = item.get("content", "").strip()
                category = item.get("category", "other")
                if category not in VALID_CATEGORIES:
                    category = "other"

                if not content or len(content) < 3:
                    continue

                if looks_like_prompt_injection(content):
                    continue

                # Deduplication via embedding similarity
                embedding = None
                if self._embedding:
                    try:
                        embedding = await self._embedding.embed_text_safe(content)
                        if embedding and chunk_repo:
                            if await self._is_duplicate(chunk_repo, embedding, project_id):
                                logger.debug(f"Skipping duplicate memory: {content[:50]}")
                                continue
                    except Exception as e:
                        logger.debug(f"Dedup check failed: {e}")

                # Store as chunk
                stored = await self._store_chunk(
                    chunk_repo, content, category, embedding, project_id, conversation_id
                )
                if stored:
                    captured += 1
                    categories.append(category)

            # Commit if we created a new session
            if session_to_close and captured > 0:
                await session_to_close.commit()
        except Exception as e:
            logger.warning(f"Memory capture storage error: {e}")
            if session_to_close:
                with contextlib.suppress(Exception):
                    await session_to_close.rollback()
        finally:
            if session_to_close:
                await session_to_close.close()

        self.last_categories = categories
        return captured

    async def _extract_memories(
        self,
        user_message: str,
        assistant_response: str,
    ) -> list[dict]:
        """Ask LLM to extract memorable items from conversation."""
        if not self._llm_client:
            return []

        user_prompt = MEMORY_EXTRACT_USER_TEMPLATE.format(
            user_message=user_message,
            assistant_response=assistant_response[:2000],
        )

        try:
            response = await self._llm_client.generate(
                messages=[
                    {"role": "system", "content": MEMORY_EXTRACT_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=500,
            )
            content = response.get("content", "") if isinstance(response, dict) else str(response)

            # Log memory extraction cost
            usage = response.get("usage") if isinstance(response, dict) else None
            if usage:
                logger.debug(
                    f"Memory capture LLM cost: "
                    f"in={usage.get('input_tokens', 0)}, "
                    f"out={usage.get('output_tokens', 0)}"
                )

            return self._parse_llm_response(content)
        except Exception as e:
            logger.warning(f"LLM memory extraction failed ({type(self._llm_client).__name__}): {e}")
            return []

    def _parse_llm_response(self, content: str) -> list[dict]:
        """Parse LLM JSON response, handling markdown fences."""
        if not content:
            return []

        text = content.strip()
        # Strip markdown code fences
        if text.startswith("```"):
            lines = text.split("\n")
            lines = lines[1:]  # remove opening fence
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()

        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [item for item in parsed if isinstance(item, dict) and "content" in item]
        except json.JSONDecodeError:
            logger.debug(f"Failed to parse LLM memory response: {text[:200]}")
        return []

    async def _store_chunk(
        self,
        chunk_repo: Any,
        content: str,
        category: str,
        embedding: list[float] | None,
        project_id: str,
        conversation_id: str,
    ) -> bool:
        """Store a single memory chunk."""
        if not chunk_repo:
            return False
        try:
            from src.infrastructure.adapters.secondary.persistence.models import MemoryChunk
            from src.infrastructure.memory.chunker import _hash_text

            chunk = MemoryChunk(
                id=str(uuid.uuid4()),
                project_id=project_id,
                source_type="conversation",
                source_id=conversation_id,
                chunk_index=0,
                content=content,
                content_hash=_hash_text(content),
                embedding=embedding,
                importance=0.7,
                category=category,
            )
            await chunk_repo.save(chunk)
            logger.info(f"Auto-captured memory: category={category}, len={len(content)}")
            return True
        except Exception as e:
            logger.warning(f"Failed to capture memory: {e}")
            return False

    async def _is_duplicate(
        self,
        chunk_repo: Any,
        embedding: list[float],
        project_id: str,
        threshold: float = 0.95,
    ) -> bool:
        """Check if similar content already exists."""
        try:
            similar = await chunk_repo.find_similar(
                embedding, project_id, threshold=threshold, limit=1
            )
            return len(similar) > 0
        except Exception:
            return False
