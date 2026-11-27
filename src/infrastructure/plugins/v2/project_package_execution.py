"""Admit a verified project package to its declared execution backend."""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from src.configuration.config import get_settings
from src.host.operations.project_package_audit import identify_signed_operation
from src.infrastructure.plugins.v2.command_schema import validate_command_document
from src.infrastructure.plugins.v2.oci_mcp_services import worker_host_callback
from src.infrastructure.plugins.v2.signed_optional_business_v2 import (
    OptionalBusinessError,
    ScopeBindingV2,
    SignedOptionalBusinessRuntimeV2,
    SignedPackageBytesV2,
    signed_ui_resource,
)

if TYPE_CHECKING:
    from src.host.operations.application_commands import PackageOperationContext
    from src.infrastructure.plugins.v2.oci_mcp_worker import OciWorkerSession

type Progress = Callable[[dict[str, Any]], Awaitable[None]]


def allowed_worker_registries() -> frozenset[str]:
    return frozenset(get_settings().plugin_worker_allowed_registries)


@asynccontextmanager
async def _open_worker(
    package: SignedPackageBytesV2, scope: ScopeBindingV2
) -> AsyncIterator["OciWorkerSession"]:
    registries = allowed_worker_registries()
    if package.worker is None or not registries:
        raise OptionalBusinessError("forbidden", "no OCI worker registry is authorized")
    from src.infrastructure.plugins.v2.oci_mcp_worker import OciWorkerSession

    async with OciWorkerSession.open(
        package.worker,
        scope=scope,
        release_digest=package.digest,
        allowed_registries=registries,
        wall_time_ms=package.quotas["wall_time_ms"],
        max_output_bytes=package.quotas["max_output_bytes"],
    ) as worker:
        await worker.prepare(package.contribution.tools)
        yield worker


async def with_wasm_runtime[T](
    package: SignedPackageBytesV2, call: Callable[[SignedOptionalBusinessRuntimeV2], T]
) -> T:
    def execute() -> T:
        runtime = SignedOptionalBusinessRuntimeV2()
        runtime.record(package)
        try:
            runtime.enable(package.plugin_id)
            return call(runtime)
        finally:
            runtime.disable(package.plugin_id)

    pending = asyncio.create_task(asyncio.to_thread(execute))
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        await asyncio.gather(pending, return_exceptions=True)
        raise


async def prepare_project_guest(package: SignedPackageBytesV2, scope: ScopeBindingV2) -> None:
    if package.worker is None:
        await with_wasm_runtime(package, lambda _: None)
        return
    async with _open_worker(package, scope):
        pass


async def invoke_project_tool(
    package: SignedPackageBytesV2,
    scope: ScopeBindingV2,
    tool: str,
    payload: dict[str, Any],
    on_progress: Progress | None = None,
) -> dict[str, Any]:
    identify_signed_operation(package, tool=tool)
    if package.worker is None:
        return await with_wasm_runtime(
            package, lambda runtime: runtime.session(package.plugin_id, scope).invoke(tool, payload)
        )
    selected = next((item for item in package.contribution.tools if item.name == tool), None)
    if selected is None or not selected.permissions <= package.approved_permissions:
        raise OptionalBusinessError("forbidden", "tool is unavailable for this installation")
    async with _open_worker(package, scope) as worker:
        return await worker.invoke(
            tool,
            payload,
            on_progress=on_progress,
            on_record=worker_host_callback(package, scope, selected),
        )


async def dispatch_project_command(
    package: SignedPackageBytesV2,
    scope: ScopeBindingV2,
    command_id: str,
    payload: dict[str, Any] | None = None,
    on_progress: Progress | None = None,
    application: "PackageOperationContext | None" = None,
) -> dict[str, Any]:
    identify_signed_operation(package, command=command_id)
    command = next((c for c in package.contribution.commands if c.command_id == command_id), None)
    if command is None or not command.permissions <= package.approved_permissions:
        raise OptionalBusinessError("forbidden", "command is unavailable for this installation")
    if payload is not None and not command.accepts_input:
        raise OptionalBusinessError("forbidden", "command does not accept user input")
    supplied = dict(command.payload) if payload is None else payload
    validate_command_document(command.input_schema, supplied, "input_schema")
    if command.host_operation:
        if application is None or application.scope != scope:
            raise OptionalBusinessError("runtime_unavailable", "application command unavailable")
        result = await application.invoke(
            command.host_operation,
            supplied,
            on_progress,
            plugin=package.plugin_id,
            digest=package.digest,
            command=command_id,
            supplied_payload=payload,
        )
    else:
        result = await invoke_project_tool(
            package,
            scope,
            command.tool,
            supplied,
            on_progress,
        )
    validate_command_document(command.output_schema, result, "output_schema")
    return result


def project_page(package: SignedPackageBytesV2, target: str) -> dict[str, Any]:
    slot = package.page_slot(target)
    if slot is None:
        raise OptionalBusinessError("ui_unavailable", "no package page for this target")
    return signed_ui_resource(package, slot, target, package.approved_permissions)
