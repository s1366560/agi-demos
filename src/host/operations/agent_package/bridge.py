"""Host data plane for an agent command guest.

Routes run as the admitted actor. The caller's bearer token is not copied.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any, cast
from urllib.parse import urlencode

from sqlalchemy import select

from src.host.operations.agent_package.admission import admit
from src.host.operations.agent_package.turn_stream import actor_control, stream_turn
from src.host.operations.application_commands import PackageOperationContext
from src.host.operations.tenant_commands import TenantPackageContext
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

type Progress = Callable[[dict[str, Any]], Awaitable[None]]


class HostBridge:
    def __init__(self, ctx: PackageOperationContext | TenantPackageContext) -> None:
        self.ctx = ctx
        self.user_id = str(ctx.user.id)
        self.tenant_id = ctx.scope.tenant_id
        self.project_id = getattr(ctx.scope, "project_id", None)

    async def http(
        self,
        method: str,
        path: str,
        *,
        project_route: bool = False,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        absolute: bool = False,
    ) -> dict[str, Any]:
        if absolute:
            return await self._call(method, path, body=body, query=query)
        if project_route:
            base = f"/api/v1/projects/{self.project_id}/"
        else:
            base = "/api/v1/agent/"
        return await self._call(method, base + path, body=body, query=query)

    async def _call(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        params = dict(query or {})
        if self.project_id and "project_id" not in params:
            params["project_id"] = self.project_id
        status, payload = await invoke_admitted_route(
            self.ctx.request.app,
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            method=method,
            path=path,
            query=params,
            body=body,
            form=data,
        )
        if status >= 400:
            code = {403: "forbidden", 401: "forbidden", 404: "page_not_found", 409: "conflict"}.get(
                status, "runtime_unavailable"
            )
            raise OptionalBusinessError(code, f"Agent authority returned HTTP {status}")
        if not isinstance(payload, dict):
            raise OptionalBusinessError("runtime_unavailable", "Invalid Agent authority response")
        return payload

    async def own(self, conversation_id: str) -> None:
        from src.infrastructure.adapters.secondary.persistence.models import Conversation

        if not self.project_id:
            raise OptionalBusinessError("forbidden", "conversation unavailable for this project")
        match = await self.ctx.db.scalar(
            select(Conversation.id).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == self.tenant_id,
                Conversation.project_id == self.project_id,
                Conversation.user_id == self.user_id,
            )
        )
        if match is None:
            raise OptionalBusinessError("forbidden", "conversation unavailable for this project")

    async def local_ids(self, ids: list[str]) -> list[str]:
        from src.infrastructure.adapters.secondary.persistence.models import Conversation

        if not ids or not self.project_id:
            return []
        rows = await self.ctx.db.scalars(
            select(Conversation.id).where(
                Conversation.id.in_(ids),
                Conversation.tenant_id == self.tenant_id,
                Conversation.project_id == self.project_id,
                Conversation.user_id == self.user_id,
                Conversation.meta["execution_target"].as_string() == "local",
            )
        )
        return list(rows)

    async def meta(self, conversation_id: str) -> dict[str, Any] | None:
        from src.infrastructure.adapters.secondary.persistence.models import Conversation

        value = await self.ctx.db.scalar(
            select(Conversation.meta).where(Conversation.id == conversation_id)
        )
        return value if isinstance(value, dict) else None

    async def placements(self, ids: list[str]) -> dict[str, str]:
        from src.infrastructure.adapters.secondary.persistence.sql_agent_run_authority import (
            latest_execution_placements,
        )

        if not self.project_id:
            return {}
        rows = await latest_execution_placements(
            self.ctx.db,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            conversation_ids=ids,
        )
        return {key: row.execution_target for key, row in rows.items()}

    async def run_cloud(self, run_id: str, conversation_id: str) -> bool:
        from src.infrastructure.adapters.secondary.persistence.models import AgentRunAuthorityModel

        if not self.project_id:
            return False
        run = await self.ctx.db.scalar(
            select(AgentRunAuthorityModel.id).where(
                AgentRunAuthorityModel.id == run_id,
                AgentRunAuthorityModel.conversation_id == conversation_id,
                AgentRunAuthorityModel.tenant_id == self.tenant_id,
                AgentRunAuthorityModel.project_id == self.project_id,
                AgentRunAuthorityModel.execution_target == "cloud",
            )
        )
        return run is not None

    async def run_conversation(self, run_id: str) -> str | None:
        from src.infrastructure.adapters.secondary.persistence.models import AgentRunAuthorityModel

        if not self.project_id:
            return None
        conversation = await self.ctx.db.scalar(
            select(AgentRunAuthorityModel.conversation_id).where(
                AgentRunAuthorityModel.id == run_id,
                AgentRunAuthorityModel.tenant_id == self.tenant_id,
                AgentRunAuthorityModel.project_id == self.project_id,
            )
        )
        return conversation if isinstance(conversation, str) else None

    async def run_fields(self, run_id: str, conversation_id: str) -> dict[str, Any]:
        from src.infrastructure.adapters.secondary.persistence.models import AgentRunAuthorityModel

        run = await self.ctx.db.scalar(
            select(AgentRunAuthorityModel).where(
                AgentRunAuthorityModel.id == run_id,
                AgentRunAuthorityModel.conversation_id == conversation_id,
                AgentRunAuthorityModel.tenant_id == self.tenant_id,
                AgentRunAuthorityModel.project_id == self.project_id,
            )
        )
        if run is None:
            raise OptionalBusinessError("forbidden", "run unavailable for this project")
        return {
            "permission_profile": run.permission_profile,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "error": run.error,
        }

    async def device(self, op: str, payload: dict[str, Any]) -> dict[str, Any]:
        from src.host.operations.application_commands import PackageOperationContext
        from src.host.operations.device_conversations import create_owned, local_history

        ctx = cast(PackageOperationContext, self.ctx)
        if op == "create":
            return await create_owned(ctx, payload, None)
        if op == "history":
            return await local_history(ctx, payload, None)
        raise OptionalBusinessError("forbidden", "unsupported device operation")

    async def stream(self, message: dict[str, Any], progress: Progress | None) -> dict[str, Any]:
        if not self.project_id:
            raise OptionalBusinessError("forbidden", "project scope required")
        return await stream_turn(
            self.ctx.request.app,
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            data=message,
            progress=progress,
        )

    async def actor(self, action: str) -> str:
        if not self.project_id:
            raise OptionalBusinessError("forbidden", "project scope required")
        return await actor_control(
            self.ctx.request.app,
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            action=action,
        )

    async def voice(self, conversation_id: str) -> dict[str, str]:
        from src.host.operations.package_voice_lease import voice_ticket
        from src.host.operations.voice_scope import voice_conversation_tenant

        if not self.project_id:
            raise OptionalBusinessError(
                "forbidden", "Voice requires an accessible cloud conversation"
            )
        tenant = await voice_conversation_tenant(
            self.ctx.db,
            user_id=self.user_id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            conversation_id=conversation_id,
        )
        if not tenant:
            raise OptionalBusinessError(
                "forbidden", "Voice requires an accessible cloud conversation"
            )
        return {
            "conversation_id": conversation_id,
            "principal_id": self.user_id,
            "ticket": voice_ticket(
                principal=self.user_id,
                tenant=tenant,
                project=self.project_id,
                conversation=conversation_id,
            ),
        }

    async def welcome(self, complete: bool | None) -> dict[str, Any]:
        from src.infrastructure.adapters.secondary.persistence.models import User

        field = "memstack_agent_web_onboarding_complete"
        if complete is None:
            profile = await self.ctx.db.scalar(select(User.profile).where(User.id == self.user_id))
            return {"complete": (profile or {}).get(field) is True}
        user = await self.ctx.db.scalar(
            select(User)
            .where(User.id == self.user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if user is None:
            raise OptionalBusinessError("forbidden", "User unavailable")
        if (user.profile or {}).get(field) is not True:
            user.profile = {**(user.profile or {}), field: True}
        await self.ctx.db.commit()
        return {"complete": True}

    async def model_routes(self) -> dict[str, Any]:
        from src.host.operations.agent_package.model_routes import routes_for
        from src.infrastructure.persistence.tenant_model_roster import tenant_chat_providers

        providers = list(await self.ctx.db.scalars(tenant_chat_providers(self.tenant_id)))
        default, routes = routes_for(providers)
        return {"default_model": default, "models": routes}

    async def lifecycle_snapshot(self) -> dict[str, Any]:
        from src.infrastructure.agent.actor.lifecycle_snapshot import project_lifecycle_snapshot

        if not self.project_id:
            raise OptionalBusinessError("forbidden", "project scope required")
        return await project_lifecycle_snapshot(self.tenant_id, self.project_id)

    async def templates(self, limit: int) -> list[dict[str, Any]]:
        from src.infrastructure.adapters.primary.web.routers.agent.templates import list_templates

        if not self.project_id:
            return []
        rows = await list_templates(
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            limit=limit,
            offset=0,
            category=None,
            current_user=self.ctx.user,
            db=self.ctx.db,
        )
        return [
            row.model_dump(mode="json")
            for row in rows
            if row.tenant_id == self.tenant_id and row.project_id == self.project_id
        ]

    async def hitl(self, conversation_id: str, request_id: str) -> dict[str, Any] | None:
        from src.infrastructure.adapters.secondary.persistence.models import HITLRequest

        if not self.project_id:
            return None
        record = await self.ctx.db.scalar(
            select(HITLRequest).where(
                HITLRequest.id == request_id,
                HITLRequest.conversation_id == conversation_id,
                HITLRequest.tenant_id == self.tenant_id,
                HITLRequest.project_id == self.project_id,
            )
        )
        if (
            record is None
            or record.user_id not in (None, self.user_id)
            or (record.request_metadata or {}).get("native_binding")
        ):
            return None
        return {"id": record.id}

    async def attachment_files(
        self, conversation_id: str, ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        from src.infrastructure.adapters.secondary.persistence.attachment_model import (
            AttachmentModel,
        )

        if not self.project_id:
            return {}
        records = await self.ctx.db.scalars(
            select(AttachmentModel).where(
                AttachmentModel.id.in_(ids),
                AttachmentModel.conversation_id == conversation_id,
                AttachmentModel.tenant_id == self.tenant_id,
                AttachmentModel.project_id == self.project_id,
                AttachmentModel.status.in_(("uploaded", "processing", "ready")),
            )
        )
        return {
            row.id: {
                "id": row.id,
                "filename": row.filename,
                "mime_type": row.mime_type,
                "size_bytes": row.size_bytes,
            }
            for row in records
        }

    async def attachment(self, payload: dict[str, Any]) -> dict[str, Any]:
        from src.host.operations.agent_package.attachments import perform

        return await perform(self, payload)

    async def dashboard(self, op: str, payload: dict[str, Any]) -> dict[str, Any]:
        from src.host.operations.agent_package.dashboard import perform

        return await perform(self, op, payload)

    async def tenant_sessions(self, op: str, payload: dict[str, Any]) -> dict[str, Any]:
        from src.host.operations.agent_package.tenant_sessions import perform

        return await perform(self, op, payload)


async def invoke_admitted_route(
    app: Callable[..., Awaitable[None]],
    *,
    user_id: str,
    tenant_id: str,
    method: str,
    path: str,
    query: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
    form: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    raw = b""
    headers: list[tuple[bytes, bytes]] = []
    if body is not None:
        raw = json.dumps(body).encode()
        headers.append((b"content-type", b"application/json"))
    elif form is not None:
        raw = urlencode(form).encode()
        headers.append((b"content-type", b"application/x-www-form-urlencoded"))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": urlencode(
            {key: value for key, value in (query or {}).items() if value is not None}
        ).encode(),
        "headers": headers,
        "client": ("127.0.0.1", 0),
        "server": ("localhost", 80),
        "app": app,
    }
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": raw, "more_body": False}

    messages: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    with admit(user_id, tenant_id):
        await app(scope, receive, send)
    status = 500
    chunks: list[bytes] = []
    for message in messages:
        if message["type"] == "http.response.start":
            status = int(message["status"])
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body") or b"")
    text = b"".join(chunks)
    if not text:
        return status, {}
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OptionalBusinessError(
            "runtime_unavailable", "Invalid Agent authority response"
        ) from exc
    return status, decoded
