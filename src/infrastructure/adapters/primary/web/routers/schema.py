"""Project schema API endpoints backed exclusively by a pinned V2 generation."""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import Response

from src.application.schemas.schema import (
    EdgeTypeCreate,
    EdgeTypeMapCreate,
    EdgeTypeMapResponse,
    EdgeTypeResponse,
    EdgeTypeUpdate,
    EntityTypeCreate,
    EntityTypeResponse,
    EntityTypeUpdate,
)
from src.domain.model.project_schema.http_mutations import SchemaHttpReceipt
from src.domain.model.project_schema.validation import ProjectSchemaError
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.schema_documents import (
    router as document_router,
)
from src.infrastructure.adapters.primary.web.schema_application_authority_v2 import (
    SchemaApplicationAuthorityV2,
    schema_application_authority_dependency_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.adapters.secondary.schema.active_schema_reads import SchemaCommandRequiredV2
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.schema_services import (
    SchemaAccessDeniedV2,
    SchemaEdgeMapConflictV2,
    SchemaEdgeMapNotFoundV2,
    SchemaEdgeTypeConflictV2,
    SchemaEdgeTypeNotFoundV2,
    SchemaEntityTypeConflictV2,
    SchemaEntityTypeNotFoundV2,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/schema", tags=["schema"])
router.include_router(document_router)


async def _schema_call[ResultT](operation: Awaitable[ResultT]) -> ResultT:
    try:
        return await operation
    except SchemaCommandRequiredV2 as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": error.code,
                "message": _("Active project schemas require an explicit schema command"),
            },
        ) from error
    except SchemaAccessDeniedV2 as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_("Access denied to project"),
        ) from error
    except SchemaEntityTypeConflictV2 as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Entity type with this name already exists"),
        ) from error
    except SchemaEntityTypeNotFoundV2 as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Entity type not found"),
        ) from error
    except SchemaEdgeTypeConflictV2 as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("Edge type with this name already exists"),
        ) from error
    except SchemaEdgeTypeNotFoundV2 as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Edge type not found"),
        ) from error
    except SchemaEdgeMapConflictV2 as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=_("This mapping already exists"),
        ) from error
    except SchemaEdgeMapNotFoundV2 as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=_("Mapping not found"),
        ) from error


async def _schema_mutation_call(operation: Awaitable[Any]) -> Any:
    try:
        result = await _schema_call(operation)
    except ProjectSchemaError as error:
        status_by_code = {
            "project_schema_active_required": 409,
            "project_schema_precondition_invalid": 422,
            "project_schema_mutation_invalid": 422,
            "project_schema_revision_conflict": 409,
            "project_schema_change_id_reused": 409,
            "project_schema_deleted": 409,
            "project_schema_type_referenced": 409,
            "project_schema_entity_type_conflict": 400,
            "project_schema_edge_type_conflict": 400,
            "project_schema_mapping_conflict": 400,
            "project_schema_entity_type_not_found": 404,
            "project_schema_edge_type_not_found": 404,
            "project_schema_mapping_not_found": 404,
            "project_schema_mapping_reference_not_found": 404,
        }
        if error.code not in status_by_code:
            raise
        raise HTTPException(
            status_code=status_by_code[error.code],
            detail={
                "code": error.code,
                "message": _("Project schema mutation was rejected"),
            },
        ) from error
    if isinstance(result, SchemaHttpReceipt):
        value = result.to_dict()
        return Response(
            content=value["body"],
            status_code=value["status"],
            headers=value["headers"],
            media_type="application/json" if value["status"] != 204 else None,
        )
    return result


@router.get("/entities", response_model=list[EntityTypeResponse])
async def list_entity_types(
    project_id: str,
    current_user: User = Depends(get_current_user),
    schema_application: SchemaApplicationAuthorityV2 = Depends(
        schema_application_authority_dependency_v2
    ),
) -> Any:
    return await _schema_call(
        schema_application.services.list_entity_types(
            user_id=current_user.id,
            project_id=project_id,
        )
    )


@router.post("/entities", response_model=EntityTypeResponse)
async def create_entity_type(
    project_id: str,
    entity_data: EntityTypeCreate,
    current_user: User = Depends(get_current_user),
    schema_application: SchemaApplicationAuthorityV2 = Depends(
        schema_application_authority_dependency_v2
    ),
    expected_revision: Annotated[
        str | None, Header(alias="X-Project-Schema-Expected-Revision")
    ] = None,
    change_id: Annotated[str | None, Header(alias="X-Project-Schema-Change-Id")] = None,
) -> Any:
    return await _schema_mutation_call(
        schema_application.services.create_entity_type(
            user_id=current_user.id,
            project_id=project_id,
            expected_revision=expected_revision,
            change_id=change_id,
            data=entity_data,
        )
    )


@router.put("/entities/{entity_id}", response_model=EntityTypeResponse)
async def update_entity_type(
    project_id: str,
    entity_id: str,
    entity_data: EntityTypeUpdate,
    current_user: User = Depends(get_current_user),
    schema_application: SchemaApplicationAuthorityV2 = Depends(
        schema_application_authority_dependency_v2
    ),
    expected_revision: Annotated[
        str | None, Header(alias="X-Project-Schema-Expected-Revision")
    ] = None,
    change_id: Annotated[str | None, Header(alias="X-Project-Schema-Change-Id")] = None,
) -> Any:
    return await _schema_mutation_call(
        schema_application.services.update_entity_type(
            user_id=current_user.id,
            project_id=project_id,
            expected_revision=expected_revision,
            change_id=change_id,
            entity_id=entity_id,
            data=entity_data,
        )
    )


@router.delete("/entities/{entity_id}", status_code=204, response_class=Response)
async def delete_entity_type(
    project_id: str,
    entity_id: str,
    current_user: User = Depends(get_current_user),
    schema_application: SchemaApplicationAuthorityV2 = Depends(
        schema_application_authority_dependency_v2
    ),
    expected_revision: Annotated[
        str | None, Header(alias="X-Project-Schema-Expected-Revision")
    ] = None,
    change_id: Annotated[str | None, Header(alias="X-Project-Schema-Change-Id")] = None,
) -> Response:
    result = await _schema_mutation_call(
        schema_application.services.delete_entity_type(
            user_id=current_user.id,
            project_id=project_id,
            expected_revision=expected_revision,
            change_id=change_id,
            entity_id=entity_id,
        )
    )
    if isinstance(result, Response):
        return result
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/edges", response_model=list[EdgeTypeResponse])
async def list_edge_types(
    project_id: str,
    current_user: User = Depends(get_current_user),
    schema_application: SchemaApplicationAuthorityV2 = Depends(
        schema_application_authority_dependency_v2
    ),
) -> Any:
    return await _schema_call(
        schema_application.services.list_edge_types(
            user_id=current_user.id,
            project_id=project_id,
        )
    )


@router.post("/edges", response_model=EdgeTypeResponse)
async def create_edge_type(
    project_id: str,
    edge_data: EdgeTypeCreate,
    current_user: User = Depends(get_current_user),
    schema_application: SchemaApplicationAuthorityV2 = Depends(
        schema_application_authority_dependency_v2
    ),
    expected_revision: Annotated[
        str | None, Header(alias="X-Project-Schema-Expected-Revision")
    ] = None,
    change_id: Annotated[str | None, Header(alias="X-Project-Schema-Change-Id")] = None,
) -> Any:
    return await _schema_mutation_call(
        schema_application.services.create_edge_type(
            user_id=current_user.id,
            project_id=project_id,
            expected_revision=expected_revision,
            change_id=change_id,
            data=edge_data,
        )
    )


@router.put("/edges/{edge_id}", response_model=EdgeTypeResponse)
async def update_edge_type(
    project_id: str,
    edge_id: str,
    edge_data: EdgeTypeUpdate,
    current_user: User = Depends(get_current_user),
    schema_application: SchemaApplicationAuthorityV2 = Depends(
        schema_application_authority_dependency_v2
    ),
    expected_revision: Annotated[
        str | None, Header(alias="X-Project-Schema-Expected-Revision")
    ] = None,
    change_id: Annotated[str | None, Header(alias="X-Project-Schema-Change-Id")] = None,
) -> Any:
    return await _schema_mutation_call(
        schema_application.services.update_edge_type(
            user_id=current_user.id,
            project_id=project_id,
            expected_revision=expected_revision,
            change_id=change_id,
            edge_id=edge_id,
            data=edge_data,
        )
    )


@router.delete("/edges/{edge_id}", status_code=204, response_class=Response)
async def delete_edge_type(
    project_id: str,
    edge_id: str,
    current_user: User = Depends(get_current_user),
    schema_application: SchemaApplicationAuthorityV2 = Depends(
        schema_application_authority_dependency_v2
    ),
    expected_revision: Annotated[
        str | None, Header(alias="X-Project-Schema-Expected-Revision")
    ] = None,
    change_id: Annotated[str | None, Header(alias="X-Project-Schema-Change-Id")] = None,
) -> Response:
    result = await _schema_mutation_call(
        schema_application.services.delete_edge_type(
            user_id=current_user.id,
            project_id=project_id,
            expected_revision=expected_revision,
            change_id=change_id,
            edge_id=edge_id,
        )
    )
    if isinstance(result, Response):
        return result
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/mappings", response_model=list[EdgeTypeMapResponse])
async def list_edge_maps(
    project_id: str,
    current_user: User = Depends(get_current_user),
    schema_application: SchemaApplicationAuthorityV2 = Depends(
        schema_application_authority_dependency_v2
    ),
) -> Any:
    return await _schema_call(
        schema_application.services.list_edge_maps(
            user_id=current_user.id,
            project_id=project_id,
        )
    )


@router.post("/mappings", response_model=EdgeTypeMapResponse)
async def create_edge_map(
    project_id: str,
    map_data: EdgeTypeMapCreate,
    current_user: User = Depends(get_current_user),
    schema_application: SchemaApplicationAuthorityV2 = Depends(
        schema_application_authority_dependency_v2
    ),
    expected_revision: Annotated[
        str | None, Header(alias="X-Project-Schema-Expected-Revision")
    ] = None,
    change_id: Annotated[str | None, Header(alias="X-Project-Schema-Change-Id")] = None,
) -> Any:
    return await _schema_mutation_call(
        schema_application.services.create_edge_map(
            user_id=current_user.id,
            project_id=project_id,
            expected_revision=expected_revision,
            change_id=change_id,
            data=map_data,
        )
    )


@router.delete("/mappings/{map_id}", status_code=204, response_class=Response)
async def delete_edge_map(
    project_id: str,
    map_id: str,
    current_user: User = Depends(get_current_user),
    schema_application: SchemaApplicationAuthorityV2 = Depends(
        schema_application_authority_dependency_v2
    ),
    expected_revision: Annotated[
        str | None, Header(alias="X-Project-Schema-Expected-Revision")
    ] = None,
    change_id: Annotated[str | None, Header(alias="X-Project-Schema-Change-Id")] = None,
) -> Response:
    result = await _schema_mutation_call(
        schema_application.services.delete_edge_map(
            user_id=current_user.id,
            project_id=project_id,
            expected_revision=expected_revision,
            change_id=change_id,
            map_id=map_id,
        )
    )
    if isinstance(result, Response):
        return result
    return Response(status_code=status.HTTP_204_NO_CONTENT)
