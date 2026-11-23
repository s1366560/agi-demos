"""Generation-owned workflow runtime Provider and application Consumer seams."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

from plugins.business.automation.workflow.contract import (
    WorkflowEnginePort,
    WorkflowHandlerRegistry,
)
from plugins.business.automation.workflow.engine import AsyncioWorkflowEngine
from src.infrastructure.plugins.v2.background_task_services import (
    BackgroundTaskManagerRuntimeV2,
)
from src.infrastructure.plugins.v2.runtime import (
    ContextV2,
    EffectResultV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

WORKFLOW_RUNTIME_MODULE_V2 = "builtin://memstack/workflow/asyncio-runtime"
WORKFLOW_RUNTIME_SERVICE_V2 = "service:workflow.runtime"
WORKFLOW_APPLICATION_MODULE_V2 = "builtin://memstack/application/workflow-services"
WORKFLOW_APPLICATION_SERVICE_V2 = "service:application.workflow-services"
WORKFLOW_RUNTIME_INJECT_V2 = "runtime"
WORKFLOW_TASK_MANAGER_INJECT_V2 = "task_manager"

type WorkflowRuntimeFactoryV2 = Callable[[], WorkflowEnginePort | Awaitable[WorkflowEnginePort]]


@dataclass(frozen=True, kw_only=True)
class WorkflowRuntimeServiceV2:
    """Exact workflow engine owned by one staged generation."""

    engine: WorkflowEnginePort


@dataclass(frozen=True, kw_only=True)
class WorkflowApplicationServicesV2:
    """Consumer-visible workflow services for one operation."""

    engine: WorkflowEnginePort


@runtime_checkable
class WorkflowApplicationResolverProtocolV2(Protocol):
    """Resolve workflow services without exposing the Provider implementation."""

    def resolve(self, operation: OperationContextV2) -> WorkflowApplicationServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class WorkflowApplicationResolverV2:
    """Resolve the engine from the operation's exact generation."""

    runtime: WorkflowRuntimeServiceV2

    def resolve(self, operation: OperationContextV2) -> WorkflowApplicationServicesV2:
        _ = operation.descriptor
        return WorkflowApplicationServicesV2(engine=self.runtime.engine)


def _configure_engine(
    engine: WorkflowEnginePort,
    tasks: BackgroundTaskManagerRuntimeV2,
    register_handlers: Callable[[WorkflowHandlerRegistry], None] | None,
) -> None:
    if isinstance(engine, WorkflowHandlerRegistry):
        engine.bind_task_manager(tasks.manager)
        if register_handlers is not None:
            register_handlers(engine)


def workflow_runtime_definition_v2(
    workflow_runtime_factory: WorkflowRuntimeFactoryV2 | None = None,
    *,
    register_handlers: Callable[[WorkflowHandlerRegistry], None] | None = None,
) -> PluginDefinitionV2:
    """Build the workflow Provider definition for one data plane."""

    async def apply_runtime(
        context: ContextV2,
        config: Mapping[str, Any],
    ) -> EffectResultV2:
        if config.get("strategy") != "asyncio-local":
            raise ValueError("workflow runtime requires strategy asyncio-local")

        task_manager_runtime = context.require(WORKFLOW_TASK_MANAGER_INJECT_V2)
        if not isinstance(task_manager_runtime, BackgroundTaskManagerRuntimeV2):
            raise RuntimeV2Error(
                "invalid_background_task_manager_inject",
                "workflow runtime requires the shared background task manager",
            )
        candidate: object
        if workflow_runtime_factory is None:
            candidate = cast(
                "object",
                AsyncioWorkflowEngine(manager=task_manager_runtime.manager),
            )
        else:
            candidate = cast("object", workflow_runtime_factory())
        if inspect.isawaitable(candidate):
            candidate = await candidate
        if not isinstance(candidate, WorkflowEnginePort):
            raise RuntimeV2Error(
                "invalid_workflow_runtime",
                "workflow runtime factory must supply a WorkflowEnginePort",
            )
        engine = candidate

        async def dispose() -> None:
            close = getattr(engine, "close", None)
            if not callable(close):
                return
            result = close()
            if inspect.isawaitable(result):
                await result

        try:
            _configure_engine(engine, task_manager_runtime, register_handlers)
            _ = context.provide(
                WORKFLOW_RUNTIME_SERVICE_V2,
                WorkflowRuntimeServiceV2(engine=engine),
                label="workflow-runtime",
            )
        except BaseException:
            await dispose()
            raise
        return dispose

    return PluginDefinitionV2(
        module_ref=WORKFLOW_RUNTIME_MODULE_V2,
        contract_digest=generated_contract_digest_v2(WORKFLOW_RUNTIME_MODULE_V2),
        apply=apply_runtime,
    )


def workflow_application_definition_v2() -> PluginDefinitionV2:
    """Build the workflow application Consumer definition."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "generation-runtime":
            raise ValueError("workflow application requires strategy generation-runtime")
        runtime = context.require(WORKFLOW_RUNTIME_INJECT_V2)
        if not isinstance(runtime, WorkflowRuntimeServiceV2):
            raise RuntimeV2Error(
                "invalid_workflow_runtime_inject",
                "workflow runtime inject has an invalid implementation",
            )
        _ = context.provide(
            WORKFLOW_APPLICATION_SERVICE_V2,
            WorkflowApplicationResolverV2(runtime=runtime),
            label="workflow-application",
        )

    return PluginDefinitionV2(
        module_ref=WORKFLOW_APPLICATION_MODULE_V2,
        contract_digest=generated_contract_digest_v2(WORKFLOW_APPLICATION_MODULE_V2),
        apply=apply,
    )


def workflow_service_definitions_v2(
    workflow_runtime_factory: WorkflowRuntimeFactoryV2 | None = None,
    *,
    register_handlers: Callable[[WorkflowHandlerRegistry], None] | None = None,
) -> tuple[PluginDefinitionV2, ...]:
    """Build the workflow Provider/Consumer definition pair."""
    return (
        workflow_runtime_definition_v2(
            workflow_runtime_factory, register_handlers=register_handlers
        ),
        workflow_application_definition_v2(),
    )


__all__ = [
    "WORKFLOW_APPLICATION_MODULE_V2",
    "WORKFLOW_APPLICATION_SERVICE_V2",
    "WORKFLOW_RUNTIME_INJECT_V2",
    "WORKFLOW_RUNTIME_MODULE_V2",
    "WORKFLOW_RUNTIME_SERVICE_V2",
    "WORKFLOW_TASK_MANAGER_INJECT_V2",
    "WorkflowApplicationResolverProtocolV2",
    "WorkflowApplicationResolverV2",
    "WorkflowApplicationServicesV2",
    "WorkflowRuntimeFactoryV2",
    "WorkflowRuntimeServiceV2",
    "workflow_application_definition_v2",
    "workflow_runtime_definition_v2",
    "workflow_service_definitions_v2",
]
