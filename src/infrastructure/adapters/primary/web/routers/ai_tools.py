"""AI tools API routes."""

import logging
from collections.abc import Mapping
from typing import cast

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.domain.llm_providers.llm_types import LLMClient
from src.infrastructure.adapters.primary.web.ai_tool_application_authority_v2 import (
    AiToolApplicationAuthorityV2,
    ai_tool_application_authority_dependency_v2,
)
from src.infrastructure.i18n import gettext as _
from src.infrastructure.plugins.v2.ai_tool_services import AiToolClientUnavailableV2

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


async def _resolve_ai_tool_client_v2(
    authority: AiToolApplicationAuthorityV2,
) -> LLMClient:
    try:
        return await authority.services.resolve_client(
            user_id=authority.user_id,
            tenant_id=authority.tenant_id,
        )
    except AiToolClientUnavailableV2 as error:
        raise HTTPException(
            status_code=501,
            detail=LLM_CLIENT_UNAVAILABLE_DETAIL,
        ) from error


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
    ai_tool_application: AiToolApplicationAuthorityV2 = Depends(
        ai_tool_application_authority_dependency_v2
    ),
) -> OptimizeResponse:
    """
    Optimize content using AI.
    """
    try:
        llm_client = await _resolve_ai_tool_client_v2(ai_tool_application)
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
        logger.exception("Failed to optimize content")
        raise HTTPException(
            status_code=500,
            detail=_("Failed to optimize content"),
        ) from e


@router.post("/generate-title", response_model=TitleResponse)
async def generate_title(
    request: TitleRequest,
    ai_tool_application: AiToolApplicationAuthorityV2 = Depends(
        ai_tool_application_authority_dependency_v2
    ),
) -> TitleResponse:
    """
    Generate a title for the content using AI.
    """
    try:
        llm_client = await _resolve_ai_tool_client_v2(ai_tool_application)
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
        logger.exception("Failed to generate title")
        raise HTTPException(
            status_code=500,
            detail=_("Failed to generate title"),
        ) from e
