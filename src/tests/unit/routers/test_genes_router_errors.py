"""Unit tests for gene router error response sanitization."""

from __future__ import annotations

import inspect
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
        deleted_at = datetime(2026, 1, 2, tzinfo=UTC) if instance_id == "deleted-instance" else None
        tenant_id = "tenant-2" if instance_id == "foreign-instance" else "tenant-1"
        return SimpleNamespace(id=instance_id, tenant_id=tenant_id, deleted_at=deleted_at)


class _Container:
    def gene_service(self) -> _FailingGeneService:
        return _FailingGeneService()

    def instance_service(self) -> _InstanceService:
        return _InstanceService()


def _gene_entity(
    *,
    gene_id: str,
    tenant_id: str | None,
    is_published: bool = True,
    visibility: str = "public",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=gene_id,
        name="Global Gene" if tenant_id is None else "Tenant Gene",
        slug=gene_id,
        tenant_id=tenant_id,
        description=None,
        short_description=None,
        category=None,
        tags=[],
        source="official",
        source_ref=None,
        icon=None,
        version="1.0.0",
        manifest={},
        dependencies=[],
        synergies=[],
        parent_gene_id=None,
        visibility=visibility,
        install_count=0,
        avg_rating=None,
        effectiveness_score=None,
        is_featured=False,
        review_status=None,
        is_published=is_published,
        created_by="user-1",
        created_by_instance_id=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=None,
    )


def _genome_entity(
    *,
    genome_id: str,
    tenant_id: str | None,
    is_published: bool = True,
    visibility: str = "public",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=genome_id,
        name="Global Genome" if tenant_id is None else "Tenant Genome",
        slug=genome_id,
        tenant_id=tenant_id,
        description=None,
        short_description=None,
        icon=None,
        gene_slugs=[],
        config_override={},
        visibility=visibility,
        install_count=0,
        avg_rating=None,
        is_featured=False,
        is_published=is_published,
        created_by="user-1",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=None,
    )


class _InstanceGeneListService(_FailingGeneService):
    async def list_instance_genes_with_summary(
        self,
        instance_id: str,
        limit: int,
        offset: int,
        search: str | None = None,
        tenant_id: str | None = None,
    ) -> tuple[list[SimpleNamespace], int, int, int]:
        assert limit == 25
        assert offset == 0
        assert search is None
        assert tenant_id == "tenant-1"
        return (
            [
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
                ),
                SimpleNamespace(
                    id="instance-gene-2",
                    instance_id=instance_id,
                    gene_id="global-gene",
                    genome_id=None,
                    status=InstanceGeneStatus.installed,
                    installed_version="2.0.0",
                    config_snapshot={},
                    usage_count=10,
                    installed_at=datetime(2026, 1, 1, tzinfo=UTC),
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                ),
            ],
            3,
            2,
            17,
        )


class _InstanceGeneListContainer(_Container):
    def gene_service(self) -> _InstanceGeneListService:
        return _InstanceGeneListService()


class _GeneListService(_FailingGeneService):
    async def list_genes_with_total(self, **kwargs: object) -> tuple[list[SimpleNamespace], int]:
        assert kwargs["tenant_id"] == "tenant-1"
        assert kwargs["include_global"] is True
        assert kwargs["slugs"] == ["code-review", "test-writer"]
        return (
            [
                SimpleNamespace(
                    id="gene-1",
                    name="Code Review",
                    slug="code-review",
                    tenant_id="tenant-1",
                    description="Reviews code",
                    short_description="Review code",
                    category="tool",
                    tags=[],
                    source="manual",
                    source_ref=None,
                    icon=None,
                    version="1.0.0",
                    manifest={},
                    dependencies=[],
                    synergies=[],
                    parent_gene_id=None,
                    visibility="public",
                    install_count=0,
                    avg_rating=None,
                    effectiveness_score=None,
                    is_featured=False,
                    review_status=None,
                    is_published=True,
                    created_by="user-1",
                    created_by_instance_id=None,
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                    updated_at=None,
                )
            ],
            1,
        )


class _GeneListContainer(_Container):
    def gene_service(self) -> _GeneListService:
        return _GeneListService()


class _InvalidVisibilityListService(_FailingGeneService):
    async def list_genes_with_total(self, **_kwargs: object) -> tuple[list[SimpleNamespace], int]:
        raise ValueError("invalid visibility secret")

    async def list_genomes_with_total(self, **_kwargs: object) -> tuple[list[SimpleNamespace], int]:
        raise ValueError("invalid visibility secret")


class _InvalidVisibilityListContainer(_Container):
    def gene_service(self) -> _InvalidVisibilityListService:
        return _InvalidVisibilityListService()


class _GenomeListService(_FailingGeneService):
    async def list_genomes_with_total(self, **kwargs: object) -> tuple[list[SimpleNamespace], int]:
        assert kwargs["tenant_id"] == "tenant-1"
        assert kwargs["include_global"] is True
        assert kwargs["search"] == "review"
        assert kwargs["visibility"] == "public"
        assert kwargs["is_published"] is True
        return ([_genome_entity(genome_id="global-genome", tenant_id=None)], 1)


class _GenomeListContainer(_Container):
    def gene_service(self) -> _GenomeListService:
        return _GenomeListService()


class _GenomeInstallService(_FailingGeneService):
    async def get_genome(self, genome_id: str, *_args: object, **_kwargs: object) -> object | None:
        return _genome_entity(genome_id=genome_id, tenant_id=None)

    async def install_genome(self, **kwargs: object) -> list[SimpleNamespace]:
        assert kwargs == {
            "instance_id": "instance-1",
            "genome_id": "global-genome",
            "tenant_id": "tenant-1",
            "config_snapshot": {"code-review": {"mode": "strict"}},
        }
        return [
            SimpleNamespace(
                id="instance-gene-1",
                instance_id="instance-1",
                gene_id="gene-1",
                genome_id="global-genome",
                status=InstanceGeneStatus.installed,
                installed_version="1.0.0",
                config_snapshot={"mode": "strict"},
                usage_count=0,
                installed_at=datetime(2026, 1, 1, tzinfo=UTC),
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                deleted_at=None,
            )
        ]


class _GenomeInstallContainer(_Container):
    def gene_service(self) -> _GenomeInstallService:
        return _GenomeInstallService()


class _GeneInstallService(_FailingGeneService):
    async def get_gene(self, gene_id: str, *_args: object, **_kwargs: object) -> object | None:
        return SimpleNamespace(
            id=gene_id,
            tenant_id="tenant-1",
            name="Code Review",
            description="Reviews code changes",
            category="tool",
            visibility="public",
            is_published=True,
        )

    async def install_gene(self, **kwargs: object) -> SimpleNamespace:
        assert kwargs == {
            "instance_id": "instance-1",
            "gene_id": "gene-1",
            "config_snapshot": {"mode": "strict"},
        }
        return SimpleNamespace(
            id="instance-gene-1",
            instance_id="instance-1",
            gene_id="gene-1",
            genome_id=None,
            status=InstanceGeneStatus.installed,
            installed_version="1.0.0",
            config_snapshot={"mode": "strict"},
            usage_count=0,
            installed_at=datetime(2026, 1, 1, tzinfo=UTC),
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            deleted_at=None,
        )


class _GeneInstallContainer(_Container):
    def gene_service(self) -> _GeneInstallService:
        return _GeneInstallService()


class _EvolutionAccessGeneService(_FailingGeneService):
    async def get_gene(self, gene_id: str, *_args: object, **_kwargs: object) -> object | None:
        if gene_id == "missing-gene":
            return None
        if gene_id == "global-gene":
            return _gene_entity(gene_id=gene_id, tenant_id=None)
        if gene_id == "global-draft-gene":
            return _gene_entity(gene_id=gene_id, tenant_id=None, is_published=False)
        tenant_id = "tenant-2" if gene_id == "foreign-gene" else "tenant-1"
        return _gene_entity(gene_id=gene_id, tenant_id=tenant_id)

    async def get_genome(self, genome_id: str, *_args: object, **_kwargs: object) -> object | None:
        if genome_id == "missing-genome":
            return None
        if genome_id == "global-genome":
            return _genome_entity(genome_id=genome_id, tenant_id=None)
        if genome_id == "global-draft-genome":
            return _genome_entity(genome_id=genome_id, tenant_id=None, is_published=False)
        tenant_id = "tenant-2" if genome_id == "foreign-genome" else "tenant-1"
        return _genome_entity(genome_id=genome_id, tenant_id=tenant_id)

    async def get_evolution_event(self, event_id: str) -> object | None:
        instance_id = "foreign-instance" if event_id == "foreign-event" else "instance-1"
        return SimpleNamespace(instance_id=instance_id)


class _EvolutionAccessContainer(_Container):
    def gene_service(self) -> _EvolutionAccessGeneService:
        return _EvolutionAccessGeneService()


class _DeletedInstanceGeneService(_FailingGeneService):
    async def get_instance_gene(self, *_args: object, **_kwargs: object) -> object | None:
        return SimpleNamespace(
            id="instance-gene-deleted",
            instance_id="instance-1",
            deleted_at=datetime(2026, 1, 2, tzinfo=UTC),
        )


class _DeletedInstanceGeneContainer(_Container):
    def gene_service(self) -> _DeletedInstanceGeneService:
        return _DeletedInstanceGeneService()


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


def _tenant_dependency(handler: object) -> object:
    default = inspect.signature(handler).parameters["tenant_id"].default
    return getattr(default, "dependency", None)


@pytest.mark.unit
@pytest.mark.parametrize(
    "handler_name",
    [
        "create_gene",
        "update_gene",
        "delete_gene",
        "publish_gene",
        "unpublish_gene",
        "create_genome",
        "update_genome",
        "delete_genome",
        "publish_genome",
        "unpublish_genome",
        "install_gene",
        "install_genome",
        "uninstall_gene",
        "create_evolution_event",
    ],
)
def test_gene_write_routes_require_admin_tenant_dependency(handler_name: str) -> None:
    assert (
        _tenant_dependency(getattr(genes, handler_name)) is genes._get_selected_gene_admin_tenant_id
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "handler_name",
    [
        "list_genes",
        "get_gene",
        "list_genomes",
        "get_genome",
        "list_instance_genes",
        "get_instance_gene",
        "rate_gene",
        "list_gene_ratings",
        "list_genome_ratings",
        "rate_genome",
        "list_evolution_events",
        "get_evolution_event",
        "list_gene_reviews",
        "create_gene_review",
        "delete_gene_review",
    ],
)
def test_gene_member_routes_keep_member_tenant_dependency(handler_name: str) -> None:
    assert _tenant_dependency(getattr(genes, handler_name)) is genes._get_selected_gene_tenant_id


@pytest.mark.unit
async def test_selected_gene_admin_tenant_requires_admin_for_selected_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[object, object, str, bool]] = []

    async def require_access(
        db: object,
        user: object,
        tenant_id: str,
        *,
        require_admin: bool = False,
    ) -> None:
        captured.append((db, user, tenant_id, require_admin))

    monkeypatch.setattr(genes, "require_tenant_access", require_access)
    db = SimpleNamespace(name="db")
    user = SimpleNamespace(id="user-1")

    tenant_id = await genes._get_selected_gene_admin_tenant_id(
        selected_tenant_id="tenant-2",
        fallback_tenant_id="tenant-1",
        current_user=user,
        db=db,
    )

    assert tenant_id == "tenant-2"
    assert captured == [(db, user, "tenant-2", True)]


@pytest.mark.unit
async def test_selected_gene_admin_tenant_requires_admin_for_fallback_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[object, object, str, bool]] = []

    async def require_access(
        db: object,
        user: object,
        tenant_id: str,
        *,
        require_admin: bool = False,
    ) -> None:
        captured.append((db, user, tenant_id, require_admin))

    monkeypatch.setattr(genes, "require_tenant_access", require_access)
    db = SimpleNamespace(name="db")
    user = SimpleNamespace(id="user-1")

    tenant_id = await genes._get_selected_gene_admin_tenant_id(
        selected_tenant_id=None,
        fallback_tenant_id="tenant-1",
        current_user=user,
        db=db,
    )

    assert tenant_id == "tenant-1"
    assert captured == [(db, user, "tenant-1", True)]


@pytest.mark.unit
async def test_selected_gene_member_tenant_keeps_member_access_for_selected_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[object, object, str, bool]] = []

    async def require_access(
        db: object,
        user: object,
        tenant_id: str,
        *,
        require_admin: bool = False,
    ) -> None:
        captured.append((db, user, tenant_id, require_admin))

    monkeypatch.setattr(genes, "require_tenant_access", require_access)
    db = SimpleNamespace(name="db")
    user = SimpleNamespace(id="user-1")

    tenant_id = await genes._get_selected_gene_tenant_id(
        selected_tenant_id="tenant-2",
        fallback_tenant_id="tenant-1",
        current_user=user,
        db=db,
    )

    assert tenant_id == "tenant-2"
    assert captured == [(db, user, "tenant-2", False)]


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
async def test_get_gene_allows_published_global_gene(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _EvolutionAccessContainer(),
    )

    response = await genes.get_gene(
        request=SimpleNamespace(),
        gene_id="global-gene",
        tenant_id="tenant-1",
        db=SimpleNamespace(),
    )

    assert response.id == "global-gene"
    assert response.tenant_id is None


@pytest.mark.unit
async def test_get_gene_hides_unpublished_global_gene(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _EvolutionAccessContainer(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await genes.get_gene(
            request=SimpleNamespace(),
            gene_id="global-draft-gene",
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Gene not found"


@pytest.mark.unit
async def test_update_gene_hides_global_gene_from_tenant_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _EvolutionAccessContainer(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await genes.update_gene(
            request=SimpleNamespace(),
            gene_id="global-gene",
            data=GeneUpdate(name="Updated"),
            tenant_id="tenant-1",
            db=SimpleNamespace(commit=AsyncMock()),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Gene not found"


@pytest.mark.unit
async def test_list_genes_splits_comma_separated_slug_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _GeneListContainer(),
    )

    response = await genes.list_genes(
        request=SimpleNamespace(),
        page=1,
        page_size=20,
        category=None,
        search=None,
        slugs=" code-review, test-writer,, ",
        visibility=None,
        is_published=None,
        exclude_installed_instance_id=None,
        tenant_id="tenant-1",
        db=SimpleNamespace(),
    )

    assert response.total == 1
    assert response.genes[0].slug == "code-review"


@pytest.mark.unit
async def test_list_genes_sanitizes_invalid_visibility_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _InvalidVisibilityListContainer(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await genes.list_genes(
            request=SimpleNamespace(),
            page=1,
            page_size=20,
            category=None,
            search=None,
            slugs=None,
            visibility="not-a-visibility",
            is_published=None,
            exclude_installed_instance_id=None,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid gene request"


@pytest.mark.unit
async def test_list_genomes_passes_global_inclusion_to_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _GenomeListContainer(),
    )

    response = await genes.list_genomes(
        request=SimpleNamespace(),
        page=1,
        page_size=20,
        search="review",
        visibility="public",
        is_published=True,
        tenant_id="tenant-1",
        db=SimpleNamespace(),
    )

    assert response.total == 1
    assert response.genomes[0].id == "global-genome"


@pytest.mark.unit
async def test_install_gene_includes_access_checked_gene_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = AsyncMock()
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _GeneInstallContainer(),
    )

    response = await genes.install_gene(
        request=SimpleNamespace(),
        instance_id="instance-1",
        data=genes.InstallGeneRequest(gene_id="gene-1", config={"mode": "strict"}),
        tenant_id="tenant-1",
        db=SimpleNamespace(commit=commit),
    )

    assert response.gene_id == "gene-1"
    assert response.gene_name == "Code Review"
    assert response.gene_description == "Reviews code changes"
    assert response.gene_category == "tool"
    commit.assert_awaited_once()


@pytest.mark.unit
async def test_list_genomes_sanitizes_invalid_visibility_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _InvalidVisibilityListContainer(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await genes.list_genomes(
            request=SimpleNamespace(),
            page=1,
            page_size=20,
            search=None,
            visibility="not-a-visibility",
            is_published=None,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid gene request"


@pytest.mark.unit
async def test_install_genome_allows_published_global_genome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = AsyncMock()
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _GenomeInstallContainer(),
    )
    metadata_result = Mock()
    metadata_result.all.return_value = [("gene-1", "Code Review", "Reviews code changes", "tool")]
    db = SimpleNamespace(commit=commit, execute=AsyncMock(return_value=metadata_result))

    response = await genes.install_genome(
        request=SimpleNamespace(),
        instance_id="instance-1",
        genome_id="global-genome",
        data=genes.InstallGenomeRequest(config={"code-review": {"mode": "strict"}}),
        tenant_id="tenant-1",
        db=db,
    )

    assert response.instance_id == "instance-1"
    assert response.genome_id == "global-genome"
    assert response.total == 1
    assert response.items[0].genome_id == "global-genome"
    assert response.items[0].gene_name == "Code Review"
    assert response.items[0].gene_description == "Reviews code changes"
    assert response.items[0].gene_category == "tool"
    db.execute.assert_awaited_once()
    commit.assert_awaited_once()


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
async def test_get_genome_allows_published_global_genome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _EvolutionAccessContainer(),
    )

    response = await genes.get_genome(
        request=SimpleNamespace(),
        genome_id="global-genome",
        tenant_id="tenant-1",
        db=SimpleNamespace(),
    )

    assert response.id == "global-genome"
    assert response.tenant_id is None


@pytest.mark.unit
async def test_get_genome_hides_unpublished_global_genome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _EvolutionAccessContainer(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await genes.get_genome(
            request=SimpleNamespace(),
            genome_id="global-draft-genome",
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Genome not found"


@pytest.mark.unit
async def test_unpublish_genome_sanitizes_missing_genome_id() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await genes.unpublish_genome(
            request=SimpleNamespace(),
            genome_id="genome-secret",
            tenant_id="tenant-1",
            db=SimpleNamespace(commit=None),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Genome not found"


@pytest.mark.unit
async def test_update_genome_hides_global_genome_from_tenant_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _EvolutionAccessContainer(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await genes.update_genome(
            request=SimpleNamespace(),
            genome_id="global-genome",
            data=genes.GenomeUpdate(name="Updated"),
            tenant_id="tenant-1",
            db=SimpleNamespace(commit=AsyncMock()),
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
async def test_get_instance_gene_hides_deleted_instance_gene(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        genes,
        "get_container_with_db",
        lambda _request, _db: _DeletedInstanceGeneContainer(),
    )

    with pytest.raises(HTTPException) as exc_info:
        await genes.get_instance_gene(
            request=SimpleNamespace(),
            instance_id="instance-1",
            instance_gene_id="instance-gene-deleted",
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Instance gene not found"


@pytest.mark.unit
async def test_get_instance_gene_hides_missing_instance_as_instance_gene_not_found() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await genes.get_instance_gene(
            request=SimpleNamespace(),
            instance_id="missing-instance",
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
        ("global-gene", "Global Review", "Official shared gene", "official"),
    ]
    db = SimpleNamespace(execute=AsyncMock(return_value=metadata_result))

    response = await genes.list_instance_genes(
        request=SimpleNamespace(),
        instance_id="instance-1",
        limit=25,
        offset=0,
        search=None,
        tenant_id="tenant-1",
        db=db,
    )

    assert response.total == 3
    assert response.active_total == 2
    assert response.usage_total == 17
    assert response.limit == 25
    assert response.offset == 0
    assert response.has_more is True
    item = response.items[0]
    assert item.gene_id == "gene-1"
    assert item.gene_name == "Code Review"
    assert item.gene_description == "Reviews code changes"
    assert item.gene_category == "tool"
    global_item = response.items[1]
    assert global_item.gene_id == "global-gene"
    assert global_item.gene_name == "Global Review"
    db.execute.assert_awaited_once()
    metadata_statement = db.execute.await_args.args[0]
    compiled_statement = str(metadata_statement.compile(compile_kwargs={"literal_binds": True}))
    assert "gene_market.tenant_id = 'tenant-1'" in compiled_statement
    assert "gene_market.tenant_id IS NULL" in compiled_statement


@pytest.mark.unit
async def test_list_instance_genes_hides_deleted_instance() -> None:
    with pytest.raises(HTTPException) as exc_info:
        await genes.list_instance_genes(
            request=SimpleNamespace(),
            instance_id="deleted-instance",
            limit=25,
            offset=0,
            search=None,
            tenant_id="tenant-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Instance not found"


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
