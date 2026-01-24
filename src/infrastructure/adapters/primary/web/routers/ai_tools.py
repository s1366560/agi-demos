"""AI tools API routes."""

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

# Use Cases & DI Container
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_graphiti_client,
)
from src.infrastructure.adapters.secondary.persistence.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ai", tags=["ai"])


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


@router.post("/optimize", response_model=OptimizeResponse)
async def optimize_content(
    request: OptimizeRequest,
    current_user: User = Depends(get_current_user),
    graphiti_client=Depends(get_graphiti_client),
):
    """
    Optimize content using AI.
    """
    try:
        # Get LLM client from graphiti
        # Note: This assumes graphiti_client has an llm_client property
        llm_client = getattr(graphiti_client, "llm_client", None)

        if not llm_client:
            # Fallback: try to get it from the client attribute
            client = getattr(graphiti_client, "client", None)
            llm_client = getattr(client, "llm_client", None) if client else None

        if not llm_client:
            raise HTTPException(
                status_code=501, detail="LLM client not available. Please check configuration."
            )

        prompt = f"""
        You are an intelligent writing assistant.
        Please rewrite the following text according to these instructions: {request.instruction}

        Original Text:
        {request.content}

        Output ONLY the rewritten text. Do not include any explanations or conversational filler.
        """

        response = await llm_client.generate_response(
            messages=[{"role": "user", "content": prompt}]
        )

        return OptimizeResponse(content=response.strip())

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to optimize content: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-title", response_model=TitleResponse)
async def generate_title(
    request: TitleRequest,
    current_user: User = Depends(get_current_user),
    graphiti_client=Depends(get_graphiti_client),
):
    """
    Generate a title for the content using AI.
    """
    try:
        # Get LLM client from graphiti
        llm_client = getattr(graphiti_client, "llm_client", None)

        if not llm_client:
            client = getattr(graphiti_client, "client", None)
            llm_client = getattr(client, "llm_client", None) if client else None

        if not llm_client:
            raise HTTPException(
                status_code=501, detail="LLM client not available. Please check configuration."
            )

        # Truncate content if too long
        content_preview = request.content[:1000] if len(request.content) > 1000 else request.content

        prompt = f"""
        Generate a concise and descriptive title (max 10 words) for the following text.

        Text:
        {content_preview}...

        Output ONLY the title. Do not use quotes.
        """

        response = await llm_client.generate_response(
            messages=[{"role": "user", "content": prompt}]
        )

        # Cleanup quotes if present
        title = response.strip().strip('"').strip("'")

        return TitleResponse(title=title)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate title: {e}")
        raise HTTPException(status_code=500, detail=str(e))
