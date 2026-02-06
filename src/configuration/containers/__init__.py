"""DI sub-container modules for domain-specific dependency injection.

Each sub-container encapsulates factory methods for a specific domain,
while the main DIContainer delegates to them via composition.
"""

from src.configuration.containers.agent_container import AgentContainer
from src.configuration.containers.auth_container import AuthContainer
from src.configuration.containers.infra_container import InfraContainer
from src.configuration.containers.memory_container import MemoryContainer
from src.configuration.containers.project_container import ProjectContainer
from src.configuration.containers.sandbox_container import SandboxContainer
from src.configuration.containers.task_container import TaskContainer

__all__ = [
    "AgentContainer",
    "AuthContainer",
    "InfraContainer",
    "MemoryContainer",
    "ProjectContainer",
    "SandboxContainer",
    "TaskContainer",
]
