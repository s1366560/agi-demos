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
from src.domain.model.agent.delegate_config import DelegateConfig
from src.domain.model.agent.identity import AgentIdentity
from src.domain.model.agent.session_policy import SessionPolicy
from src.domain.model.agent.spawn_policy import SpawnPolicy
from src.domain.model.agent.subagent import AgentModel, AgentTrigger
from src.domain.model.agent.tool_policy import ToolPolicy
from src.domain.model.agent.workspace_config import WorkspaceConfig

_RESERVED_AGENT_REFS = frozenset({"__system__"})
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
    agent_to_agent_allowlist: list[str] | None = None
    discoverable: bool = True

    # Policy VOs (multi-agent governance)
    spawn_policy: SpawnPolicy | None = None
    tool_policy: ToolPolicy | None = None
    session_policy: SessionPolicy | None = None
    delegate_config: DelegateConfig | None = None
    identity: AgentIdentity | None = None

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
        self.validate()

    def validate(self) -> None:
        """Validate the current agent state after create or update."""
        self._validate_identity_fields()
        self._validate_runtime_limits()
        self.agent_to_agent_allowlist = self.normalize_agent_to_agent_allowlist(
            self.agent_to_agent_allowlist
        )

    def _validate_identity_fields(self) -> None:
        """Validate required identity and naming fields."""
        if not self.id:
            raise ValueError("id cannot be empty")
        if self.id in _RESERVED_AGENT_REFS:
            raise ValueError("id uses a reserved agent identifier")
        if not self.tenant_id:
            raise ValueError("tenant_id cannot be empty")
        if not self.name:
            raise ValueError("name cannot be empty")
        if self.name in _RESERVED_AGENT_REFS:
            raise ValueError("name uses a reserved agent identifier")
        if not self.display_name:
            raise ValueError("display_name cannot be empty")
        if not self.system_prompt:
            raise ValueError("system_prompt cannot be empty")

    def _validate_runtime_limits(self) -> None:
        """Validate numeric runtime limits and metrics."""
        if not isinstance(self.model, AgentModel):
            raise ValueError("model must be a valid AgentModel")
        if not isinstance(self.workspace_config, WorkspaceConfig):
            raise ValueError("workspace_config must be a WorkspaceConfig")
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

    @staticmethod
    def normalize_agent_to_agent_allowlist(allowlist: list[str] | None) -> list[str] | None:
        """Normalize an agent-to-agent allowlist while preserving legacy None semantics."""
        if allowlist is None:
            return None

        normalized: list[str] = []
        seen: set[str] = set()
        for raw_value in allowlist:
            normalized_value = raw_value.strip()
            if not normalized_value or normalized_value in seen:
                continue
            seen.add(normalized_value)
            normalized.append(normalized_value)
        return normalized

    def has_legacy_open_agent_to_agent_policy(self) -> bool:
        """Return whether the agent still relies on the legacy implicit-open A2A policy."""
        return (
            self.source != AgentSource.BUILTIN
            and self.agent_to_agent_enabled
            and self.agent_to_agent_allowlist is None
        )

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

    def accepts_messages_from(self, sender_agent_id: str) -> bool:
        """Check if this agent accepts messages from a given sender.

        Resolution order:
        1. If agent_to_agent_enabled is False -> reject all.
        2. Built-in agents may use allowlist=None as an explicit trusted-open policy.
        3. Non-built-in agents with allowlist=None reject until the policy is made explicit.
        4. If allowlist is empty -> reject all.
        5. Otherwise check membership.
        """
        if not self.agent_to_agent_enabled:
            return False
        if self.agent_to_agent_allowlist is None:
            return self.source == AgentSource.BUILTIN
        return sender_agent_id.strip() in self.agent_to_agent_allowlist

    def to_identity(self) -> AgentIdentity:
        """Build an AgentIdentity snapshot from this Agent's current state."""
        return AgentIdentity(
            agent_id=self.id,
            name=self.name,
            description=self.display_name,
            system_prompt=self.system_prompt,
            model=self.model,
            allowed_tools=tuple(self.allowed_tools),
            allowed_skills=tuple(self.allowed_skills),
            spawn_policy=self.spawn_policy or SpawnPolicy(),
            tool_policy=self.tool_policy or ToolPolicy(),
            metadata=tuple((k, str(v)) for k, v in (self.metadata or {}).items()),
        )

    def _spawn_policy_to_dict(self) -> dict[str, Any] | None:
        if self.spawn_policy is None:
            return None
        sp = self.spawn_policy
        return {
            "max_depth": sp.max_depth,
            "max_active_runs": sp.max_active_runs,
            "max_children_per_requester": sp.max_children_per_requester,
            "allowed_subagents": (
                sorted(sp.allowed_subagents) if sp.allowed_subagents is not None else None
            ),
        }

    def _tool_policy_to_dict(self) -> dict[str, Any] | None:
        if self.tool_policy is None:
            return None
        tp = self.tool_policy
        return {
            "allow": list(tp.allow),
            "deny": list(tp.deny),
            "precedence": tp.precedence.value,
        }

    def _session_policy_to_dict(self) -> dict[str, Any] | None:
        if self.session_policy is None:
            return None
        return self.session_policy.to_dict()

    def _delegate_config_to_dict(self) -> dict[str, Any] | None:
        if self.delegate_config is None:
            return None
        return self.delegate_config.to_dict()

    def _agent_allowlist_to_dict(self) -> list[str] | None:
        return (
            list(self.agent_to_agent_allowlist)
            if self.agent_to_agent_allowlist is not None
            else None
        )

    @staticmethod
    def _agent_allowlist_from_dict(data: list[str] | None) -> list[str] | None:
        return list(data) if data is not None else None

    @staticmethod
    def _spawn_policy_from_dict(data: dict[str, Any] | None) -> SpawnPolicy | None:
        if data is None or not isinstance(data, dict):
            return None
        raw_allowed = data.get("allowed_subagents")
        return SpawnPolicy(
            max_depth=data.get("max_depth", 2),
            max_active_runs=data.get("max_active_runs", 16),
            max_children_per_requester=data.get("max_children_per_requester", 8),
            allowed_subagents=(frozenset(raw_allowed) if raw_allowed is not None else None),
        )

    @staticmethod
    def _tool_policy_from_dict(data: dict[str, Any] | None) -> ToolPolicy | None:
        if data is None or not isinstance(data, dict):
            return None
        from src.domain.model.agent.tool_policy import ToolPolicyPrecedence

        return ToolPolicy(
            allow=tuple(data.get("allow", ())),
            deny=tuple(data.get("deny", ())),
            precedence=ToolPolicyPrecedence(
                data.get("precedence", ToolPolicyPrecedence.DENY_FIRST.value)
            ),
        )

    @staticmethod
    def _session_policy_from_dict(data: dict[str, Any] | None) -> SessionPolicy | None:
        if data is None or not isinstance(data, dict):
            return None
        return SessionPolicy.from_dict(data)

    @staticmethod
    def _delegate_config_from_dict(data: dict[str, Any] | None) -> DelegateConfig | None:
        if data is None or not isinstance(data, dict):
            return None
        return DelegateConfig.from_dict(data)

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
            agent_to_agent_allowlist=(
                list(self.agent_to_agent_allowlist)
                if self.agent_to_agent_allowlist is not None
                else None
            ),
            discoverable=self.discoverable,
            spawn_policy=self.spawn_policy,
            tool_policy=self.tool_policy,
            session_policy=self.session_policy,
            delegate_config=self.delegate_config,
            identity=self.identity,
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
            "agent_to_agent_allowlist": self._agent_allowlist_to_dict(),
            "discoverable": self.discoverable,
            "spawn_policy": self._spawn_policy_to_dict(),
            "tool_policy": self._tool_policy_to_dict(),
            "session_policy": self._session_policy_to_dict(),
            "delegate_config": self._delegate_config_to_dict(),
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

        spawn_policy = cls._spawn_policy_from_dict(data.get("spawn_policy"))
        tool_policy_vo = cls._tool_policy_from_dict(data.get("tool_policy"))
        session_policy_vo = cls._session_policy_from_dict(data.get("session_policy"))
        delegate_config_vo = cls._delegate_config_from_dict(data.get("delegate_config"))

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
            agent_to_agent_allowlist=cls._agent_allowlist_from_dict(
                data.get("agent_to_agent_allowlist")
            ),
            discoverable=data.get("discoverable", True),
            spawn_policy=spawn_policy,
            tool_policy=tool_policy_vo,
            session_policy=session_policy_vo,
            delegate_config=delegate_config_vo,
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
        agent_to_agent_allowlist: list[str] | None = None,
        discoverable: bool = True,
        max_retries: int = 0,
        fallback_models: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        spawn_policy: SpawnPolicy | None = None,
        tool_policy: ToolPolicy | None = None,
        session_policy: SessionPolicy | None = None,
        delegate_config: DelegateConfig | None = None,
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
            agent_to_agent_allowlist=agent_to_agent_allowlist,
            discoverable=discoverable,
            spawn_policy=spawn_policy,
            tool_policy=tool_policy,
            session_policy=session_policy,
            delegate_config=delegate_config,
            max_retries=max_retries,
            fallback_models=fallback_models or [],
            metadata=metadata,
        )
