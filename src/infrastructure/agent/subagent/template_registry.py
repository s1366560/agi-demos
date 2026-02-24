"""SubAgent template registry for marketplace support.

Provides serialization, registration, discovery, and versioning of SubAgent
configurations as reusable templates.

Usage:
    registry = TemplateRegistry()
    template = SubAgentTemplate.from_subagent(my_subagent, author="team-a")
    registry.register(template)

    found = registry.search("code review")
    subagent = found[0].to_subagent()
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_TEMPLATES = 200


@dataclass
class SubAgentTemplate:
    """Serializable SubAgent configuration template.

    Attributes:
        template_id: Unique template identifier.
        name: Display name.
        description: What this SubAgent does.
        version: Semantic version string.
        author: Who created this template.
        category: Classification (e.g., "code", "research", "writing").
        system_prompt: The SubAgent's system prompt.
        model_preference: Preferred model (or "inherit").
        temperature: LLM temperature.
        max_iterations: Maximum ReAct steps.
        max_tokens: Maximum output tokens.
        trigger_keywords: Keywords for routing.
        trigger_description: Natural language trigger description.
        trigger_examples: Example queries that should route here.
        tool_filter_tags: Tags to filter available tools.
        tags: Searchable tags.
        metadata: Additional configuration.
        created_at: Creation timestamp.
        usage_count: How many times this template has been instantiated.
    """

    template_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    version: str = "1.0.0"
    author: str = ""
    category: str = "general"
    system_prompt: str = ""
    model_preference: str = "inherit"
    temperature: float = 0.7
    max_iterations: int = 15
    max_tokens: int = 4096
    trigger_keywords: List[str] = field(default_factory=list)
    trigger_description: str = ""
    trigger_examples: List[str] = field(default_factory=list)
    tool_filter_tags: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    usage_count: int = 0

    @classmethod
    def from_subagent(
        cls,
        subagent: Any,  # noqa: ANN401
        author: str = "",
        category: str = "general",
        version: str = "1.0.0",
    ) -> "SubAgentTemplate":
        """Create a template from an existing SubAgent instance.

        Args:
            subagent: SubAgent domain model instance.
            author: Template author name.
            category: Template category.
            version: Template version.

        Returns:
            SubAgentTemplate ready for registration.
        """
        trigger = getattr(subagent, "trigger", None)
        keywords = []
        description = ""
        examples = []

        if trigger:
            keywords = list(getattr(trigger, "keywords", []))
            description = getattr(trigger, "description", "")
            examples = list(getattr(trigger, "examples", []))

        return cls(
            name=getattr(subagent, "name", ""),
            description=getattr(subagent, "description", ""),
            system_prompt=getattr(subagent, "system_prompt", ""),
            model_preference=getattr(subagent, "model", "inherit"),
            temperature=getattr(subagent, "temperature", 0.7),
            max_iterations=getattr(subagent, "max_iterations", 15),
            max_tokens=getattr(subagent, "max_tokens", 4096),
            trigger_keywords=keywords,
            trigger_description=description,
            trigger_examples=examples,
            tool_filter_tags=list(getattr(subagent, "tool_filter_tags", [])),
            tags=list(getattr(subagent, "tags", [])),
            author=author,
            category=category,
            version=version,
        )

    def to_subagent(self, project_id: str = "", tenant_id: str = "") -> Any:  # noqa: ANN401
        """Instantiate a SubAgent from this template.

        Args:
            project_id: Project scope for the new SubAgent.
            tenant_id: Tenant scope for the new SubAgent.

        Returns:
            SubAgent domain model instance.
        """
        from src.domain.model.agent.subagent import AgentModel, SubAgent

        model_value = self.model_preference
        try:
            model = AgentModel(model_value)
        except (ValueError, KeyError):
            model = AgentModel.INHERIT

        self.usage_count += 1

        return SubAgent.create(
            tenant_id=tenant_id or "default",
            name=self.name,
            display_name=self.name,
            system_prompt=self.system_prompt or f"You are {self.name}.",
            model=model,
            temperature=self.temperature,
            max_iterations=self.max_iterations,
            max_tokens=self.max_tokens,
            trigger_description=self.trigger_description or f"Handle {self.name} tasks",
            trigger_keywords=self.trigger_keywords,
            trigger_examples=self.trigger_examples,
            project_id=project_id or None,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize template to dict for storage/transport."""
        return {
            "template_id": self.template_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "author": self.author,
            "category": self.category,
            "system_prompt": self.system_prompt,
            "model_preference": self.model_preference
            if isinstance(self.model_preference, str)
            else str(self.model_preference),
            "temperature": self.temperature,
            "max_iterations": self.max_iterations,
            "max_tokens": self.max_tokens,
            "trigger_keywords": self.trigger_keywords,
            "trigger_description": self.trigger_description,
            "trigger_examples": self.trigger_examples,
            "tool_filter_tags": self.tool_filter_tags,
            "tags": self.tags,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "usage_count": self.usage_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubAgentTemplate":
        """Deserialize template from dict."""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)
        elif not isinstance(created_at, datetime):
            created_at = datetime.now(timezone.utc)

        return cls(
            template_id=data.get("template_id", str(uuid.uuid4())),
            name=data.get("name", ""),
            description=data.get("description", ""),
            version=data.get("version", "1.0.0"),
            author=data.get("author", ""),
            category=data.get("category", "general"),
            system_prompt=data.get("system_prompt", ""),
            model_preference=data.get("model_preference", "inherit"),
            temperature=data.get("temperature", 0.7),
            max_iterations=data.get("max_iterations", 15),
            max_tokens=data.get("max_tokens", 4096),
            trigger_keywords=data.get("trigger_keywords", []),
            trigger_description=data.get("trigger_description", ""),
            trigger_examples=data.get("trigger_examples", []),
            tool_filter_tags=data.get("tool_filter_tags", []),
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
            created_at=created_at,
            usage_count=data.get("usage_count", 0),
        )


class TemplateRegistry:
    """In-memory registry for SubAgent templates.

    Provides registration, search, and version management.
    Can be extended with persistent storage (DB/Redis) in the future.
    """

    def __init__(self) -> None:
        self._templates: Dict[str, SubAgentTemplate] = {}
        # name -> list of template_ids (for version history)
        self._name_index: Dict[str, List[str]] = {}

    def register(self, template: SubAgentTemplate) -> str:
        """Register a new template.

        Args:
            template: Template to register.

        Returns:
            The template_id.

        Raises:
            ValueError: If registry is full.
        """
        if len(self._templates) >= MAX_TEMPLATES:
            raise ValueError(f"Registry full (max {MAX_TEMPLATES} templates)")

        self._templates[template.template_id] = template

        name_key = template.name.lower()
        if name_key not in self._name_index:
            self._name_index[name_key] = []
        self._name_index[name_key].append(template.template_id)

        logger.info(
            f"[TemplateRegistry] Registered '{template.name}' v{template.version} "
            f"(id={template.template_id})"
        )
        return template.template_id

    def get(self, template_id: str) -> Optional[SubAgentTemplate]:
        """Get a template by ID."""
        return self._templates.get(template_id)

    def get_by_name(self, name: str) -> Optional[SubAgentTemplate]:
        """Get the latest version of a template by name."""
        name_key = name.lower()
        ids = self._name_index.get(name_key, [])
        if not ids:
            return None
        return self._templates.get(ids[-1])

    def unregister(self, template_id: str) -> bool:
        """Remove a template from the registry."""
        template = self._templates.pop(template_id, None)
        if not template:
            return False

        name_key = template.name.lower()
        ids = self._name_index.get(name_key, [])
        if template_id in ids:
            ids.remove(template_id)
            if not ids:
                del self._name_index[name_key]

        return True

    def search(
        self,
        query: str = "",
        category: str = "",
        tags: Optional[List[str]] = None,
    ) -> List[SubAgentTemplate]:
        """Search templates by query text, category, and/or tags.

        Args:
            query: Free-text search across name, description, trigger info.
            category: Filter by category.
            tags: Filter by tags (any match).

        Returns:
            Matching templates sorted by usage_count descending.
        """
        results: List[SubAgentTemplate] = []
        query_lower = query.lower()

        for template in self._templates.values():
            if category and template.category != category:
                continue

            if tags:
                if not any(t in template.tags for t in tags):
                    continue

            if query_lower:
                searchable = " ".join([
                    template.name,
                    template.description,
                    template.trigger_description,
                    " ".join(template.trigger_keywords),
                    " ".join(template.tags),
                ]).lower()

                if query_lower not in searchable:
                    continue

            results.append(template)

        results.sort(key=lambda t: t.usage_count, reverse=True)
        return results

    def list_all(self) -> List[SubAgentTemplate]:
        """List all registered templates."""
        return list(self._templates.values())

    def list_categories(self) -> List[str]:
        """List distinct categories."""
        return sorted({t.category for t in self._templates.values()})

    def get_versions(self, name: str) -> List[SubAgentTemplate]:
        """Get all versions of a template by name."""
        name_key = name.lower()
        ids = self._name_index.get(name_key, [])
        return [self._templates[tid] for tid in ids if tid in self._templates]

    def clear(self) -> None:
        """Clear all templates."""
        self._templates.clear()
        self._name_index.clear()
