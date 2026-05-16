"""AI tools API routes."""

import logging
from collections.abc import Mapping
from typing import cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.factories import create_llm_client
from src.domain.llm_providers.llm_types import LLMClient
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_db,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import User, UserTenant

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])

LLM_CLIENT_UNAVAILABLE_DETAIL = "LLM client not available. Please check configuration."


# --- Schemas ---


class OptimizeRequest(BaseModel):
    content: str
    instruction: str = "Improve clarity, fix grammar, and format with Markdown."


class OptimizeResponse(BaseModel):
    content: str


class TitleRequest(BaseModel):
    content: str


class TitleResponse(BaseModel):
    title: str


# --- Endpoints ---


async def get_ai_tools_llm_client(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LLMClient:
    """Resolve the tenant-bound LLM client used by lightweight AI endpoints."""
    tenant_id = getattr(current_user, "tenant_id", None)
    if not isinstance(tenant_id, str) or not tenant_id.strip():
        result = await db.execute(
            refresh_select_statement(
                select(UserTenant.tenant_id).where(UserTenant.user_id == current_user.id).limit(1)
            )
        )
        tenant_id = result.scalar_one_or_none()

    llm_client = cast(
        LLMClient | None,
        await create_llm_client(tenant_id if isinstance(tenant_id, str) else None),
    )
    if llm_client is None:
        raise HTTPException(status_code=501, detail=LLM_CLIENT_UNAVAILABLE_DETAIL)
    return llm_client


def _extract_llm_content(response: object) -> str:
    if isinstance(response, str):
        return response
    if isinstance(response, Mapping):
        content = cast(Mapping[str, object], response).get("content")
        if isinstance(content, str):
            return content
    raise ValueError("LLM response did not include text content")


@router.post("/optimize", response_model=OptimizeResponse)
async def optimize_content(
    request: OptimizeRequest,
    llm_client: LLMClient = Depends(get_ai_tools_llm_client),
) -> OptimizeResponse:
    """
    Optimize content using AI.
    """
    try:
        prompt = f"""
        You are an intelligent writing assistant.
        Please rewrite the following text according to these instructions: {request.instruction}

        Original Text:
        {request.content}

        Output ONLY the rewritten text. Do not include any explanations or conversational filler.
        """

        response = await llm_client.generate(messages=[{"role": "user", "content": prompt}])

        return OptimizeResponse(content=_extract_llm_content(response).strip())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to optimize content: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/generate-title", response_model=TitleResponse)
async def generate_title(
    request: TitleRequest,
    llm_client: LLMClient = Depends(get_ai_tools_llm_client),
) -> TitleResponse:
    """
    Generate a title for the content using AI.
    """
    try:
        # Truncate content if too long
        content_preview = request.content[:1000] if len(request.content) > 1000 else request.content

        prompt = f"""
        Generate a concise and descriptive title (max 10 words) for the following text.

        Text:
        {content_preview}...

        Output ONLY the title. Do not use quotes.
        """

        response = await llm_client.generate(messages=[{"role": "user", "content": prompt}])

        # Cleanup quotes if present
        title = _extract_llm_content(response).strip().strip('"').strip("'")

        return TitleResponse(title=title)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate title: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e
