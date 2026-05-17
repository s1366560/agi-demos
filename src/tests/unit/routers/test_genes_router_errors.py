"""Unit tests for gene router error response sanitization."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.application.schemas.gene_schemas import (
    GeneCreate,
    GeneReviewCreate,
    GeneUpdate,
    GenomeCreate,
)
from src.infrastructure.adapters.primary.web.routers import genes


class _FailingGeneService:
    async def create_gene(self, **_kwargs: object) -> object:
        raise ValueError("gene slug secret-gene already exists")

    async def update_gene(self, *_args: object, **_kwargs: object) -> object:
        raise ValueError("gene gene-secret not found")

    async def get_gene(self, *_args: object, **_kwargs: object) -> object | None:
        return None

    async def create_genome(self, **_kwargs: object) -> object:
        raise ValueError("genome slug secret-genome already exists")

    async def get_genome(self, *_args: object, **_kwargs: object) -> object | None:
        return None

    async def get_instance_gene(self, *_args: object, **_kwargs: object) -> object | None:
        return None

    async def list_evolution_events(self, **_kwargs: object) -> list[object]:
        raise ValueError("invalid event filter secret-instance")

    async def get_evolution_event(self, *_args: object, **_kwargs: object) -> object | None:
        return None

    async def create_gene_review(self, **_kwargs: object) -> object:
        raise ValueError("gene review secret invalid")

    async def delete_gene_review(self, **_kwargs: object) -> None:
        raise PermissionError("review secret denied")


class _Container:
    def gene_service(self) -> _FailingGeneService:
        return _FailingGeneService()


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
async def test_create_gene_review_sanitizes_value_errors() -> None:
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
async def test_delete_gene_review_sanitizes_permission_errors() -> None:
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
