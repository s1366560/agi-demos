"""Send device WAL requests to the same trusted authority as the signed Agent conversations."""

from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response

from src.host.transport.conversation_journal import HistoryLimit, HistoryOffset, ProjectId
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import get_current_user
from src.infrastructure.i18n import gettext as _

router = APIRouter(dependencies=[Depends(get_current_user)])
Identifier = Annotated[str, Path(pattern=r"^[a-zA-Z0-9_-]{1,128}$")]


async def _send(
    request: Request, resource: str, query: dict[str, str | int] | None = None
) -> Response:
    if request.headers.get("x-memstack-application-hop"):
        raise HTTPException(503, _("Application routing loop"))
    origin = request.app.state.package_application_runtime_origin
    chunks = bytearray()
    async for chunk in request.stream():
        if len(chunks) + len(chunk) > 512 * 1024:
            raise HTTPException(413, _("Device request is too large"))
        chunks.extend(chunk)
    headers = {
        "Authorization": request.headers.get("authorization", ""),
        "X-Agi-Surface": request.headers.get("x-agi-surface", ""),
        "Content-Type": "application/json",
        "X-Memstack-Application-Hop": "1",
    }
    try:
        async with httpx.AsyncClient(base_url=origin, trust_env=False, timeout=30) as client:
            reply = await client.request(
                request.method,
                f"/api/v1/agent/{resource}",
                content=bytes(chunks),
                headers=headers,
                params=query,
            )
    except httpx.HTTPError as error:
        raise HTTPException(503, _("Device run authority unavailable")) from error
    if reply.is_redirect:
        raise HTTPException(503, _("Device run authority unavailable"))
    return Response(reply.content, status_code=reply.status_code, media_type="application/json")


@router.post("/conversations/{conversation_id}/local-runs")
async def register(conversation_id: Identifier, request: Request) -> Response:
    return await _send(request, f"conversations/{conversation_id}/local-runs")


@router.post("/runs/{run_id}/events:batch")
async def upload(run_id: Identifier, request: Request) -> Response:
    return await _send(request, f"runs/{run_id}/events:batch")


@router.patch("/runs/{run_id}/local-terminal")
async def settle(run_id: Identifier, request: Request) -> Response:
    return await _send(request, f"runs/{run_id}/local-terminal")


@router.post("/runs/{run_id}/local-stop")
async def stop(run_id: Identifier, request: Request) -> Response:
    return await _send(request, f"runs/{run_id}/local-stop")


@router.get("/runs/{run_id}/local-events")
async def events(run_id: Identifier, request: Request) -> Response:
    return await _send(request, f"runs/{run_id}/local-events")


@router.get("/conversations/{conversation_id}")
async def detail(conversation_id: Identifier, project_id: ProjectId, request: Request) -> Response:
    return await _send(request, f"conversations/{conversation_id}", {"project_id": project_id})


@router.get("/conversations")
async def history(
    project_id: ProjectId, request: Request, limit: HistoryLimit = 50, offset: HistoryOffset = 0
) -> Response:
    return await _send(
        request, "conversations", {"project_id": project_id, "limit": limit, "offset": offset}
    )
