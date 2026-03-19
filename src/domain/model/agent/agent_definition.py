"""
Agent entity for the Multi-Agent System.

Represents a top-level agent (L4) with persona, routing bindings,
workspace isolation, and inter-agent communication capabilities.

Agents are the L4 layer in the four-layer capability architecture:
Tool (L1) -> Skill (L2) -> SubAgent (L3) -> Agent (L4)
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.model.agent.agent_binding import AgentBinding
from src.domain.model.agent.agent_source import AgentSource
from src.domain.model.agent.subagent import AgentModel, AgentTrigger
from src.domain.model.agent.workspace_config import WorkspaceConfig


@dataclass
class Agent:
    """A top-level agent with persona, routing, and workspace isolation.

    Agents provide:
    - Persona-driven behavior via system prompts and persona files
    - Channel-based routing via AgentBinding rules
    - Isolated workspace for long-term memory and artifacts
    - Inter-agent communication and spawning capabilities
    - Scoped tool, skill, and MCP server access

    Attributes:
        id: Unique identifier
        tenant_id: Tenant that owns this agent
        project_id: Optional project-specific agent
        name: Unique name identifier (used for routing)
        display_name: Human-readable display name
        system_prompt: Custom system prompt for this agent
        persona_files: Persona files injected into system prompt
        model: LLM model to use
        temperature: LLM temperature setting
        max_tokens: Maximum tokens for responses
        max_iterations: Maximum ReAct iterations
        allowed_tools: Tools this agent can use
        allowed_skills: Skills this agent can use
        allowed_mcp_servers: MCP servers this agent can use
        trigger: Trigger configuration for routing
        bindings: Channel routing bindings
        workspace_dir: Workspace directory path
        workspace_config: Workspace configuration
        can_spawn: Whether this agent can spawn sub-agents
        max_spawn_depth: Maximum spawning depth
        agent_to_agent_enabled: Allow inter-agent messaging
        discoverable: Whether other agents can discover this one
        source: Where this agent definition comes from
        enabled: Whether this agent is active
        max_retries: Maximum retry attempts on failure
        fallback_models: Fallback models if primary fails
        total_invocations: Total invocation count
        avg_execution_time_ms: Average execution time
        success_rate: Historical success rate (0.0 to 1.0)
        created_at: Creation timestamp
        updated_at: Last modification timestamp
        metadata: Optional additional metadata
    """

    # Identity
    id: str
    tenant_id: str
    name: str
    display_name: str
    system_prompt: str
    trigger: AgentTrigger
    project_id: str | None = None

    # Persona & Behavior
    persona_files: list[str] = field(default_factory=list)
    model: AgentModel = AgentModel.INHERIT
    temperature: float = 0.7
    max_tokens: int = 4096
    max_iterations: int = 10

    # Capability Scoping
    allowed_tools: list[str] = field(default_factory=lambda: ["*"])
    allowed_skills: list[str] = field(default_factory=list)
    allowed_mcp_servers: list[str] = field(default_factory=list)

    # Routing
    bindings: list[AgentBinding] = field(default_factory=list)

    # Workspace
    workspace_dir: str | None = None
    workspace_config: WorkspaceConfig = field(default_factory=WorkspaceConfig)

    # Inter-Agent
    can_spawn: bool = False
    max_spawn_depth: int = 3
    agent_to_agent_enabled: bool = False
    discoverable: bool = True

    # Runtime
    source: AgentSource = AgentSource.DATABASE
    enabled: bool = True
    max_retries: int = 0
    fallback_models: list[str] = field(default_factory=list)

    # Stats
    total_invocations: int = 0
    avg_execution_time_ms: float = 0.0
    success_rate: float = 1.0

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        """Validate the agent."""
        if not self.id:
            raise ValueError("id cannot be empty")
        if not self.tenant_id:
            raise ValueError("tenant_id cannot be empty")
        if not self.name:
            raise ValueError("name cannot be empty")
        if not self.display_name:
            raise ValueError("display_name cannot be empty")
        if not self.system_prompt:
            raise ValueError("system_prompt cannot be empty")
        if self.max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.max_iterations < 1:
            raise ValueError("max_iterations must be positive")
        if not 0 <= self.success_rate <= 1:
            raise ValueError("success_rate must be between 0 and 1")
        if self.max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if self.max_spawn_depth < 0:
            raise ValueError("max_spawn_depth must be non-negative")

    def is_enabled(self) -> bool:
        """Check if agent is enabled."""
        return self.enabled

    def has_tool_access(self, tool_name: str) -> bool:
        """Check if this agent can use a specific tool."""
        if "*" in self.allowed_tools:
            return True
        return tool_name in self.allowed_tools

    def has_skill_access(self, skill_id: str) -> bool:
        """Check if this agent can use a specific skill."""
        if not self.allowed_skills:
            return True
        return skill_id in self.allowed_skills

    def has_mcp_access(self, server_name: str) -> bool:
        """Check if this agent can use a specific MCP server."""
        if "*" in self.allowed_mcp_servers:
            return True
        return server_name in self.allowed_mcp_servers

    def get_filtered_tools(self, available_tools: list[str]) -> list[str]:
        """Get tools filtered by this agent's allowed tools."""
        if "*" in self.allowed_tools:
            return list(available_tools)
        return [t for t in available_tools if t in self.allowed_tools]

    def record_execution(self, execution_time_ms: float, success: bool) -> "Agent":
        """Record an execution and return updated agent."""
        new_invocations = self.total_invocations + 1

        if self.total_invocations == 0:
            new_avg_time = execution_time_ms
        else:
            new_avg_time = (
                self.avg_execution_time_ms * self.total_invocations + execution_time_ms
            ) / new_invocations

        if self.total_invocations == 0:
            new_success_rate = 1.0 if success else 0.0
        else:
            success_value = 1.0 if success else 0.0
            new_success_rate = (
                self.success_rate * self.total_invocations + success_value
            ) / new_invocations

        return Agent(
            id=self.id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            name=self.name,
            display_name=self.display_name,
            system_prompt=self.system_prompt,
            trigger=self.trigger,
            persona_files=list(self.persona_files),
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            max_iterations=self.max_iterations,
            allowed_tools=list(self.allowed_tools),
            allowed_skills=list(self.allowed_skills),
            allowed_mcp_servers=list(self.allowed_mcp_servers),
            bindings=list(self.bindings),
            workspace_dir=self.workspace_dir,
            workspace_config=self.workspace_config,
            can_spawn=self.can_spawn,
            max_spawn_depth=self.max_spawn_depth,
            agent_to_agent_enabled=(self.agent_to_agent_enabled),
            discoverable=self.discoverable,
            source=self.source,
            enabled=self.enabled,
            max_retries=self.max_retries,
            fallback_models=list(self.fallback_models),
            total_invocations=new_invocations,
            avg_execution_time_ms=new_avg_time,
            success_rate=new_success_rate,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            metadata=self.metadata,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "name": self.name,
            "display_name": self.display_name,
            "system_prompt": self.system_prompt,
            "trigger": self.trigger.to_dict(),
            "persona_files": list(self.persona_files),
            "model": self.model.value,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "max_iterations": self.max_iterations,
            "allowed_tools": list(self.allowed_tools),
            "allowed_skills": list(self.allowed_skills),
            "allowed_mcp_servers": list(self.allowed_mcp_servers),
            "bindings": [b.to_dict() for b in self.bindings],
            "workspace_dir": self.workspace_dir,
            "workspace_config": (self.workspace_config.to_dict()),
            "can_spawn": self.can_spawn,
            "max_spawn_depth": self.max_spawn_depth,
            "agent_to_agent_enabled": (self.agent_to_agent_enabled),
            "discoverable": self.discoverable,
            "source": (self.source.value if isinstance(self.source, AgentSource) else self.source),
            "enabled": self.enabled,
            "max_retries": self.max_retries,
            "fallback_models": list(self.fallback_models),
            "total_invocations": self.total_invocations,
            "avg_execution_time_ms": (self.avg_execution_time_ms),
            "success_rate": self.success_rate,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Agent":
        """Create from dictionary (e.g., from database)."""
        trigger_data = data.get("trigger", {})
        if isinstance(trigger_data, dict):
            trigger = AgentTrigger.from_dict(trigger_data)
        else:
            trigger = AgentTrigger(description=(str(trigger_data) or "Default agent trigger"))

        bindings_data = data.get("bindings", [])
        bindings = [AgentBinding.from_dict(b) if isinstance(b, dict) else b for b in bindings_data]

        ws_data = data.get("workspace_config", {})
        workspace_config = (
            WorkspaceConfig.from_dict(ws_data) if isinstance(ws_data, dict) else ws_data
        )

        return cls(
            id=data["id"],
            tenant_id=data["tenant_id"],
            project_id=data.get("project_id"),
            name=data["name"],
            display_name=data.get("display_name", data["name"]),
            system_prompt=data["system_prompt"],
            trigger=trigger,
            persona_files=data.get("persona_files", []),
            model=AgentModel(data.get("model", "inherit")),
            temperature=data.get("temperature", 0.7),
            max_tokens=data.get("max_tokens", 4096),
            max_iterations=data.get("max_iterations", 10),
            allowed_tools=data.get("allowed_tools", ["*"]),
            allowed_skills=data.get("allowed_skills", []),
            allowed_mcp_servers=data.get("allowed_mcp_servers", []),
            bindings=bindings,
            workspace_dir=data.get("workspace_dir"),
            workspace_config=workspace_config,
            can_spawn=data.get("can_spawn", False),
            max_spawn_depth=data.get("max_spawn_depth", 3),
            agent_to_agent_enabled=data.get("agent_to_agent_enabled", False),
            discoverable=data.get("discoverable", True),
            source=(AgentSource(data["source"]) if "source" in data else AgentSource.DATABASE),
            enabled=data.get("enabled", True),
            max_retries=data.get("max_retries", 0),
            fallback_models=data.get("fallback_models", []),
            total_invocations=data.get("total_invocations", 0),
            avg_execution_time_ms=data.get("avg_execution_time_ms", 0.0),
            success_rate=data.get("success_rate", 1.0),
            created_at=(
                datetime.fromisoformat(data["created_at"])
                if "created_at" in data
                else datetime.now(UTC)
            ),
            updated_at=(
                datetime.fromisoformat(data["updated_at"])
                if "updated_at" in data
                else datetime.now(UTC)
            ),
            metadata=data.get("metadata"),
        )

    @classmethod
    def create(  # noqa: PLR0913
        cls,
        tenant_id: str,
        name: str,
        display_name: str,
        system_prompt: str,
        trigger_description: str = "Default agent trigger",
        trigger_examples: list[str] | None = None,
        trigger_keywords: list[str] | None = None,
        project_id: str | None = None,
        persona_files: list[str] | None = None,
        model: AgentModel = AgentModel.INHERIT,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        max_iterations: int = 10,
        allowed_tools: list[str] | None = None,
        allowed_skills: list[str] | None = None,
        allowed_mcp_servers: list[str] | None = None,
        bindings: list[AgentBinding] | None = None,
        workspace_dir: str | None = None,
        workspace_config: WorkspaceConfig | None = None,
        can_spawn: bool = False,
        max_spawn_depth: int = 3,
        agent_to_agent_enabled: bool = False,
        discoverable: bool = True,
        max_retries: int = 0,
        fallback_models: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "Agent":
        """Create a new agent with generated ID."""
        import uuid

        trigger = AgentTrigger(
            description=trigger_description,
            examples=trigger_examples or [],
            keywords=trigger_keywords or [],
        )

        return cls(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            project_id=project_id,
            name=name,
            display_name=display_name,
            system_prompt=system_prompt,
            trigger=trigger,
            persona_files=persona_files or [],
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            max_iterations=max_iterations,
            allowed_tools=allowed_tools or ["*"],
            allowed_skills=allowed_skills or [],
            allowed_mcp_servers=(allowed_mcp_servers or []),
            bindings=bindings or [],
            workspace_dir=workspace_dir,
            workspace_config=(workspace_config or WorkspaceConfig()),
            can_spawn=can_spawn,
            max_spawn_depth=max_spawn_depth,
            agent_to_agent_enabled=(agent_to_agent_enabled),
            discoverable=discoverable,
            max_retries=max_retries,
            fallback_models=fallback_models or [],
            metadata=metadata,
        )
