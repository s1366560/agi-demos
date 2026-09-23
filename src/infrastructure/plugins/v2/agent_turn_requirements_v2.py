"""Explicit service roots consumed by the Agent turn, prompt and tool construction paths.

These declarations select services, not contribution entry IDs. Catalog contribution
membership remains a separate protocol relationship; these roots alone do not prove
that every configured tool or capability contribution is included in a projection.
"""

from src.domain.model.plugins.generated_v2 import ServiceRequiredV2

# Versions are checked against the actual production Bundle contracts in focused tests.
AGENT_TURN_REQUIRED_SERVICES_V2: tuple[ServiceRequiredV2, ...] = (
    ServiceRequiredV2(alias="turn", service="service:agent.turn-service", version="1.0.0"),
    ServiceRequiredV2(
        alias="definitions", service="service:agent-definition-resolver", version="1.0.0"
    ),
    ServiceRequiredV2(alias="events", service="service:session-event-log", version="1.0.0"),
    ServiceRequiredV2(alias="recovery", service="service:agent.recovery-stream", version="1.0.0"),
    ServiceRequiredV2(alias="worker", service="service:agent.worker-runtime", version="1.0.0"),
    ServiceRequiredV2(alias="loop", service="service:agent-loop-resolver", version="1.0.0"),
    ServiceRequiredV2(
        alias="dispatcher", service="service:agent-runtime-dispatcher", version="1.0.0"
    ),
    ServiceRequiredV2(
        alias="tenant_config",
        service="service:application.tenant-agent-config-services",
        version="1.0.0",
    ),
    ServiceRequiredV2(alias="defaults", service="service:agent-default-selection", version="1.0.0"),
    ServiceRequiredV2(alias="prompt", service="service:system-prompt-builder", version="1.0.0"),
    ServiceRequiredV2(
        alias="prompt_sections", service="service:system-prompt-sections", version="1.0.0"
    ),
    ServiceRequiredV2(alias="tools", service="service:tool-set-resolver", version="1.0.0"),
    ServiceRequiredV2(
        alias="capabilities", service="service:agent-capability-resolver", version="1.0.0"
    ),
    ServiceRequiredV2(
        alias="skill_mcp", service="service:agent.skill-mcp-manager", version="1.0.0"
    ),
    ServiceRequiredV2(
        alias="managed_mcp", service="service:application.mcp-services", version="1.0.0"
    ),
    ServiceRequiredV2(
        alias="artifacts",
        service="service:application.artifact-lifecycle-services",
        version="1.0.0",
    ),
    ServiceRequiredV2(
        alias="conversation_access",
        service="service:application.conversation-access",
        version="1.0.0",
    ),
    ServiceRequiredV2(alias="commands", service="service:agent-command-catalog", version="1.0.0"),
)

# react_agent_prompt_mixin builds workspace context only for is_workspace_conversation.
AGENT_WORKSPACE_REQUIRED_SERVICES_V2: tuple[ServiceRequiredV2, ...] = (
    *AGENT_TURN_REQUIRED_SERVICES_V2,
    ServiceRequiredV2(
        alias="workspace_prompt", service="service:agent.workspace-prompt-context", version="1.0.0"
    ),
)
