"""Resolve a channel's approved task timeline renderer without exposing message content."""

from __future__ import annotations

import asyncio
import json
import logging
from importlib.resources import files
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from src.application.services.channels._session import with_session
from src.configuration.config import get_settings
from src.host.packages.project_plugin_installation import ProjectPluginInstallationService
from src.infrastructure.adapters.secondary.persistence.channel_models import (
    ChannelConfigModel,
    ChannelSessionBindingModel,
)
from src.infrastructure.adapters.secondary.persistence.models import Conversation, Project
from src.infrastructure.plugins.package_registry import load_plugin_trust_keys
from src.infrastructure.plugins.v2.project_package_execution import invoke_project_tool
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
    SignedPackageBytesV2,
)
from src.infrastructure.plugins.wasm_host import WasmToolHost

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)
_TOOL = "render_timeline"


def _prefix(result: dict[str, Any]) -> str:
    value = result.get("prefix")
    if set(result) != {"prefix"} or not isinstance(value, str) or len(value) > 1024:
        raise ValueError("invalid task timeline renderer output")
    return value


def _bundled_prefix(progress: dict[str, Any]) -> str:
    # Full distributions ship the same ABI guest as the independent publisher.
    guest = files("plugins.adapters.channels.feishu").joinpath("timeline.wasm").read_bytes()
    host = WasmToolHost(
        "memstack-feishu-timeline", guest, expected_abi="invoke", fuel_budget=1_000_000
    )
    try:
        return _prefix(json.loads(host.invoke_json(_TOOL, json.dumps(progress))))
    finally:
        host.close()


async def _selected_renderer(
    db: AsyncSession, config_id: str, chat_id: str, data: dict[str, Any]
) -> tuple[ScopeBindingV2, str | None]:
    row = (
        await db.execute(
            select(
                Project.tenant_id,
                Project.id,
                ChannelConfigModel.extra_settings["task_timeline_package"].as_string(),
            )
            .select_from(ChannelSessionBindingModel)
            .join(
                ChannelConfigModel,
                ChannelConfigModel.id == ChannelSessionBindingModel.channel_config_id,
            )
            .join(Project, Project.id == ChannelConfigModel.project_id)
            .join(Conversation, Conversation.id == ChannelSessionBindingModel.conversation_id)
            .where(
                ChannelConfigModel.id == config_id,
                ChannelConfigModel.enabled.is_(True),
                ChannelConfigModel.channel_type == "feishu",
                ChannelSessionBindingModel.channel_type == "feishu",
                ChannelSessionBindingModel.chat_id == chat_id,
                ChannelSessionBindingModel.project_id == Project.id,
                Conversation.project_id == Project.id,
                Conversation.tenant_id == Project.tenant_id,
                Conversation.id == data["_conversation_id"],
            )
            .execution_options(populate_existing=True)
        )
    ).one_or_none()
    if (
        row is None
        or data.get("_project_id") not in (None, row[1])
        or data.get("_tenant_id") not in (None, row[0])
    ):
        raise ValueError("invalid task timeline channel scope")
    return ScopeBindingV2(tenant_id=row[0], project_id=row[1]), row[2]


async def timeline_prefix(data: dict[str, Any], chat_id: str) -> str:
    progress = {
        "event": data["_event_type"],
        "status": data.get("status", ""),
        "order_index": data.get("order_index", 0),
        "total_tasks": data.get("total_tasks", 1),
    }
    config_id = data.get("_feishu_timeline_config_id")
    if config_id is not None:
        async with with_session() as db:
            scope, plugin_id = await _selected_renderer(db, config_id, chat_id, data)
            if plugin_id is not None:
                keys = await asyncio.to_thread(
                    load_plugin_trust_keys, get_settings().plugin_marketplace_trusted_key_files
                )
                service = ProjectPluginInstallationService(db, scope, tuple(keys))

                async def invoke(package: SignedPackageBytesV2) -> str:
                    if package.worker is not None or package.approved_permissions != frozenset(
                        {"tools.execute"}
                    ):
                        raise OptionalBusinessError(
                            "forbidden", "channel rendering requires compute-only Wasm"
                        )
                    return _prefix(await invoke_project_tool(package, scope, _TOOL, progress))

                try:
                    return await service.call_active(plugin_id, invoke)
                except (OptionalBusinessError, ValueError) as error:
                    # A revoked or unavailable renderer can no longer decorate the event.
                    # The existing channel transport still delivers the bound task text.
                    logger.warning("Task timeline renderer unavailable (%s)", type(error).__name__)
                    return ""
    return await asyncio.to_thread(_bundled_prefix, progress)
