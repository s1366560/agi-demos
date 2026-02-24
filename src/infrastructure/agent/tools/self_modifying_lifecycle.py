"""Shared post-change lifecycle orchestration for self-modifying tools."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


class SelfModifyingLifecycleOrchestrator:
    """Coordinate cache invalidation, probing, and event metadata assembly."""

    @staticmethod
    def run_post_change(
        *,
        source: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
        clear_tool_definitions: bool = True,
        expected_tool_names: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run post-change lifecycle steps and return structured summary."""
        result: dict[str, Any] = {
            "source": source,
            "timestamp": datetime.now(UTC).isoformat(),
            "cache_invalidation": {},
            "probe": {},
            "metadata": metadata or {},
        }

        from src.infrastructure.agent.state.agent_worker_state import (
            get_cached_tools_for_project,
            invalidate_all_caches_for_project,
            invalidate_skill_loader_cache,
        )

        if tenant_id:
            invalidate_skill_loader_cache(tenant_id)
            result["cache_invalidation"]["skill_loader"] = f"invalidated:{tenant_id}"
        else:
            invalidate_skill_loader_cache()
            result["cache_invalidation"]["skill_loader"] = "invalidated:all"

        if tenant_id and project_id:
            invalidation = invalidate_all_caches_for_project(
                project_id=project_id,
                tenant_id=tenant_id,
                clear_tool_definitions=clear_tool_definitions,
            )
            result["cache_invalidation"]["project"] = invalidation.get("invalidated", {})

        if expected_tool_names and project_id:
            cached_tools = get_cached_tools_for_project(project_id)
            if cached_tools is None:
                result["probe"] = {
                    "status": "cache_miss",
                    "expected": expected_tool_names,
                }
            else:
                missing = [name for name in expected_tool_names if name not in cached_tools]
                result["probe"] = {
                    "status": "ok" if not missing else "missing_tools",
                    "expected_count": len(expected_tool_names),
                    "missing_tools": missing,
                }
        else:
            result["probe"] = {"status": "skipped"}

        return result
