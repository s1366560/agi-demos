"""Agent-First auto-routing broker.

When an agent sends ``model="auto"`` the broker decides which capability
class (``tier``, ``vision``, ``tools``) the turn needs and returns a
:class:`BrokerVerdict`. The verdict is converted into a
:class:`~src.infrastructure.llm.model_pool.PoolFilter` that constrains
the load-balancer's candidate set.

**Agent-First rule (AGENTS.md)**: the verdict is *subjective* — it
classifies user intent and required capabilities. It MUST come from a
structured LLM tool-call, not a regex/keyword heuristic. The broker
therefore issues an actual LLM call against the cheapest model in the
tenant's pool. On hard failure we DO fall back to a deterministic
verdict (medium tier, vision iff any multimodal message, tools iff
tools were supplied) so the platform never wedges, but every fallback
is logged with ``source="fallback"`` for audit.

Results are cached for 30 seconds keyed by ``(tenant_id,
hash(last_user_message_text + tool_signature))`` to amortize the meta-
call across a multi-turn conversation that keeps asking variations of
the same question.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, replace
from typing import Any, Literal

from src.domain.llm_providers.llm_types import Message
from src.infrastructure.llm.model_pool import (
    CandidateModel,
    ModelPoolService,
    PoolFilter,
    get_model_pool_service,
)

logger = logging.getLogger(__name__)

Tier = Literal["small", "medium", "large"]
Category = Literal["chat", "code", "analysis", "vision", "agent_tools"]

_BROKER_CACHE_TTL_SECONDS = 30.0
_BROKER_MAX_RETRIES = 1  # single retry; broker overhead must stay small


@dataclass(frozen=True, kw_only=True)
class BrokerVerdict:
    """Structured verdict from the auto-router.

    Attributes:
        tier: Target capability tier.
        require_vision: Whether the turn needs a vision-capable model.
        require_tools: Whether the turn needs tool-call support.
        category: Coarse task class (for telemetry only).
        rationale: Short justification (LLM-supplied or "fallback").
        source: ``"llm"`` for tool-call verdicts, ``"fallback"`` for
            deterministic ones, ``"cache"`` for cache hits.
    """

    tier: Tier
    require_vision: bool
    require_tools: bool
    category: Category
    rationale: str
    source: Literal["llm", "fallback", "cache"]

    def to_filter(self, exclude_keys: frozenset[str] = frozenset()) -> PoolFilter:
        """Convert the verdict into a pool filter."""
        return PoolFilter(
            tier=self.tier,
            require_vision=self.require_vision,
            require_tools=self.require_tools,
            exclude_keys=exclude_keys,
        )


_BROKER_TOOL: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "route_request",
            "description": (
                "Classify the user's request to pick a model tier. "
                "Choose 'small' for short Q&A / classification / formatting, "
                "'medium' for normal coding/chat/analysis, "
                "'large' for long-context reasoning, complex coding, or "
                "multi-step planning. Set require_vision=true ONLY if the "
                "user attached an image or asks about one. Set "
                "require_tools=true if the conversation already supplies "
                "tools the model is expected to call."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tier": {
                        "type": "string",
                        "enum": ["small", "medium", "large"],
                    },
                    "require_vision": {"type": "boolean"},
                    "require_tools": {"type": "boolean"},
                    "category": {
                        "type": "string",
                        "enum": ["chat", "code", "analysis", "vision", "agent_tools"],
                    },
                    "rationale": {
                        "type": "string",
                        "description": "One short sentence explaining the choice.",
                    },
                },
                "required": [
                    "tier",
                    "require_vision",
                    "require_tools",
                    "category",
                    "rationale",
                ],
            },
        },
    }
]


@dataclass(kw_only=True)
class _CacheEntry:
    verdict: BrokerVerdict
    cached_at: float


class AutoBroker:
    """Issue an LLM tool-call to pick the routing tier for the next turn."""

    def __init__(
        self,
        *,
        pool_service: ModelPoolService | None = None,
        cache_ttl_seconds: float = _BROKER_CACHE_TTL_SECONDS,
    ) -> None:
        self._pool = pool_service or get_model_pool_service()
        self._cache: dict[str, _CacheEntry] = {}
        self._cache_ttl = cache_ttl_seconds

    async def decide(
        self,
        *,
        tenant_id: str | None,
        messages: list[Message] | list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> BrokerVerdict:
        """Return a verdict for the current turn."""
        cache_key = self._cache_key(tenant_id, messages, tools)
        cached = self._cache.get(cache_key)
        if cached is not None and time.monotonic() - cached.cached_at <= self._cache_ttl:
            v = cached.verdict
            cached_verdict = BrokerVerdict(
                tier=v.tier,
                require_vision=v.require_vision,
                require_tools=v.require_tools,
                category=v.category,
                rationale=v.rationale,
                source="cache",
            )
            self._log_verdict(tenant_id, cached_verdict)
            return cached_verdict

        has_image = self._has_image_content(messages)
        has_tools = bool(tools)

        # Pick the cheapest small-tier model from the pool to host the meta-call.
        # If no small-tier exists, fall back to any candidate.
        broker_candidate = await self._pick_broker_model(tenant_id)
        if broker_candidate is None:
            verdict = self._deterministic_verdict(
                has_image=has_image,
                has_tools=has_tools,
                reason="no broker candidate available",
            )
            self._cache[cache_key] = _CacheEntry(verdict=verdict, cached_at=time.monotonic())
            self._log_verdict(tenant_id, verdict)
            return verdict

        try:
            verdict = await self._llm_decide(broker_candidate, messages, tools)
            logger.info(
                "AutoBroker verdict: tier=%s vision=%s tools=%s "
                "category=%s (via %s)",
                verdict.tier,
                verdict.require_vision,
                verdict.require_tools,
                verdict.category,
                broker_candidate.candidate_key,
            )
        except Exception as exc:
            logger.warning(
                "AutoBroker LLM call failed (%s); falling back to heuristic verdict",
                exc,
            )
            verdict = self._deterministic_verdict(
                has_image=has_image,
                has_tools=has_tools,
                reason=f"broker error: {type(exc).__name__}",
            )

        # Clamp capability requirements to objective state. The LLM may
        # over-eagerly demand vision/tools support even when the current
        # turn has neither images nor a tool schema, which would empty
        # the candidate set against pools whose models are not flagged
        # vision-capable in the catalog.
        if verdict.require_vision and not has_image:
            verdict = replace(verdict, require_vision=False)
        if verdict.require_tools and not has_tools:
            verdict = replace(verdict, require_tools=False)

        self._cache[cache_key] = _CacheEntry(verdict=verdict, cached_at=time.monotonic())
        self._log_verdict(tenant_id, verdict)
        return verdict

    @staticmethod
    def _log_verdict(tenant_id: str | None, verdict: BrokerVerdict) -> None:
        """Emit a structured verdict event (rationale text omitted by design)."""
        from src.infrastructure.llm.structured_logger import get_llm_logger

        get_llm_logger().log_auto_broker_verdict(
            tenant_id=tenant_id,
            tier=verdict.tier,
            require_vision=verdict.require_vision,
            require_tools=verdict.require_tools,
            category=verdict.category,
            source=verdict.source,
            rationale_length=len(verdict.rationale or ""),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _pick_broker_model(
        self, tenant_id: str | None
    ) -> CandidateModel | None:
        """Cheapest candidate (small tier preferred, else any)."""
        small = await self._pool.list_candidates(
            tenant_id=tenant_id,
            pool_filter=PoolFilter(tier="small"),
        )
        if small:
            return small[0]
        all_cands = await self._pool.list_candidates(tenant_id=tenant_id)
        return all_cands[0] if all_cands else None

    async def _llm_decide(
        self,
        candidate: CandidateModel,
        messages: list[Message] | list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> BrokerVerdict:
        """Issue the structured tool-call and parse the verdict."""
        from src.infrastructure.llm.litellm.litellm_client import create_litellm_client
        from src.infrastructure.llm.model_catalog import get_model_catalog_service

        client = create_litellm_client(
            candidate.provider_config, catalog=get_model_catalog_service()
        )
        broker_messages = self._build_broker_messages(messages, tools)

        response = await client.generate(
            messages=broker_messages,
            tools=_BROKER_TOOL,
            temperature=0.0,
            max_tokens=256,
            model=candidate.model_name,
        )

        args = self._extract_tool_args(response)
        if args is None:
            raise ValueError("broker response missing route_request tool call")

        return BrokerVerdict(
            tier=args["tier"],
            require_vision=bool(args["require_vision"]),
            require_tools=bool(args["require_tools"]),
            category=args.get("category", "chat"),
            rationale=str(args.get("rationale", "")),
            source="llm",
        )

    @staticmethod
    def _extract_tool_args(response: dict[str, Any]) -> dict[str, Any] | None:
        tool_calls = response.get("tool_calls") or []
        if not tool_calls and "choices" in response:
            # Some clients return raw OpenAI shape; dig deeper defensively.
            try:
                tool_calls = (
                    response["choices"][0]["message"].get("tool_calls") or []
                )
            except (KeyError, IndexError, TypeError):
                tool_calls = []
        for call in tool_calls:
            fn = call.get("function") or {}
            if fn.get("name") == "route_request":
                raw = fn.get("arguments")
                if isinstance(raw, str):
                    try:
                        parsed = json.loads(raw)
                    except json.JSONDecodeError:
                        return None
                    return parsed if isinstance(parsed, dict) else None
                if isinstance(raw, dict):
                    return raw
        return None

    @staticmethod
    def _build_broker_messages(
        messages: list[Message] | list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> list[Message]:
        """Compact prompt — only what the broker needs to decide."""
        last_user_text = AutoBroker._last_user_text(messages) or "(empty)"
        tool_names: list[str] = []
        for t in tools or []:
            name = (t.get("function") or {}).get("name") or t.get("name")
            if name:
                tool_names.append(str(name))
        system = (
            "You are an LLM router. Look at the user's latest message and "
            "the available tools, then call route_request exactly once."
        )
        user = (
            f"Latest user message:\n---\n{last_user_text[:2000]}\n---\n"
            f"Available tools: {', '.join(tool_names) if tool_names else 'none'}\n"
            "Decide the tier."
        )
        return [Message.system(system), Message.user(user)]

    @staticmethod
    def _last_user_text(
        messages: list[Message] | list[dict[str, Any]],
    ) -> str | None:
        for msg in reversed(messages):
            role = (
                getattr(msg, "role", None)
                or (msg.get("role") if isinstance(msg, dict) else None)
            )
            if role != "user":
                continue
            if isinstance(msg, Message):
                return msg.text
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [
                    str(p.get("text", ""))
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                ]
                return "\n".join(parts)
        return None

    @staticmethod
    def _has_image_content(
        messages: list[Message] | list[dict[str, Any]],
    ) -> bool:
        for msg in messages:
            content = (
                getattr(msg, "content", None)
                if isinstance(msg, Message)
                else (msg.get("content") if isinstance(msg, dict) else None)
            )
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") in (
                        "image",
                        "image_url",
                    ):
                        return True
        return False

    @staticmethod
    def _deterministic_verdict(
        *, has_image: bool, has_tools: bool, reason: str
    ) -> BrokerVerdict:
        return BrokerVerdict(
            tier="medium",
            require_vision=has_image,
            require_tools=has_tools,
            category="vision" if has_image else ("agent_tools" if has_tools else "chat"),
            rationale=f"fallback: {reason}",
            source="fallback",
        )

    @staticmethod
    def _cache_key(
        tenant_id: str | None,
        messages: list[Message] | list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
    ) -> str:
        last_user = AutoBroker._last_user_text(messages) or ""
        tool_names = sorted(
            (t.get("function") or {}).get("name") or t.get("name", "")
            for t in (tools or [])
        )
        payload = f"{tenant_id or 'default'}|{last_user[:512]}|{','.join(tool_names)}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# Module-level singleton -----------------------------------------------------

_auto_broker: AutoBroker | None = None


def get_auto_broker() -> AutoBroker:
    """Return the process-wide ``AutoBroker`` singleton."""
    global _auto_broker
    if _auto_broker is None:
        _auto_broker = AutoBroker()
    return _auto_broker


def reset_auto_broker() -> None:
    """Reset the singleton (test helper)."""
    global _auto_broker
    _auto_broker = None
