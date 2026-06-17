"""Unit tests for gene router error response sanitization."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from src.application.schemas.gene_schemas import (
    GeneCreate,
    GeneReviewCreate,
    GeneUpdate,
    GenomeCreate,
)
from src.domain.model.gene.enums import EvolutionEventType, InstanceGeneStatus
from src.infrastructure.adapters.primary.web.routers import genes


class _FailingGeneService:
    async def create_gene(self, **_kwargs: object) -> object:
        raise ValueError("gene slug secret-gene already exists")

    async def update_gene(self, *_args: object, **_kwargs: object) -> object:
        raise ValueError("gene gene-secret not found")

    async def get_gene(self, *_args: object, **_kwargs: object) -> object | None:
        return None

    async def create_evolution_event(self, **_kwargs: object) -> object:
        raise AssertionError("create_evolution_event should not run before access checks")

    async def create_genome(self, **_kwargs: object) -> object:
        raise ValueError("genome slug secret-genome already exists")

    async def get_genome(self, *_args: object, **_kwargs: object) -> object | None:
        return None

    async def get_instance_gene(self, *_args: object, **_kwargs: object) -> object | None:
        return None

    async def list_evolution_events(self, **_kwargs: object) -> list[object]:
        raise ValueError("invalid event filter secret-instance")

    async def list_evolution_events_with_total(self, **_kwargs: object) -> tuple[list[object], int]:
        raise ValueError("invalid event filter secret-instance")

    async def get_evolution_event(self, *_args: object, **_kwargs: object) -> object | None:
        return None

    async def create_gene_review(self, **_kwargs: object) -> object:
        raise ValueError("gene review secret invalid")

    async def delete_gene_review(self, **_kwargs: object) -> None:
        raise PermissionError("review secret denied")


class _InstanceService:
    async def get_instance(self, instance_id: str) -> object | None:
        if instance_id == "missing-instance":
            return None
        tenant_id = "tenant-2" if instance_id == "foreign-instance" else "tenant-1"
        return SimpleNamespace(id=instance_id, tenant_id=tenant_id)


class _Container:
    def gene_service(self) -> _FailingGeneService:
        return _FailingGeneService()

    def instance_service(self) -> _InstanceService:
        return _InstanceService()


class _InstanceGeneListService(_FailingGeneService):
    async def list_instance_genes(self, instance_id: str) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                id="instance-gene-1",
                instance_id=instance_id,
                gene_id="gene-1",
                genome_id=None,
                status=InstanceGeneStatus.installed,
                installed_version="1.2.3",
                config_snapshot={"mode": "strict"},
                usage_count=7,
                installed_at=datetime(2026, 1, 1, tzinfo=UTC),
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        ]


class _InstanceGeneListContainer(_Container):
    def gene_service(self) -> _InstanceGeneListService:
        return _InstanceGeneListService()


class _EvolutionAccessGeneService(_FailingGeneService):
    async def get_gene(self, gene_id: str, *_args: object, **_kwargs: object) -> object | None:
        if gene_id == "missing-gene":
            return None
        tenant_id = "tenant-2" if gene_id == "foreign-gene" else "tenant-1"
        return SimpleNamespace(id=gene_id, tenant_id=tenant_id)

    async def get_evolution_event(self, event_id: str) -> object | None:
        instance_id = "foreign-instance" if event_id == "foreign-event" else "instance-1"
        return SimpleNamespace(instance_id=instance_id)


class _EvolutionAccessContainer(_Container):
    def gene_service(self) -> _EvolutionAccessGeneService:
        return _EvolutionAccessGeneService()


class _ReviewFailingGeneService(_FailingGeneService):
    async def get_gene(self, gene_id: str, *_args: object, **_kwargs: object) -> object | None:
        return SimpleNamespace(id=gene_id, tenant_id="tenant-1")


class _ReviewFailingContainer(_Container):
    def gene_service(self) -> _ReviewFailingGeneService:
        return _ReviewFailingGeneService()


class _UpdateValidationGeneService(_FailingGeneService):
    async def get_gene(self, gene_id: str, *_args: object, **_kwargs: object) -> object | None:
        return SimpleNamespace(id=gene_id, tenant_id="tenant-1")

    async def update_gene(self, *_args: object, **_kwargs: object) -> object:
        raise ValueError("gene slug secret duplicate")

    async def get_genome(self, genome_id: str, *_args: object, **_kwargs: object) -> object | None:
        return SimpleNamespace(id=genome_id, tenant_id="tenant-1")

    async def update_genome(self, *_args: object, **_kwargs: object) -> object:
        raise ValueError("genome slug secret duplicate")


class _UpdateValidationContainer(_Container):
    def gene_service(self) -> _UpdateValidationGeneService:
        return _UpdateValidationGeneService()


@pytest.fixture(autouse=True)
def patch_container(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(genes, "get_container_with_db", lambda _request, _db: _Container())


@pytest.mark.unit
async def test_create_gene_sanitizes_value_errors() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await genes.create_gene(
            request=SimpleNamespace(),
            data=GeneCreate(name="Gene", slug="secret-gene"),
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
            db=SimpleNamespace(commit=None),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid gene request"
    assert "secret-gene" not in str(exc_info.value.detail)


@pytest.mark.unit
async def test_create_gene_rejects_mismatched_payload_tenant() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await genes.create_gene(
            request=SimpleNamespace(),
            data=GeneCreate(name="Gene", slug="gene", tenant_id="tenant-2"),
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
            db=SimpleNamespace(commit=None),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Access denied"


@pytest.mark.unit
async def test_update_gene_sanitizes_missing_gene_id() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await genes.update_gene(
            request=SimpleNamespace(),
            gene_id="gene-secret",
            data=GeneUpdate(name="Updated"),
            tenant_id="tenant-1",
            db=SimpleNamespace(commit=None),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Gene not found"
    assert "gene-secret" not in str(exc_info.value.detail)


@pytest.mark.unit
async def test_update_gene_reports_validation_errors_as_bad_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _UpdateValidationContainer(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await genes.update_gene(
            request=SimpleNamespace(),
            gene_id="gene-1",
            data=GeneUpdate(slug="secret-slug"),
            tenant_id="tenant-1",
            db=SimpleNamespace(commit=None),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid gene request"
    assert "secret" not in str(exc_info.value.detail)


@pytest.mark.unit
async def test_get_gene_sanitizes_missing_gene_id() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await genes.get_gene(
            request=SimpleNamespace(),
            gene_id="gene-secret",
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Gene not found"


@pytest.mark.unit
async def test_get_gene_hides_foreign_gene(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _EvolutionAccessContainer(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await genes.get_gene(
            request=SimpleNamespace(),
            gene_id="foreign-gene",
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Gene not found"


@pytest.mark.unit
async def test_create_genome_sanitizes_value_errors() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await genes.create_genome(
            request=SimpleNamespace(),
            data=GenomeCreate(name="Genome", slug="secret-genome"),
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
            db=SimpleNamespace(commit=None),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid gene request"
    assert "secret-genome" not in str(exc_info.value.detail)


@pytest.mark.unit
async def test_get_genome_sanitizes_missing_genome_id() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await genes.get_genome(
            request=SimpleNamespace(),
            genome_id="genome-secret",
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Genome not found"


@pytest.mark.unit
async def test_update_genome_reports_validation_errors_as_bad_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _UpdateValidationContainer(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await genes.update_genome(
            request=SimpleNamespace(),
            genome_id="genome-1",
            data=genes.GenomeUpdate(slug="secret-slug"),
            tenant_id="tenant-1",
            db=SimpleNamespace(commit=None),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid gene request"
    assert "secret" not in str(exc_info.value.detail)


@pytest.mark.unit
async def test_get_instance_gene_sanitizes_missing_instance_gene_id() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await genes.get_instance_gene(
            request=SimpleNamespace(),
            instance_id="instance-1",
            instance_gene_id="instance-gene-secret",
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Instance gene not found"


@pytest.mark.unit
async def test_list_instance_genes_enriches_gene_display_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _InstanceGeneListContainer(),
    )
    metadata_result = Mock()
    metadata_result.all.return_value = [
        ("gene-1", "Code Review", "Reviews code changes", "tool"),
    ]
    db = SimpleNamespace(execute=AsyncMock(return_value=metadata_result))

    response = await genes.list_instance_genes(
        request=SimpleNamespace(),
        instance_id="instance-1",
        tenant_id="tenant-1",
        db=db,
    )

    assert response.total == 1
    item = response.items[0]
    assert item.gene_id == "gene-1"
    assert item.gene_name == "Code Review"
    assert item.gene_description == "Reviews code changes"
    assert item.gene_category == "tool"
    db.execute.assert_awaited_once()


@pytest.mark.unit
async def test_list_evolution_events_sanitizes_value_errors() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await genes.list_evolution_events(
            request=SimpleNamespace(),
            instance_id="secret-instance",
            gene_id=None,
            event_type=None,
            page=1,
            page_size=20,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid evolution event request"
    assert "secret-instance" not in str(exc_info.value.detail)


@pytest.mark.unit
async def test_list_evolution_events_hides_foreign_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _EvolutionAccessContainer(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await genes.list_evolution_events(
            request=SimpleNamespace(),
            instance_id="foreign-instance",
            gene_id=None,
            event_type=None,
            page=1,
            page_size=20,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Evolution event not found"


@pytest.mark.unit
async def test_list_evolution_events_hides_foreign_gene(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _EvolutionAccessContainer(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await genes.list_evolution_events(
            request=SimpleNamespace(),
            instance_id=None,
            gene_id="foreign-gene",
            event_type=None,
            page=1,
            page_size=20,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Gene not found"


@pytest.mark.unit
async def test_create_evolution_event_hides_foreign_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _EvolutionAccessContainer(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await genes.create_evolution_event(
            request=SimpleNamespace(),
            data=genes.EvolutionEventCreateRequest(
                instance_id="foreign-instance",
                event_type=EvolutionEventType.learned,
            ),
            tenant_id="tenant-1",
            db=SimpleNamespace(commit=None),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Evolution event not found"


@pytest.mark.unit
async def test_get_evolution_event_sanitizes_missing_event_id() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await genes.get_evolution_event(
            request=SimpleNamespace(),
            event_id="event-secret",
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Evolution event not found"


@pytest.mark.unit
async def test_get_evolution_event_hides_foreign_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _EvolutionAccessContainer(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await genes.get_evolution_event(
            request=SimpleNamespace(),
            event_id="foreign-event",
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Evolution event not found"


@pytest.mark.unit
async def test_create_gene_review_sanitizes_value_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _ReviewFailingContainer(),
    )
    with pytest.raises(HTTPException) as exc_info:
        await genes.create_gene_review(
            request=SimpleNamespace(),
            gene_id="gene-secret",
            data=GeneReviewCreate(rating=5, content="solid"),
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
            db=SimpleNamespace(commit=None),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid gene request"


@pytest.mark.unit
async def test_delete_gene_review_sanitizes_permission_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _ReviewFailingContainer(),
    )
    with pytest.raises(HTTPException) as exc_info:
        await genes.delete_gene_review(
            request=SimpleNamespace(),
            gene_id="gene-secret",
            review_id="review-secret",
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
            db=SimpleNamespace(commit=None),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Access denied"
    assert "review-secret" not in str(exc_info.value.detail)
