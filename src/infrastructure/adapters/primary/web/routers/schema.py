from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    EdgeType,
    EdgeTypeMap,
    EntityType,
    User,
    UserProject,
)

router = APIRouter(prefix="/api/v1/projects/{project_id}/schema", tags=["schema"])


async def verify_project_access(
    project_id: str,
    user: User,
    db: AsyncSession,
    required_role: list[str] | None = None,
) -> Any:
    query = select(UserProject).where(
        and_(UserProject.user_id == user.id, UserProject.project_id == project_id)
    )
    if required_role:
        query = query.where(UserProject.role.in_(required_role))

    result = await db.execute(query)
    user_project = result.scalar_one_or_none()

    if not user_project:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to project"
        )
    return user_project


# --- Entity Types ---


@router.get("/entities", response_model=list[EntityTypeResponse])
async def list_entity_types(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await verify_project_access(project_id, current_user, db)
    result = await db.execute(select(EntityType).where(EntityType.project_id == project_id))
    return result.scalars().all()


@router.post("/entities", response_model=EntityTypeResponse)
async def create_entity_type(
    project_id: str,
    entity_data: EntityTypeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await verify_project_access(project_id, current_user, db, ["owner", "admin", "member"])

    # Check uniqueness
    existing = await db.execute(
        select(EntityType).where(
            and_(
                EntityType.project_id == project_id,
                EntityType.name == entity_data.name,
            )
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Entity type with this name already exists")

    entity_type = EntityType(
        id=str(uuid4()),
        project_id=project_id,
        name=entity_data.name,
        description=entity_data.description,
        schema=entity_data.schema_def,
    )
    db.add(entity_type)
    await db.commit()
    await db.refresh(entity_type)
    return entity_type


@router.put("/entities/{entity_id}", response_model=EntityTypeResponse)
async def update_entity_type(
    project_id: str,
    entity_id: str,
    entity_data: EntityTypeUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await verify_project_access(project_id, current_user, db)
    entity_type = await db.get(EntityType, entity_id)
    if not entity_type or entity_type.project_id != project_id:
        raise HTTPException(status_code=404, detail="Entity type not found")

    if entity_data.description is not None:
        entity_type.description = entity_data.description
    if entity_data.schema_def is not None:
        entity_type.schema = entity_data.schema_def

    await db.commit()
    await db.refresh(entity_type)
    return entity_type


@router.delete("/entities/{entity_id}", status_code=204, response_class=Response)
async def delete_entity_type(
    project_id: str,
    entity_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await verify_project_access(project_id, current_user, db)
    entity_type = await db.get(EntityType, entity_id)
    if not entity_type or entity_type.project_id != project_id:
        raise HTTPException(status_code=404, detail="Entity type not found")

    await db.delete(entity_type)
    await db.commit()
    return Response(status_code=204)


# --- Edge Types ---


@router.get("/edges", response_model=list[EdgeTypeResponse])
async def list_edge_types(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await verify_project_access(project_id, current_user, db)
    result = await db.execute(select(EdgeType).where(EdgeType.project_id == project_id))
    return result.scalars().all()


@router.post("/edges", response_model=EdgeTypeResponse)
async def create_edge_type(
    project_id: str,
    edge_data: EdgeTypeCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await verify_project_access(project_id, current_user, db)

    existing = await db.execute(
        select(EdgeType).where(
            and_(EdgeType.project_id == project_id, EdgeType.name == edge_data.name)
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Edge type with this name already exists")

    edge_type = EdgeType(
        id=str(uuid4()),
        project_id=project_id,
        name=edge_data.name,
        description=edge_data.description,
        schema=edge_data.schema_def,
    )
    db.add(edge_type)
    await db.commit()
    await db.refresh(edge_type)
    return edge_type


@router.put("/edges/{edge_id}", response_model=EdgeTypeResponse)
async def update_edge_type(
    project_id: str,
    edge_id: str,
    edge_data: EdgeTypeUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await verify_project_access(project_id, current_user, db)
    edge_type = await db.get(EdgeType, edge_id)
    if not edge_type or edge_type.project_id != project_id:
        raise HTTPException(status_code=404, detail="Edge type not found")

    if edge_data.description is not None:
        edge_type.description = edge_data.description
    if edge_data.schema_def is not None:
        edge_type.schema = edge_data.schema_def

    await db.commit()
    await db.refresh(edge_type)
    return edge_type


@router.delete("/edges/{edge_id}", status_code=204, response_class=Response)
async def delete_edge_type(
    project_id: str,
    edge_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await verify_project_access(project_id, current_user, db)
    edge_type = await db.get(EdgeType, edge_id)
    if not edge_type or edge_type.project_id != project_id:
        raise HTTPException(status_code=404, detail="Edge type not found")

    await db.delete(edge_type)
    await db.commit()
    return Response(status_code=204)


# --- Edge Maps ---


@router.get("/mappings", response_model=list[EdgeTypeMapResponse])
async def list_edge_maps(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await verify_project_access(project_id, current_user, db)
    result = await db.execute(select(EdgeTypeMap).where(EdgeTypeMap.project_id == project_id))
    return result.scalars().all()


@router.post("/mappings", response_model=EdgeTypeMapResponse)
async def create_edge_map(
    project_id: str,
    map_data: EdgeTypeMapCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    await verify_project_access(project_id, current_user, db)

    # Check uniqueness
    existing = await db.execute(
        select(EdgeTypeMap).where(
            and_(
                EdgeTypeMap.project_id == project_id,
                EdgeTypeMap.source_type == map_data.source_type,
                EdgeTypeMap.target_type == map_data.target_type,
                EdgeTypeMap.edge_type == map_data.edge_type,
            )
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="This mapping already exists")

    edge_map = EdgeTypeMap(
        id=str(uuid4()),
        project_id=project_id,
        source_type=map_data.source_type,
        target_type=map_data.target_type,
        edge_type=map_data.edge_type,
    )
    db.add(edge_map)
    await db.commit()
    await db.refresh(edge_map)
    return edge_map


@router.delete("/mappings/{map_id}", status_code=204, response_class=Response)
async def delete_edge_map(
    project_id: str,
    map_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await verify_project_access(project_id, current_user, db)
    edge_map = await db.get(EdgeTypeMap, map_id)
    if not edge_map or edge_map.project_id != project_id:
        raise HTTPException(status_code=404, detail="Mapping not found")

    await db.delete(edge_map)
    await db.commit()
    return Response(status_code=204)
