"""Command-related endpoints.

Endpoints for listing available slash commands.
"""

import logging

from fastapi import APIRouter, Depends, Query

from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.agent.commands.builtins import register_builtin_commands
from src.infrastructure.agent.commands.registry import CommandRegistry
from src.infrastructure.agent.commands.types import CommandCategory, CommandScope

from .schemas import (
    CommandArgInfo,
    CommandInfo,
    CommandsListResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def _get_command_registry() -> CommandRegistry:
    """Build a CommandRegistry with builtin commands registered."""
    registry = CommandRegistry()
    register_builtin_commands(registry)
    return registry


@router.get("/commands", response_model=CommandsListResponse)
async def list_commands(
    category: str | None = Query(None, description="Filter by command category"),
    scope: str | None = Query(None, description="Filter by command scope"),
    current_user: User = Depends(get_current_user),
) -> CommandsListResponse:
    """List available slash commands."""
    registry = _get_command_registry()

    cat_filter = CommandCategory(category) if category else None
    scope_filter = CommandScope(scope) if scope else None

    commands = registry.list_commands(
        category=cat_filter,
        scope=scope_filter,
        include_hidden=False,
    )

    command_infos = [
        CommandInfo(
            name=cmd.name,
            description=cmd.description,
            category=cmd.category.value,
            scope=cmd.scope.value,
            aliases=cmd.aliases,
            args=[
                CommandArgInfo(
                    name=arg.name,
                    description=arg.description,
                    arg_type=arg.arg_type.value,
                    required=arg.required,
                    choices=arg.choices,
                )
                for arg in cmd.args
            ],
        )
        for cmd in commands
    ]

    return CommandsListResponse(commands=command_infos, total=len(command_infos))
