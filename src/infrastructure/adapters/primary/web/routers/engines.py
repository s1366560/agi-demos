from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["engines"])

_RUNTIME_ENGINES: list[dict[str, Any]] = [
    {
        "runtime_id": "python-3.12",
        "display_name": "Python 3.12",
        "display_description": "CPython 3.12 runtime with scientific computing packages",
        "display_tags": ["python", "data-science", "general"],
        "display_powered_by": "Docker",
        "order": 1,
        "image_registry_key": "python",
        "default_registry_url": "docker.io/library/python:3.12-slim",
    },
    {
        "runtime_id": "node-22",
        "display_name": "Node.js 22",
        "display_description": "Node.js 22 LTS runtime for JavaScript/TypeScript",
        "display_tags": ["javascript", "typescript", "web"],
        "display_powered_by": "Docker",
        "order": 2,
        "image_registry_key": "node",
        "default_registry_url": "docker.io/library/node:22-slim",
    },
    {
        "runtime_id": "sandbox-base",
        "display_name": "MemStack Sandbox",
        "display_description": "Full-featured sandbox with terminal, desktop, and MCP tools",
        "display_tags": ["sandbox", "full-stack", "mcp"],
        "display_powered_by": "Docker + noVNC",
        "order": 3,
        "image_registry_key": "sandbox",
        "default_registry_url": "memstack/sandbox:latest",
    },
]


@router.get("/api/v1/engines")
async def list_engines() -> list[dict[str, Any]]:
    return sorted(_RUNTIME_ENGINES, key=lambda e: e.get("order", 999))
