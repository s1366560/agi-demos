"""Shared fixtures for V2 repository tests."""

import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
async def v2_db_session(db_session: AsyncSession) -> AsyncSession:
    """Provide db_session fixture for V2 repository tests."""
    return db_session


def make_agent_execution(
    execution_id: str = "exec-1",
    conversation_id: str = "conv-1",
    message_id: str = "msg-1",
    status: str = "pending",
    thought: str | None = None,
    action: str | None = None,
    observation: str | None = None,
    tool_name: str | None = None,
    tool_input: dict | None = None,
    tool_output: str | None = None,
    metadata: dict | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> dict:
    """Factory for creating agent execution domain objects."""
    from src.domain.model.agent import AgentExecution, ExecutionStatus

    return AgentExecution(
        id=execution_id,
        conversation_id=conversation_id,
        message_id=message_id,
        status=ExecutionStatus(status),
        thought=thought,
        action=action,
        observation=observation,
        tool_name=tool_name,
        tool_input=tool_input or {},
        tool_output=tool_output,
        metadata=metadata or {},
        started_at=started_at or datetime.now(timezone.utc),
        completed_at=completed_at,
    )


def make_attachment(
    attachment_id: str = "att-1",
    conversation_id: str = "conv-1",
    project_id: str = "proj-1",
    tenant_id: str = "tenant-1",
    filename: str = "test.txt",
    mime_type: str = "text/plain",
    size_bytes: int = 100,
    object_key: str = "key/test.txt",
    purpose: str = "assistant",
    status: str = "pending",
) -> dict:
    """Factory for creating attachment domain objects."""
    from src.domain.model.agent.attachment import (
        Attachment,
        AttachmentMetadata,
        AttachmentPurpose,
        AttachmentStatus,
    )

    return Attachment(
        id=attachment_id,
        conversation_id=conversation_id,
        project_id=project_id,
        tenant_id=tenant_id,
        filename=filename,
        mime_type=mime_type,
        size_bytes=size_bytes,
        object_key=object_key,
        purpose=AttachmentPurpose(purpose),
        status=AttachmentStatus(status),
        upload_id=None,
        total_parts=1,
        uploaded_parts=0,
        sandbox_path=None,
        metadata=AttachmentMetadata.empty(),
        created_at=datetime.now(timezone.utc),
        expires_at=None,
        error_message=None,
    )


def make_execution_checkpoint(
    checkpoint_id: str = "ckpt-1",
    conversation_id: str = "conv-1",
    message_id: str | None = None,
    checkpoint_type: str = "llm_complete",
    execution_state: dict | None = None,
    step_number: int | None = None,
) -> dict:
    """Factory for creating execution checkpoint domain objects."""
    from src.domain.model.agent import ExecutionCheckpoint

    return ExecutionCheckpoint(
        id=checkpoint_id,
        conversation_id=conversation_id,
        message_id=message_id,
        checkpoint_type=checkpoint_type,
        execution_state=execution_state or {},
        step_number=step_number,
        created_at=datetime.now(timezone.utc),
    )


def make_hitl_request(
    request_id: str = "hitl-1",
    request_type: str = "clarification",
    conversation_id: str = "conv-1",
    message_id: str | None = None,
    tenant_id: str = "tenant-1",
    project_id: str = "proj-1",
    user_id: str | None = None,
    question: str = "Test question?",
    status: str = "pending",
) -> dict:
    """Factory for creating HITL request domain objects."""
    from datetime import timedelta
    from src.domain.model.agent.hitl_request import (
        HITLRequest,
        HITLRequestStatus,
        HITLRequestType,
    )

    return HITLRequest(
        id=request_id,
        request_type=HITLRequestType(request_type),
        conversation_id=conversation_id,
        message_id=message_id,
        tenant_id=tenant_id,
        project_id=project_id,
        user_id=user_id,
        question=question,
        options=None,
        context=None,
        metadata=None,
        status=HITLRequestStatus(status),
        response=None,
        response_metadata=None,
        created_at=datetime.now(timezone.utc),
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        answered_at=None,
    )


def make_memory(
    memory_id: str = "mem-1",
    project_id: str = "proj-1",
    title: str = "Test Memory",
    content: str = "Test content",
    author_id: str = "user-1",
    content_type: str = "text",
) -> dict:
    """Factory for creating memory domain objects."""
    from src.domain.model.memory.memory import Memory

    return Memory(
        id=memory_id,
        project_id=project_id,
        title=title,
        content=content,
        author_id=author_id,
        content_type=content_type,
        tags=[],
        entities=[],
        relationships=[],
        version=1,
        collaborators=[],
        is_public=False,
        status="enabled",
        processing_status="pending",
        metadata={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def make_message_execution_status(
    status_id: str = "status-1",
    conversation_id: str = "conv-1",
    message_id: str = "msg-1",
    tenant_id: str = "tenant-1",
    project_id: str = "proj-1",
    status: str = "pending",
) -> dict:
    """Factory for creating message execution status domain objects."""
    from src.domain.model.agent.execution_status import (
        AgentExecution,
        AgentExecutionStatus,
    )

    return AgentExecution(
        id=status_id,
        conversation_id=conversation_id,
        message_id=message_id,
        status=AgentExecutionStatus(status),
        tenant_id=tenant_id,
        project_id=project_id,
        last_event_sequence=0,
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        error_message=None,
    )


def make_plan_execution(
    execution_id: str = "plan-exec-1",
    conversation_id: str = "conv-1",
    plan_id: str | None = None,
    status: str = "pending",
) -> dict:
    """Factory for creating plan execution domain objects."""
    from src.domain.model.agent.plan_execution import (
        ExecutionMode,
        ExecutionStatus,
        ExecutionStep,
        PlanExecution,
    )

    return PlanExecution(
        id=execution_id,
        conversation_id=conversation_id,
        plan_id=plan_id,
        steps=[],
        current_step_index=0,
        completed_step_indices=[],
        failed_step_indices=[],
        status=ExecutionStatus(status),
        execution_mode=ExecutionMode.SEQUENTIAL,
        max_parallel_steps=3,
        reflection_enabled=True,
        max_reflection_cycles=3,
        current_reflection_cycle=0,
        workflow_pattern_id=None,
        metadata={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        started_at=None,
        completed_at=None,
    )


def make_plan(
    plan_id: str = "plan-1",
    conversation_id: str = "conv-1",
    title: str = "Test Plan",
    content: str = "# Test Plan\n\nTest content",
    status: str = "draft",
) -> dict:
    """Factory for creating plan domain objects."""
    from src.domain.model.agent.plan import Plan, PlanDocumentStatus

    return Plan(
        id=plan_id,
        conversation_id=conversation_id,
        title=title,
        content=content,
        status=PlanDocumentStatus(status),
        version=1,
        metadata={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def make_plan_snapshot(
    snapshot_id: str = "snap-1",
    execution_id: str = "plan-exec-1",
    name: str = "Initial Snapshot",
) -> dict:
    """Factory for creating plan snapshot domain objects."""
    from src.domain.model.agent.plan_snapshot import PlanSnapshot, StepState

    return PlanSnapshot(
        id=snapshot_id,
        plan_id=execution_id,
        name=name,
        step_states={},
        description=None,
        auto_created=True,
        snapshot_type="auto",
        created_at=datetime.now(timezone.utc),
    )


def make_project_sandbox(
    association_id: str = "ps-1",
    project_id: str = "proj-1",
    tenant_id: str = "tenant-1",
    sandbox_id: str = "sandbox-1",
    status: str = "pending",
) -> dict:
    """Factory for creating project sandbox domain objects."""
    from src.domain.model.sandbox.project_sandbox import (
        ProjectSandbox,
        ProjectSandboxStatus,
    )

    return ProjectSandbox(
        id=association_id,
        project_id=project_id,
        tenant_id=tenant_id,
        sandbox_id=sandbox_id,
        status=ProjectSandboxStatus(status),
        created_at=datetime.now(timezone.utc),
        started_at=None,
        last_accessed_at=datetime.now(timezone.utc),
        health_checked_at=None,
        error_message=None,
        metadata={},
    )


def make_subagent(
    subagent_id: str = "sub-1",
    tenant_id: str = "tenant-1",
    project_id: str | None = None,
    name: str = "test_subagent",
    display_name: str = "Test SubAgent",
) -> dict:
    """Factory for creating subagent domain objects."""
    from src.domain.model.agent.subagent import (
        AgentModel,
        AgentTrigger,
        SubAgent,
    )

    return SubAgent(
        id=subagent_id,
        tenant_id=tenant_id,
        project_id=project_id,
        name=name,
        display_name=display_name,
        system_prompt="You are a test subagent",
        trigger=AgentTrigger(
            description="Test trigger",
            examples=[],
            keywords=[],
        ),
        model=AgentModel.INHERIT,
        color="blue",
        allowed_tools=["*"],
        allowed_skills=[],
        allowed_mcp_servers=[],
        max_tokens=4096,
        temperature=0.7,
        max_iterations=10,
        enabled=True,
        total_invocations=0,
        avg_execution_time_ms=0.0,
        success_rate=1.0,
        metadata={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def make_task_log(
    task_id: str = "task-1",
    group_id: str = "group-1",
    task_type: str = "test_task",
    status: str = "pending",
) -> dict:
    """Factory for creating task log domain objects."""
    from src.domain.model.task.task_log import TaskLog

    return TaskLog(
        id=task_id,
        group_id=group_id,
        task_type=task_type,
        status=status,
        payload={},
        entity_id=None,
        entity_type=None,
        parent_task_id=None,
        worker_id=None,
        retry_count=0,
        error_message=None,
        created_at=datetime.now(timezone.utc),
        started_at=None,
        completed_at=None,
        stopped_at=None,
        progress=0,
        result=None,
        message=None,
    )


def make_tenant_agent_config(
    config_id: str = "config-1",
    tenant_id: str = "tenant-1",
) -> dict:
    """Factory for creating tenant agent config domain objects."""
    from src.domain.model.agent.tenant_agent_config import (
        ConfigType,
        TenantAgentConfig,
    )

    return TenantAgentConfig(
        id=config_id,
        tenant_id=tenant_id,
        config_type=ConfigType.CUSTOM,
        llm_model="default",
        llm_temperature=0.7,
        pattern_learning_enabled=True,
        multi_level_thinking_enabled=True,
        max_work_plan_steps=10,
        tool_timeout_seconds=30,
        enabled_tools=[],
        disabled_tools=[],
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def make_tenant_skill_config(
    config_id: str = "ts-config-1",
    tenant_id: str = "tenant-1",
    system_skill_name: str = "test_skill",
    action: str = "disable",
) -> dict:
    """Factory for creating tenant skill config domain objects."""
    from src.domain.model.agent.tenant_skill_config import (
        TenantSkillAction,
        TenantSkillConfig,
    )

    return TenantSkillConfig(
        id=config_id,
        tenant_id=tenant_id,
        system_skill_name=system_skill_name,
        action=TenantSkillAction(action),
        override_skill_id=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def make_tool_composition(
    composition_id: str = "tc-1",
    name: str = "test_composition",
    tools: list | None = None,
) -> dict:
    """Factory for creating tool composition domain objects."""
    from src.domain.model.agent import ToolComposition

    return ToolComposition(
        id=composition_id,
        name=name,
        description="Test composition",
        tools=tools or ["search", "calculate"],
        execution_template={},
        success_count=0,
        failure_count=0,
        usage_count=0,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def make_tool_execution_record(
    record_id: str = "ter-1",
    conversation_id: str = "conv-1",
    message_id: str = "msg-1",
    call_id: str = "call-1",
    tool_name: str = "search",
    status: str = "running",
) -> dict:
    """Factory for creating tool execution record domain objects."""
    from src.domain.model.agent import ToolExecutionRecord

    return ToolExecutionRecord(
        id=record_id,
        conversation_id=conversation_id,
        message_id=message_id,
        call_id=call_id,
        tool_name=tool_name,
        tool_input={},
        tool_output=None,
        status=status,
        error=None,
        step_number=None,
        sequence_number=1,
        started_at=datetime.now(timezone.utc),
        completed_at=None,
        duration_ms=None,
    )


def make_tool_environment_variable(
    env_var_id: str = "env-1",
    tenant_id: str = "tenant-1",
    project_id: str | None = None,
    tool_name: str = "test_tool",
    variable_name: str = "TEST_VAR",
    encrypted_value: str = "encrypted_value",
) -> dict:
    """Factory for creating tool environment variable domain objects."""
    from src.domain.model.agent.tool_environment_variable import (
        EnvVarScope,
        ToolEnvironmentVariable,
    )

    return ToolEnvironmentVariable(
        id=env_var_id,
        tenant_id=tenant_id,
        project_id=project_id,
        tool_name=tool_name,
        variable_name=variable_name,
        encrypted_value=encrypted_value,
        description="Test variable",
        is_required=True,
        is_secret=True,
        scope=EnvVarScope.TENANT,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


def make_work_plan(
    plan_id: str = "wp-1",
    conversation_id: str = "conv-1",
    status: str = "planning",
) -> dict:
    """Factory for creating work plan domain objects."""
    from src.domain.model.agent import PlanStatus, PlanStep, WorkPlan

    return WorkPlan(
        id=plan_id,
        conversation_id=conversation_id,
        status=PlanStatus(status),
        steps=[],
        current_step_index=0,
        workflow_pattern_id=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
