from typing import Any

import pytest

from src.application.use_cases.agent.compose_tools import ComposeToolsUseCase
from src.domain.model.agent import ToolComposition
from src.domain.ports.agent.agent_tool_port import AgentToolBase


class _FakeTool(AgentToolBase):
    def __init__(self, name: str, result: str) -> None:
        self._name = name
        self._result = result
        self.calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"{self._name} tool"

    async def execute(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return self._result


class _RecordingCompositionRepository:
    def __init__(self, existing: list[ToolComposition] | None = None) -> None:
        self.existing = existing or []
        self.saved: ToolComposition | None = None
        self.list_calls: list[dict[str, Any]] = []
        self.usage_updates: list[dict[str, Any]] = []

    async def save(self, composition: ToolComposition) -> ToolComposition:
        self.saved = composition
        return composition

    async def get_by_id(
        self, composition_id: str, tenant_id: str | None = None
    ) -> ToolComposition | None:
        for composition in self.existing:
            if composition.id == composition_id and (
                tenant_id is None or composition.tenant_id == tenant_id
            ):
                return composition
        return None

    async def get_by_name(
        self,
        name: str,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> ToolComposition | None:
        for composition in self.existing:
            if composition.name != name:
                continue
            if tenant_id is not None and composition.tenant_id != tenant_id:
                continue
            if project_id is not None and composition.project_id not in {project_id, None}:
                continue
            return composition
        return None

    async def list_by_tools(
        self,
        tool_names: list[str],
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> list[ToolComposition]:
        self.list_calls.append(
            {
                "tool_names": tool_names,
                "tenant_id": tenant_id,
                "project_id": project_id,
            }
        )
        return [
            composition
            for composition in self.existing
            if (tenant_id is None or composition.tenant_id == tenant_id)
            and (project_id is None or composition.project_id in {project_id, None})
        ]

    async def list_all(
        self,
        limit: int = 100,
        tenant_id: str | None = None,
        project_id: str | None = None,
    ) -> list[ToolComposition]:
        return [
            composition
            for composition in self.existing[:limit]
            if (tenant_id is None or composition.tenant_id == tenant_id)
            and (project_id is None or composition.project_id in {project_id, None})
        ]

    async def update_usage(
        self,
        composition_id: str,
        success: bool,
    ) -> ToolComposition | None:
        self.usage_updates.append({"composition_id": composition_id, "success": success})
        if self.saved and self.saved.id == composition_id:
            return self.saved
        for composition in self.existing:
            if composition.id == composition_id:
                return composition
        return None

    async def delete(self, composition_id: str) -> bool:
        return False


@pytest.mark.asyncio
async def test_execute_creates_composition_with_tenant_context() -> None:
    repository = _RecordingCompositionRepository()
    use_case = ComposeToolsUseCase(
        composition_repository=repository,
        available_tools={
            "search": _FakeTool("search", "search-output"),
            "summarize": _FakeTool("summarize", "summary-output"),
        },
    )

    result = await use_case.execute(
        ["search", "summarize"],
        execution_context={"tenant_id": " tenant-a ", "project_id": "project-a"},
    )

    assert repository.list_calls[0]["tenant_id"] == "tenant-a"
    assert repository.list_calls[0]["project_id"] == "project-a"
    assert repository.saved is not None
    assert repository.saved.tenant_id == "tenant-a"
    assert repository.saved.project_id == "project-a"
    assert result["composition"]["tenant_id"] == "tenant-a"
    assert repository.usage_updates == [{"composition_id": repository.saved.id, "success": True}]


@pytest.mark.asyncio
async def test_execute_requires_tenant_id_before_creating_composition() -> None:
    repository = _RecordingCompositionRepository()
    use_case = ComposeToolsUseCase(
        composition_repository=repository,
        available_tools={"search": _FakeTool("search", "search-output")},
    )

    with pytest.raises(ValueError, match="tenant_id is required"):
        await use_case.execute(["search"], execution_context={})

    assert repository.saved is None


@pytest.mark.asyncio
async def test_execute_prefers_project_scoped_existing_composition() -> None:
    tenant_composition = ToolComposition.create(
        tenant_id="tenant-a",
        name="tenant-wide",
        description="Tenant-wide composition",
        tools=["search"],
        project_id=None,
    )
    project_composition = ToolComposition.create(
        tenant_id="tenant-a",
        name="project-specific",
        description="Project-specific composition",
        tools=["search"],
        project_id="project-a",
    )
    repository = _RecordingCompositionRepository(existing=[tenant_composition, project_composition])
    use_case = ComposeToolsUseCase(
        composition_repository=repository,
        available_tools={"search": _FakeTool("search", "search-output")},
    )

    result = await use_case.execute(
        ["search"],
        execution_context={"tenant_id": "tenant-a", "project_id": "project-a"},
    )

    assert repository.saved is None
    assert result["composition"]["id"] == project_composition.id
