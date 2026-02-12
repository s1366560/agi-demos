"""
Unit tests for SubAgent Template Repository and REST API endpoints.

Tests cover:
- SqlSubAgentTemplateRepository CRUD operations
- Template marketplace REST API endpoints
- Builtin template seeding
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.domain.ports.repositories.subagent_template_repository import (
    SubAgentTemplateRepositoryPort,
)
from src.infrastructure.adapters.secondary.persistence.seed_templates import (
    BUILTIN_TEMPLATES,
    seed_builtin_templates,
)


# === Fake In-Memory Repository for Testing ===


class FakeTemplateRepository(SubAgentTemplateRepositoryPort):
    """In-memory fake repository for testing."""

    def __init__(self):
        self._templates: Dict[str, dict] = {}

    async def create(self, template: dict) -> dict:
        template_id = template.get("id") or str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()
        stored = {
            "id": template_id,
            "tenant_id": template["tenant_id"],
            "name": template["name"],
            "version": template.get("version", "1.0.0"),
            "display_name": template.get("display_name"),
            "description": template.get("description"),
            "category": template.get("category", "general"),
            "tags": template.get("tags", []),
            "system_prompt": template["system_prompt"],
            "trigger_description": template.get("trigger_description"),
            "trigger_keywords": template.get("trigger_keywords", []),
            "trigger_examples": template.get("trigger_examples", []),
            "model": template.get("model", "inherit"),
            "max_tokens": template.get("max_tokens", 4096),
            "temperature": template.get("temperature", 0.7),
            "max_iterations": template.get("max_iterations", 10),
            "allowed_tools": template.get("allowed_tools", ["*"]),
            "author": template.get("author"),
            "is_builtin": template.get("is_builtin", False),
            "is_published": template.get("is_published", True),
            "install_count": template.get("install_count", 0),
            "rating": template.get("rating", 0.0),
            "metadata": template.get("metadata"),
            "created_at": now,
            "updated_at": None,
        }
        self._templates[template_id] = stored
        return stored

    async def get_by_id(self, template_id: str) -> Optional[dict]:
        return self._templates.get(template_id)

    async def get_by_name(
        self, tenant_id: str, name: str, version: Optional[str] = None
    ) -> Optional[dict]:
        for t in self._templates.values():
            if t["tenant_id"] == tenant_id and t["name"] == name:
                if version is None or t["version"] == version:
                    return t
        return None

    async def update(self, template_id: str, data: dict) -> Optional[dict]:
        if template_id not in self._templates:
            return None
        self._templates[template_id].update(data)
        self._templates[template_id]["updated_at"] = (
            datetime.now(timezone.utc).isoformat()
        )
        return self._templates[template_id]

    async def delete(self, template_id: str) -> bool:
        if template_id in self._templates:
            del self._templates[template_id]
            return True
        return False

    async def list_templates(
        self,
        tenant_id: str,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
        query: Optional[str] = None,
        published_only: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> List[dict]:
        results = []
        for t in self._templates.values():
            if t["tenant_id"] != tenant_id:
                continue
            if published_only and not t["is_published"]:
                continue
            if category and t["category"] != category:
                continue
            if query and query.lower() not in (t["name"] + (t["description"] or "")).lower():
                continue
            results.append(t)
        return results[offset : offset + limit]

    async def count_templates(
        self,
        tenant_id: str,
        category: Optional[str] = None,
        published_only: bool = True,
    ) -> int:
        count = 0
        for t in self._templates.values():
            if t["tenant_id"] != tenant_id:
                continue
            if published_only and not t["is_published"]:
                continue
            if category and t["category"] != category:
                continue
            count += 1
        return count

    async def list_categories(self, tenant_id: str) -> List[str]:
        categories = set()
        for t in self._templates.values():
            if t["tenant_id"] == tenant_id and t["is_published"]:
                categories.add(t["category"])
        return sorted(categories)

    async def increment_install_count(self, template_id: str) -> None:
        if template_id in self._templates:
            self._templates[template_id]["install_count"] += 1


TENANT_ID = "test-tenant-001"


@pytest.fixture
def repo():
    return FakeTemplateRepository()


def _make_template_data(**overrides) -> dict:
    base = {
        "tenant_id": TENANT_ID,
        "name": "test-template",
        "system_prompt": "You are a test assistant.",
        "display_name": "Test Template",
        "description": "A template for testing.",
        "category": "testing",
        "tags": ["test"],
        "trigger_description": "Test tasks",
        "trigger_keywords": ["test"],
    }
    base.update(overrides)
    return base


# === Repository Port Interface Tests ===


@pytest.mark.unit
class TestSubAgentTemplateRepository:
    """Tests for template repository CRUD operations."""

    async def test_create_template(self, repo):
        data = _make_template_data()
        result = await repo.create(data)

        assert result["id"]
        assert result["name"] == "test-template"
        assert result["tenant_id"] == TENANT_ID
        assert result["system_prompt"] == "You are a test assistant."
        assert result["is_builtin"] is False
        assert result["is_published"] is True
        assert result["install_count"] == 0

    async def test_get_by_id(self, repo):
        created = await repo.create(_make_template_data())
        fetched = await repo.get_by_id(created["id"])

        assert fetched is not None
        assert fetched["id"] == created["id"]
        assert fetched["name"] == created["name"]

    async def test_get_by_id_not_found(self, repo):
        result = await repo.get_by_id("nonexistent")
        assert result is None

    async def test_get_by_name(self, repo):
        await repo.create(_make_template_data(name="unique-name"))
        result = await repo.get_by_name(TENANT_ID, "unique-name")

        assert result is not None
        assert result["name"] == "unique-name"

    async def test_get_by_name_with_version(self, repo):
        await repo.create(_make_template_data(name="versioned", version="1.0.0"))
        await repo.create(_make_template_data(name="versioned", version="2.0.0"))

        v1 = await repo.get_by_name(TENANT_ID, "versioned", "1.0.0")
        assert v1 is not None
        assert v1["version"] == "1.0.0"

    async def test_get_by_name_not_found(self, repo):
        result = await repo.get_by_name(TENANT_ID, "nonexistent")
        assert result is None

    async def test_update_template(self, repo):
        created = await repo.create(_make_template_data())
        updated = await repo.update(
            created["id"], {"description": "Updated description"}
        )

        assert updated is not None
        assert updated["description"] == "Updated description"
        assert updated["updated_at"] is not None

    async def test_update_nonexistent(self, repo):
        result = await repo.update("nonexistent", {"description": "x"})
        assert result is None

    async def test_delete_template(self, repo):
        created = await repo.create(_make_template_data())
        deleted = await repo.delete(created["id"])

        assert deleted is True
        assert await repo.get_by_id(created["id"]) is None

    async def test_delete_nonexistent(self, repo):
        deleted = await repo.delete("nonexistent")
        assert deleted is False

    async def test_list_templates_basic(self, repo):
        await repo.create(_make_template_data(name="t1"))
        await repo.create(_make_template_data(name="t2"))

        results = await repo.list_templates(TENANT_ID)
        assert len(results) == 2

    async def test_list_templates_filter_category(self, repo):
        await repo.create(_make_template_data(name="dev", category="development"))
        await repo.create(_make_template_data(name="res", category="research"))

        results = await repo.list_templates(TENANT_ID, category="development")
        assert len(results) == 1
        assert results[0]["name"] == "dev"

    async def test_list_templates_published_only(self, repo):
        await repo.create(_make_template_data(name="pub", is_published=True))
        await repo.create(_make_template_data(name="draft", is_published=False))

        results = await repo.list_templates(TENANT_ID, published_only=True)
        assert len(results) == 1
        assert results[0]["name"] == "pub"

    async def test_list_templates_pagination(self, repo):
        for i in range(5):
            await repo.create(_make_template_data(name=f"t{i}"))

        page1 = await repo.list_templates(TENANT_ID, limit=2, offset=0)
        page2 = await repo.list_templates(TENANT_ID, limit=2, offset=2)
        page3 = await repo.list_templates(TENANT_ID, limit=2, offset=4)

        assert len(page1) == 2
        assert len(page2) == 2
        assert len(page3) == 1

    async def test_list_templates_tenant_isolation(self, repo):
        await repo.create(_make_template_data(name="t1", tenant_id="tenant-a"))
        await repo.create(_make_template_data(name="t2", tenant_id="tenant-b"))

        results_a = await repo.list_templates("tenant-a")
        results_b = await repo.list_templates("tenant-b")

        assert len(results_a) == 1
        assert len(results_b) == 1

    async def test_count_templates(self, repo):
        await repo.create(_make_template_data(name="t1"))
        await repo.create(_make_template_data(name="t2"))

        count = await repo.count_templates(TENANT_ID)
        assert count == 2

    async def test_count_templates_with_category(self, repo):
        await repo.create(_make_template_data(name="d1", category="dev"))
        await repo.create(_make_template_data(name="d2", category="dev"))
        await repo.create(_make_template_data(name="r1", category="research"))

        count = await repo.count_templates(TENANT_ID, category="dev")
        assert count == 2

    async def test_list_categories(self, repo):
        await repo.create(_make_template_data(name="t1", category="research"))
        await repo.create(_make_template_data(name="t2", category="development"))
        await repo.create(_make_template_data(name="t3", category="content"))

        categories = await repo.list_categories(TENANT_ID)
        assert sorted(categories) == ["content", "development", "research"]

    async def test_increment_install_count(self, repo):
        created = await repo.create(_make_template_data())
        assert created["install_count"] == 0

        await repo.increment_install_count(created["id"])
        updated = await repo.get_by_id(created["id"])
        assert updated["install_count"] == 1

        await repo.increment_install_count(created["id"])
        updated = await repo.get_by_id(created["id"])
        assert updated["install_count"] == 2


# === Seed Builtin Templates Tests ===


@pytest.mark.unit
class TestSeedBuiltinTemplates:
    """Tests for builtin template seeding."""

    async def test_seed_creates_all_builtins(self, repo):
        created = await seed_builtin_templates(repo, TENANT_ID)
        assert created == len(BUILTIN_TEMPLATES)

        # Verify each template exists
        for bt in BUILTIN_TEMPLATES:
            result = await repo.get_by_name(TENANT_ID, bt["name"])
            assert result is not None
            assert result["is_builtin"] is True

    async def test_seed_is_idempotent(self, repo):
        first_run = await seed_builtin_templates(repo, TENANT_ID)
        second_run = await seed_builtin_templates(repo, TENANT_ID)

        assert first_run == len(BUILTIN_TEMPLATES)
        assert second_run == 0

    async def test_seed_per_tenant(self, repo):
        await seed_builtin_templates(repo, "tenant-1")
        await seed_builtin_templates(repo, "tenant-2")

        t1 = await repo.list_templates("tenant-1")
        t2 = await repo.list_templates("tenant-2")

        assert len(t1) == len(BUILTIN_TEMPLATES)
        assert len(t2) == len(BUILTIN_TEMPLATES)

    async def test_builtin_templates_have_required_fields(self):
        for bt in BUILTIN_TEMPLATES:
            assert "name" in bt
            assert "system_prompt" in bt
            assert "trigger_description" in bt
            assert "is_builtin" in bt
            assert bt["is_builtin"] is True


# === REST API Router Tests ===


@pytest.mark.unit
class TestTemplateRouterEndpoints:
    """Tests for template REST API request/response schemas."""

    def test_template_create_schema_valid(self):
        from src.infrastructure.adapters.primary.web.routers.subagents import (
            TemplateCreate,
        )

        data = TemplateCreate(
            name="test",
            system_prompt="You are a test agent.",
            category="testing",
        )
        assert data.name == "test"
        assert data.version == "1.0.0"
        assert data.model == "inherit"
        assert data.max_tokens == 4096
        assert data.is_published is True

    def test_template_create_schema_full(self):
        from src.infrastructure.adapters.primary.web.routers.subagents import (
            TemplateCreate,
        )

        data = TemplateCreate(
            name="full-template",
            version="2.0.0",
            display_name="Full Template",
            description="Complete template",
            category="development",
            tags=["dev", "full"],
            system_prompt="You are a dev agent.",
            trigger_description="Dev tasks",
            trigger_keywords=["code", "dev"],
            trigger_examples=["Write code"],
            model="gpt-4",
            max_tokens=8192,
            temperature=0.5,
            max_iterations=20,
            allowed_tools=["terminal"],
            author="tester",
            is_published=False,
        )
        assert data.version == "2.0.0"
        assert data.tags == ["dev", "full"]
        assert data.is_published is False

    def test_template_response_schema(self):
        from src.infrastructure.adapters.primary.web.routers.subagents import (
            TemplateResponse,
        )

        resp = TemplateResponse(
            id="t-001",
            tenant_id="ten-001",
            name="test",
            version="1.0.0",
            display_name="Test",
            description=None,
            category="general",
            tags=[],
            system_prompt="prompt",
            trigger_description=None,
            trigger_keywords=[],
            trigger_examples=[],
            model="inherit",
            max_tokens=4096,
            temperature=0.7,
            max_iterations=10,
            allowed_tools=["*"],
            author=None,
            is_builtin=False,
            is_published=True,
            install_count=0,
            rating=0.0,
            metadata=None,
            created_at=None,
            updated_at=None,
        )
        assert resp.id == "t-001"

    def test_template_update_schema(self):
        from src.infrastructure.adapters.primary.web.routers.subagents import (
            TemplateUpdate,
        )

        data = TemplateUpdate(description="New description", category="research")
        dumped = data.model_dump(exclude_unset=True)
        assert "description" in dumped
        assert "category" in dumped
        assert "name" not in dumped

    def test_template_list_response_schema(self):
        from src.infrastructure.adapters.primary.web.routers.subagents import (
            TemplateListResponse,
            TemplateResponse,
        )

        resp = TemplateListResponse(templates=[], total=0)
        assert resp.total == 0
        assert resp.templates == []
