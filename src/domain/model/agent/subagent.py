"""
SubAgent entity for the Agent SubAgent System.

Represents a specialized sub-agent that can handle specific types of tasks
with isolated tool access and custom system prompts.

SubAgents are the L3 layer in the four-layer capability architecture:
Tool (L1) -> Skill (L2) -> SubAgent (L3) -> Agent (L4)

Attributes:
    trigger: How the subagent is activated
    model: LLM model configuration
    allowed_tools: Tools this subagent can access
    allowed_skills: Skills this subagent can use
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from src.domain.model.agent.spawn_policy import SpawnPolicy
from src.domain.model.agent.subagent_source import SubAgentSource
from src.domain.model.agent.tool_policy import ToolPolicy

if TYPE_CHECKING:
    from src.domain.model.agent.identity import AgentIdentity


class AgentModel(str, Enum):
    """Model configuration for subagent."""

    INHERIT = "inherit"  # Use parent agent's model
    QWEN_MAX = "qwen-max"
    QWEN_PLUS = "qwen-plus"
    GPT4 = "gpt-4"
    GPT4O = "gpt-4o"
    CLAUDE_SONNET = "claude-3-5-sonnet"
    DEEPSEEK = "deepseek-chat"
    GEMINI = "gemini-pro"


@dataclass(frozen=True)
class AgentTrigger:
    """
    Trigger configuration for a subagent.

    Defines when this subagent should be activated.

    Attributes:
        description: Description of when to use this subagent
        examples: Example queries/tasks that should route to this subagent
        keywords: Optional keywords for quick matching
    """

    description: str
    examples: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate the trigger."""
        if not self.description:
            raise ValueError("description cannot be empty")

    def matches_keywords(self, query: str) -> bool:
        """Check if query contains any trigger keywords."""
        if not self.keywords:
            return False
        query_lower = query.lower()
        return any(kw.lower() in query_lower for kw in self.keywords)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "description": self.description,
            "examples": list(self.examples) if self.examples else [],
            "keywords": list(self.keywords) if self.keywords else [],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentTrigger:
        """Create from dictionary."""
        return cls(
            description=data.get("description", ""),
            examples=data.get("examples", []),
            keywords=data.get("keywords", []),
        )


def serialize_spawn_policy(policy: SpawnPolicy | None) -> dict[str, Any] | None:
    if policy is None:
        return None
    allowed = list(policy.allowed_subagents) if policy.allowed_subagents is not None else None
    return {
        "max_depth": policy.max_depth,
        "max_active_runs": policy.max_active_runs,
        "max_children_per_requester": policy.max_children_per_requester,
        "allowed_subagents": allowed,
    }


def deserialize_spawn_policy(data: dict[str, Any] | None) -> SpawnPolicy | None:
    if data is None:
        return None
    raw_allowed = data.get("allowed_subagents")
    allowed = frozenset(raw_allowed) if raw_allowed is not None else None
    return SpawnPolicy(
        max_depth=data.get("max_depth", 2),
        max_active_runs=data.get("max_active_runs", 16),
        max_children_per_requester=data.get("max_children_per_requester", 8),
        allowed_subagents=allowed,
    )


def serialize_tool_policy(policy: ToolPolicy | None) -> dict[str, Any] | None:
    if policy is None:
        return None
    return {
        "allow": list(policy.allow),
        "deny": list(policy.deny),
        "precedence": policy.precedence.value,
    }


def deserialize_tool_policy(data: dict[str, Any] | None) -> ToolPolicy | None:
    if data is None:
        return None
    from src.domain.model.agent.tool_policy import ToolPolicyPrecedence

    return ToolPolicy(
        allow=tuple(data.get("allow", ())),
        deny=tuple(data.get("deny", ())),
        precedence=ToolPolicyPrecedence(data.get("precedence", "deny_first")),
    )


def serialize_identity(identity: AgentIdentity | None) -> dict[str, Any] | None:
    if identity is None:
        return None
    return {
        "agent_id": identity.agent_id,
        "name": identity.name,
        "description": identity.description,
        "system_prompt": identity.system_prompt,
        "model": identity.model.value,
        "allowed_tools": list(identity.allowed_tools),
        "allowed_skills": list(identity.allowed_skills),
        "spawn_policy": serialize_spawn_policy(identity.spawn_policy),
        "tool_policy": serialize_tool_policy(identity.tool_policy),
        "metadata": dict(identity.metadata) if identity.metadata else {},
    }


def deserialize_identity(data: dict[str, Any] | None) -> AgentIdentity | None:
    if data is None:
        return None
    from src.domain.model.agent.identity import AgentIdentity as _AgentIdentity

    sp = deserialize_spawn_policy(data.get("spawn_policy"))
    tp = deserialize_tool_policy(data.get("tool_policy"))
    raw_meta = data.get("metadata", {})
    meta_tuple = tuple((k, v) for k, v in raw_meta.items()) if raw_meta else ()
    return _AgentIdentity(
        agent_id=data["agent_id"],
        name=data["name"],
        description=data.get("description", ""),
        system_prompt=data.get("system_prompt", ""),
        model=AgentModel(data.get("model", "inherit")),
        allowed_tools=tuple(data.get("allowed_tools", ())),
        allowed_skills=tuple(data.get("allowed_skills", ())),
        spawn_policy=sp if sp is not None else SpawnPolicy(),
        tool_policy=tp if tp is not None else ToolPolicy(),
        metadata=meta_tuple,
    )


@dataclass
class SubAgent:
    """
    A specialized sub-agent for handling specific task types.

    SubAgents provide isolated execution environments with:
    - Custom system prompts for specialized behavior
    - Restricted tool access for safety
    - Separate model configuration for cost optimization
    - Usage statistics for performance tracking

    Tenant-level scoping: SubAgents are shared across all projects within
    a tenant but isolated between tenants.

    Attributes:
        id: Unique identifier
        tenant_id: ID of the tenant that owns this subagent
        name: Unique name identifier (used for routing)
        display_name: Human-readable display name
        system_prompt: Custom system prompt for this subagent
        trigger: Trigger configuration
        model: LLM model to use
        color: UI display color
        allowed_tools: List of tool names this subagent can use
        allowed_skills: List of skill IDs this subagent can use
        allowed_mcp_servers: List of MCP server names this subagent can use
        max_tokens: Maximum tokens for responses
        temperature: LLM temperature setting
        max_iterations: Maximum ReAct iterations
        enabled: Whether this subagent is enabled
        total_invocations: Total number of times invoked
        avg_execution_time_ms: Average execution time in milliseconds
        success_rate: Historical success rate
        project_id: Optional project-specific subagent
        created_at: When this subagent was created
        updated_at: When this subagent was last modified
        metadata: Optional additional metadata
    """

    id: str
    tenant_id: str
    name: str
    display_name: str
    system_prompt: str
    trigger: AgentTrigger
    model: AgentModel = AgentModel.INHERIT
    color: str = "blue"
    allowed_tools: list[str] = field(default_factory=lambda: ["*"])
    allowed_skills: list[str] = field(default_factory=list)
    allowed_mcp_servers: list[str] = field(default_factory=list)
    max_tokens: int = 4096
    temperature: float = 0.7
    max_iterations: int = 10
    enabled: bool = True
    total_invocations: int = 0
    avg_execution_time_ms: float = 0.0
    success_rate: float = 1.0
    project_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] | None = None
    source: SubAgentSource = SubAgentSource.DATABASE
    file_path: str | None = None
    max_retries: int = 0
    fallback_models: list[str] = field(default_factory=list)
    spawn_policy: SpawnPolicy | None = None
    tool_policy: ToolPolicy | None = None
    identity: AgentIdentity | None = None

    def __post_init__(self) -> None:
        """Validate the subagent."""
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

    def is_enabled(self) -> bool:
        """Check if subagent is enabled."""
        return self.enabled

    def has_tool_access(self, tool_name: str) -> bool:
        """
        Check if this subagent can use a specific tool.

        Args:
            tool_name: Name of the tool

        Returns:
            True if the subagent can use the tool
        """
        if "*" in self.allowed_tools:
            return True
        return tool_name in self.allowed_tools

    def has_skill_access(self, skill_id: str) -> bool:
        """
        Check if this subagent can use a specific skill.

        Args:
            skill_id: ID of the skill

        Returns:
            True if the subagent can use the skill
        """
        if not self.allowed_skills:
            return True  # Empty means all skills allowed
        return skill_id in self.allowed_skills

    def has_mcp_access(self, server_name: str) -> bool:
        """
        Check if this subagent can use a specific MCP server.

        Args:
            server_name: Name of the MCP server

        Returns:
            True if the subagent can use the server
        """
        if "*" in self.allowed_mcp_servers:
            return True
        return server_name in self.allowed_mcp_servers

    def get_filtered_tools(self, available_tools: list[str]) -> list[str]:
        """
        Get tools filtered by this subagent's allowed tools.

        Args:
            available_tools: List of all available tool names

        Returns:
            List of tools this subagent can use
        """
        if "*" in self.allowed_tools:
            return list(available_tools)
        return [t for t in available_tools if t in self.allowed_tools]

    def record_execution(self, execution_time_ms: float, success: bool) -> SubAgent:
        """
        Record an execution of this subagent.

        Args:
            execution_time_ms: Execution time in milliseconds
            success: Whether the execution was successful

        Returns:
            Updated subagent
        """
        new_invocations = self.total_invocations + 1

        # Update running average of execution time
        if self.total_invocations == 0:
            new_avg_time = execution_time_ms
        else:
            new_avg_time = (
                self.avg_execution_time_ms * self.total_invocations + execution_time_ms
            ) / new_invocations

        # Update success rate using running average
        if self.total_invocations == 0:
            new_success_rate = 1.0 if success else 0.0
        else:
            success_value = 1.0 if success else 0.0
            new_success_rate = (
                self.success_rate * self.total_invocations + success_value
            ) / new_invocations

        return SubAgent(
            id=self.id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            name=self.name,
            display_name=self.display_name,
            system_prompt=self.system_prompt,
            trigger=self.trigger,
            model=self.model,
            color=self.color,
            allowed_tools=list(self.allowed_tools),
            allowed_skills=list(self.allowed_skills),
            allowed_mcp_servers=list(self.allowed_mcp_servers),
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            max_iterations=self.max_iterations,
            enabled=self.enabled,
            total_invocations=new_invocations,
            avg_execution_time_ms=new_avg_time,
            success_rate=new_success_rate,
            created_at=self.created_at,
            updated_at=datetime.now(UTC),
            metadata=self.metadata,
            source=self.source,
            file_path=self.file_path,
            max_retries=self.max_retries,
            fallback_models=list(self.fallback_models),
            spawn_policy=self.spawn_policy,
            tool_policy=self.tool_policy,
            identity=self.identity,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        result: dict[str, Any] = {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "name": self.name,
            "display_name": self.display_name,
            "system_prompt": self.system_prompt,
            "trigger": self.trigger.to_dict(),
            "model": self.model.value,
            "color": self.color,
            "allowed_tools": list(self.allowed_tools),
            "allowed_skills": list(self.allowed_skills),
            "allowed_mcp_servers": list(self.allowed_mcp_servers),
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "max_iterations": self.max_iterations,
            "enabled": self.enabled,
            "total_invocations": self.total_invocations,
            "avg_execution_time_ms": self.avg_execution_time_ms,
            "success_rate": self.success_rate,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
            "source": self.source.value if isinstance(self.source, SubAgentSource) else self.source,
            "file_path": self.file_path,
            "max_retries": self.max_retries,
            "fallback_models": list(self.fallback_models),
            "spawn_policy": serialize_spawn_policy(self.spawn_policy),
            "tool_policy": serialize_tool_policy(self.tool_policy),
            "identity": serialize_identity(self.identity),
        }
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SubAgent:
        """Create from dictionary (e.g., from database)."""
        trigger_data = data.get("trigger", {})
        if isinstance(trigger_data, dict):
            trigger = AgentTrigger.from_dict(trigger_data)
        else:
            trigger = AgentTrigger(description=str(trigger_data) or "Default trigger")

        return cls(
            id=data["id"],
            tenant_id=data["tenant_id"],
            project_id=data.get("project_id"),
            name=data["name"],
            display_name=data.get("display_name", data["name"]),
            system_prompt=data["system_prompt"],
            trigger=trigger,
            model=AgentModel(data.get("model", "inherit")),
            color=data.get("color", "blue"),
            allowed_tools=data.get("allowed_tools", ["*"]),
            allowed_skills=data.get("allowed_skills", []),
            allowed_mcp_servers=data.get("allowed_mcp_servers", []),
            max_tokens=data.get("max_tokens", 4096),
            temperature=data.get("temperature", 0.7),
            max_iterations=data.get("max_iterations", 10),
            enabled=data.get("enabled", True),
            total_invocations=data.get("total_invocations", 0),
            avg_execution_time_ms=data.get("avg_execution_time_ms", 0.0),
            success_rate=data.get("success_rate", 1.0),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(UTC),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if "updated_at" in data
            else datetime.now(UTC),
            metadata=data.get("metadata"),
            source=SubAgentSource(data["source"]) if "source" in data else SubAgentSource.DATABASE,
            file_path=data.get("file_path"),
            max_retries=data.get("max_retries", 0),
            fallback_models=data.get("fallback_models", []),
            spawn_policy=deserialize_spawn_policy(data.get("spawn_policy")),
            tool_policy=deserialize_tool_policy(data.get("tool_policy")),
            identity=deserialize_identity(data.get("identity")),
        )

    @classmethod
    def create(  # noqa: PLR0913
        cls,
        tenant_id: str,
        name: str,
        display_name: str,
        system_prompt: str,
        trigger_description: str,
        trigger_examples: list[str] | None = None,
        trigger_keywords: list[str] | None = None,
        model: AgentModel = AgentModel.INHERIT,
        color: str = "blue",
        allowed_tools: list[str] | None = None,
        allowed_skills: list[str] | None = None,
        allowed_mcp_servers: list[str] | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        max_iterations: int = 10,
        project_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        max_retries: int = 0,
        fallback_models: list[str] | None = None,
        spawn_policy: SpawnPolicy | None = None,
        tool_policy: ToolPolicy | None = None,
        identity: AgentIdentity | None = None,
    ) -> SubAgent:
        """
        Create a new subagent.

        Args:
            tenant_id: Tenant ID
            name: Unique name identifier
            display_name: Human-readable display name
            system_prompt: Custom system prompt
            trigger_description: Description of when to use this subagent
            trigger_examples: Example queries
            trigger_keywords: Keywords for quick matching
            model: LLM model to use
            color: UI display color
            allowed_tools: Tools this subagent can use
            allowed_skills: Skills this subagent can use
            allowed_mcp_servers: MCP servers this subagent can use
            max_tokens: Maximum tokens
            temperature: LLM temperature
            max_iterations: Maximum ReAct iterations
            project_id: Optional project ID
            metadata: Optional metadata
            max_retries: Maximum retries on failure
            fallback_models: Fallback model list
            spawn_policy: Optional spawn policy
            tool_policy: Optional tool policy
            identity: Optional agent identity

        Returns:
            New subagent instance
        """
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
            model=model,
            color=color,
            allowed_tools=allowed_tools or ["*"],
            allowed_skills=allowed_skills or [],
            allowed_mcp_servers=allowed_mcp_servers or [],
            max_tokens=max_tokens,
            temperature=temperature,
            max_iterations=max_iterations,
            metadata=metadata,
            max_retries=max_retries,
            fallback_models=fallback_models or [],
            spawn_policy=spawn_policy,
            tool_policy=tool_policy,
            identity=identity,
        )


# Predefined subagent templates
RESEARCHER_SUBAGENT_TEMPLATE = {
    "name": "researcher",
    "display_name": "Research Assistant",
    "system_prompt": """You are a research assistant specialized in finding and analyzing information.
Your role is to:
1. Search memories and knowledge graphs for relevant information
2. Synthesize findings into clear, concise summaries
3. Identify knowledge gaps and suggest further research

Be thorough but focused. Always cite your sources.""",
    "trigger_description": "Research tasks, information gathering, knowledge synthesis",
    "trigger_keywords": ["research", "find", "search", "analyze", "summarize"],
    "allowed_tools": ["memory_search", "entity_lookup", "graph_query"],
    "color": "purple",
}

CODER_SUBAGENT_TEMPLATE = {
    "name": "coder",
    "display_name": "Code Assistant",
    "system_prompt": """You are a coding assistant specialized in software development tasks.
Your role is to:
1. Write, review, and explain code
2. Debug issues and suggest improvements
3. Follow best practices and coding standards

Be precise and include code examples when helpful.""",
    "trigger_description": "Coding tasks, debugging, code review, implementation",
    "trigger_keywords": ["code", "implement", "debug", "fix", "program"],
    "allowed_tools": ["*"],
    "color": "green",
}

WRITER_SUBAGENT_TEMPLATE = {
    "name": "writer",
    "display_name": "Content Writer",
    "system_prompt": """You are a content writer specialized in creating clear, engaging content.
Your role is to:
1. Write and edit various types of content
2. Adapt tone and style to the audience
3. Ensure clarity and proper structure

Be creative while maintaining accuracy.""",
    "trigger_description": "Writing tasks, content creation, editing, documentation",
    "trigger_keywords": ["write", "draft", "edit", "document", "compose"],
    "allowed_tools": ["memory_search", "memory_create"],
    "color": "orange",
}
