"""Pre-compaction memory flush.

When the context window is being compressed, this module extracts
durable memories from the conversation messages that are about to
be summarized or discarded.  Aligned with Moltbot's "silent agentic
turn" that persists knowledge before context compaction.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Optional

from src.infrastructure.memory.prompt_safety import looks_like_prompt_injection

logger = logging.getLogger(__name__)

FLUSH_SYSTEM_PROMPT = """\
You are a memory extraction assistant. The conversation below is about to be \
compressed (older messages will be summarized and discarded). Your job is to \
extract any durable information worth preserving for future conversations.

Extract ONLY facts that would be useful in a brand-new session:
- User preferences, habits, working style
- Personal facts (name, role, team, timezone)
- Technical decisions, architecture choices, constraints
- Important entities (project names, URLs, credentials names)
- Agreements, action items, commitments
- Anything the user explicitly asked to remember

Rules:
- Be concise. Each memory should be a self-contained statement.
- Skip transient details (debugging steps, error messages, tool outputs).
- Skip information the assistant knows from training data.
- If nothing durable, return empty array.

Respond ONLY with a JSON array. Each item: {"content": "...", "category": "..."}.
Category: preference | fact | decision | entity.
If nothing to remember: []"""

FLUSH_USER_TEMPLATE = """\
Conversation being compressed ({msg_count} messages):

{conversation_text}"""

VALID_CATEGORIES = {"preference", "fact", "decision", "entity"}


class MemoryFlushService:
    """Extracts and persists durable memories before context compaction.

    Called when the context builder detects that compression is needed.
    Uses a lightweight LLM call on the messages being compressed,
    then stores results via the same capture pipeline.
    """

    def __init__(
        self,
        llm_client: Any,
        embedding_service: Any = None,
        session_factory: Any = None,
    ):
        self._llm_client = llm_client
        self._embedding = embedding_service
        self._session_factory = session_factory
        self.last_flush_count: int = 0

    async def flush(
        self,
        conversation_messages: list[dict],
        project_id: str,
        conversation_id: str = "unknown",
    ) -> int:
        """Extract and persist memories from messages about to be compressed.

        Args:
            conversation_messages: Messages being compressed (role/content dicts).
            project_id: Project scope.
            conversation_id: Source conversation.

        Returns:
            Number of memories flushed.
        """
        self.last_flush_count = 0

        if not conversation_messages:
            return 0

        # Build a compact text representation of the conversation
        conv_text = self._format_conversation(conversation_messages)
        if not conv_text.strip():
            return 0

        # Extract via LLM
        items = await self._extract(conv_text, len(conversation_messages))
        if not items:
            return 0

        # Store via chunk repo
        chunk_repo = await self._get_chunk_repo()
        flushed = 0
        session_to_close = None

        try:
            if chunk_repo:
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

                embedding = None
                if self._embedding:
                    try:
                        embedding = await self._embedding.embed_text_safe(content)
                        if embedding and chunk_repo:
                            if await self._is_duplicate(chunk_repo, embedding, project_id):
                                continue
                    except Exception:
                        pass

                stored = await self._store_chunk(
                    chunk_repo, content, category, embedding, project_id, conversation_id
                )
                if stored:
                    flushed += 1

            if session_to_close and flushed > 0:
                await session_to_close.commit()
        except Exception as e:
            logger.warning(f"Memory flush storage error: {e}")
            if session_to_close:
                try:
                    await session_to_close.rollback()
                except Exception:
                    pass
        finally:
            if session_to_close:
                await session_to_close.close()

        self.last_flush_count = flushed
        if flushed > 0:
            logger.info(
                f"[MemoryFlush] Flushed {flushed} memories before compaction "
                f"(conversation={conversation_id})"
            )
        return flushed

    def _format_conversation(self, messages: list[dict], max_chars: int = 8000) -> str:
        """Format messages into a compact text for LLM analysis."""
        lines: list[str] = []
        total = 0
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if not content or role == "system":
                continue
            # Truncate very long messages (e.g. tool outputs)
            if len(content) > 500:
                content = content[:500] + "..."
            line = f"[{role}] {content}"
            if total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line)
        return "\n".join(lines)

    async def _extract(self, conv_text: str, msg_count: int) -> list[dict]:
        """Call LLM to extract durable memories."""
        try:
            user_prompt = FLUSH_USER_TEMPLATE.format(
                msg_count=msg_count,
                conversation_text=conv_text,
            )
            response = await self._llm_client.generate_chat(
                messages=[
                    {"role": "system", "content": FLUSH_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.0,
                max_tokens=1024,
            )
            text = response.get("content", "") if isinstance(response, dict) else str(response)
            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            items = json.loads(text)
            if not isinstance(items, list):
                return []
            return items
        except Exception as e:
            logger.debug(f"Memory flush extraction failed: {e}")
            return []

    async def _get_chunk_repo(self) -> Optional[Any]:
        """Create chunk repo with a fresh DB session."""
        if self._session_factory is None:
            return None
        try:
            from src.infrastructure.adapters.secondary.persistence.sql_chunk_repository import (
                SqlChunkRepository,
            )

            session = self._session_factory()
            return SqlChunkRepository(session)
        except Exception as e:
            logger.debug(f"Failed to create chunk repo for flush: {e}")
            return None

    async def _is_duplicate(self, chunk_repo: Any, embedding: list[float], project_id: str) -> bool:
        """Check if a memory already exists with high similarity."""
        try:
            similar = await chunk_repo.find_similar(embedding, project_id, threshold=0.95)
            return len(similar) > 0
        except Exception:
            return False

    async def _store_chunk(
        self,
        chunk_repo: Optional[Any],
        content: str,
        category: str,
        embedding: Optional[list[float]],
        project_id: str,
        conversation_id: str,
    ) -> bool:
        """Store a single memory chunk."""
        if chunk_repo is None:
            return False
        try:
            import hashlib

            from src.infrastructure.adapters.secondary.persistence.models import MemoryChunk

            chunk = MemoryChunk(
                id=str(uuid.uuid4()),
                project_id=project_id,
                source_type="conversation",
                source_id=conversation_id,
                chunk_index=0,
                content=content,
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
                embedding=embedding,
                metadata={"flush": True},
                importance=0.7,
                category=category,
            )
            await chunk_repo.save(chunk)
            return True
        except Exception as e:
            logger.debug(f"Failed to store flush chunk: {e}")
            return False
