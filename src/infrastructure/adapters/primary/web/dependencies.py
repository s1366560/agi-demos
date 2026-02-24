from fastapi import Request

from src.domain.ports.services.graph_service import GraphServicePort
from src.domain.ports.services.workflow_engine_port import WorkflowEnginePort


def get_graphiti_client(request: Request) -> None:
    """Get Graphiti client from app state."""
    return request.app.state.container.graphiti_client


def get_graph_service(request: Request) -> GraphServicePort:
    return request.app.state.container.graph_service


def get_workflow_engine(request: Request) -> WorkflowEnginePort:
    """Get WorkflowEngine from app state."""
    return request.app.state.workflow_engine
