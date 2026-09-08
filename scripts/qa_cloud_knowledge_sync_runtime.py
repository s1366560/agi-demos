"""Explicitly non-dispatching task runtime for the QA-only HTTP process."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from scripts.qa_cloud_knowledge_sync_graph import create_qa_graph
from src.infrastructure.adapters.secondary.background_tasks import TaskManager
from src.infrastructure.plugins.v2.background_task_services import (
    BACKGROUND_TASK_MANAGER_MODULE_V2,
    background_task_manager_definition_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2

if TYPE_CHECKING:
    from src.infrastructure.adapters.secondary.background_tasks import BackgroundTask
    from src.infrastructure.plugins.v2.runtime import PluginDefinitionV2


class QaNoDispatchTaskManager(TaskManager):
    """Retain the production task interface but reject any attempted worker dispatch."""

    @override
    def start_cleanup(self) -> None:
        # No periodic task is started by a QA profile publication.
        return None

    @override
    def create_task(self, *_args: object, **_kwargs: object) -> BackgroundTask:
        raise RuntimeError("Background task dispatch is disabled in the Cloud knowledge QA API")


def qa_runtime_definitions(neo4j_uri: str) -> tuple[PluginDefinitionV2, ...]:
    definitions = builtin_runtime_definitions_v2(
        graph_runtime_factory=lambda: create_qa_graph(neo4j_uri),
    )
    return (
        *(
            definition
            for definition in definitions
            if definition.module_ref != BACKGROUND_TASK_MANAGER_MODULE_V2
        ),
        background_task_manager_definition_v2(QaNoDispatchTaskManager),
    )
