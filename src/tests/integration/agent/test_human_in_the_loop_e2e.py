"""
End-to-End Tests for Human-in-the-Loop (HITL) Tools.

Tests the complete flow from agent tool call → SSE event → user response → agent continuation
for all three HITL tools:
1. ask_clarification - Clarification questions during planning
2. request_decision - Decision requests during execution
3. request_env_var - Environment variable requests for tool configuration

These tests verify:
- Manager creates pending requests correctly
- SSE events are emitted with correct data structure
- User responses resolve the Future
- Agent receives the response and continues

TDD: RED-GREEN-REFACTOR cycle.
"""

import asyncio
from typing import Any, Dict, List

import pytest

from src.domain.events.agent_events import (
    AgentClarificationAnsweredEvent,
    AgentClarificationAskedEvent,
    AgentDecisionAnsweredEvent,
    AgentDecisionAskedEvent,
    AgentEnvVarProvidedEvent,
    AgentEnvVarRequestedEvent,
)
from src.infrastructure.agent.tools.clarification import (
    ClarificationManager,
    ClarificationOption,
    ClarificationRequest,
    ClarificationTool,
    ClarificationType,
    get_clarification_manager,
)
from src.infrastructure.agent.tools.decision import (
    DecisionManager,
    DecisionOption,
    DecisionRequest,
    DecisionTool,
    DecisionType,
    get_decision_manager,
)
from src.infrastructure.agent.tools.env_var_tools import (
    EnvVarField,
    EnvVarInputType,
    EnvVarManager,
    EnvVarRequest,
    get_env_var_manager,
)

# =============================================================================
# CLARIFICATION TOOL E2E TESTS
# =============================================================================


@pytest.mark.integration
class TestClarificationToolE2E:
    """End-to-end tests for ClarificationTool."""

    @pytest.fixture
    def clarification_manager(self) -> ClarificationManager:
        """Create a fresh clarification manager for each test."""
        return ClarificationManager()

    @pytest.fixture
    def clarification_tool(self, clarification_manager: ClarificationManager) -> ClarificationTool:
        """Create clarification tool with test manager."""
        return ClarificationTool(manager=clarification_manager)

    @pytest.mark.asyncio
    async def test_clarification_request_creation_and_event_data(
        self,
        clarification_manager: ClarificationManager,
    ) -> None:
        """Test that clarification request is created with correct event data structure."""
        # Prepare options
        options = [
            ClarificationOption(
                id="opt1", label="Option 1", description="First option", recommended=True
            ),
            ClarificationOption(id="opt2", label="Option 2", description="Second option"),
        ]

        # Create request in background (it will wait for response)
        request_task = asyncio.create_task(
            clarification_manager.create_request(
                question="Which approach should I use?",
                clarification_type=ClarificationType.APPROACH,
                options=options,
                allow_custom=True,
                context={"task": "test task"},
                timeout=5.0,
            )
        )

        # Give time for request to be registered
        await asyncio.sleep(0.1)

        # Verify request was created
        assert len(clarification_manager._pending_requests) == 1
        request_id = list(clarification_manager._pending_requests.keys())[0]
        request = clarification_manager._pending_requests[request_id]

        # Verify request data structure (matches SSE event format)
        request_dict = request.to_dict()
        assert request_dict["question"] == "Which approach should I use?"
        assert request_dict["clarification_type"] == "approach"
        assert len(request_dict["options"]) == 2
        assert request_dict["options"][0]["id"] == "opt1"
        assert request_dict["options"][0]["label"] == "Option 1"
        assert request_dict["options"][0]["recommended"] is True
        assert request_dict["allow_custom"] is True
        assert request_dict["context"]["task"] == "test task"

        # Respond to unblock the task
        await clarification_manager.respond(request_id, "opt1")
        result = await request_task
        assert result == "opt1"

    @pytest.mark.asyncio
    async def test_clarification_user_response_resolves_future(
        self,
        clarification_manager: ClarificationManager,
    ) -> None:
        """Test that user response correctly resolves the pending Future."""
        options = [
            ClarificationOption(id="yes", label="Yes"),
            ClarificationOption(id="no", label="No"),
        ]

        # Simulate: Agent creates request, user responds via API
        async def simulate_user_response(request_id: str, answer: str, delay: float = 0.2):
            await asyncio.sleep(delay)
            await clarification_manager.respond(request_id, answer)

        # Start the clarification request
        request_task = asyncio.create_task(
            clarification_manager.create_request(
                question="Should I proceed?",
                clarification_type=ClarificationType.SCOPE,  # Use SCOPE instead of CONFIRMATION
                options=options,
                timeout=5.0,
            )
        )

        # Wait for request to be registered
        await asyncio.sleep(0.1)
        request_id = list(clarification_manager._pending_requests.keys())[0]

        # Simulate user responding
        user_task = asyncio.create_task(simulate_user_response(request_id, "yes"))

        # Both should complete
        answer = await request_task
        await user_task

        assert answer == "yes"
        # Request should be cleaned up
        assert len(clarification_manager._pending_requests) == 0

    @pytest.mark.asyncio
    async def test_clarification_custom_input_response(
        self,
        clarification_manager: ClarificationManager,
    ) -> None:
        """Test that custom text input is accepted when allow_custom=True."""
        options = [
            ClarificationOption(id="opt1", label="Predefined Option"),
        ]

        request_task = asyncio.create_task(
            clarification_manager.create_request(
                question="What should I do?",
                clarification_type=ClarificationType.CUSTOM,
                options=options,
                allow_custom=True,
                timeout=5.0,
            )
        )

        await asyncio.sleep(0.1)
        request_id = list(clarification_manager._pending_requests.keys())[0]

        # User provides custom text instead of selecting option
        custom_answer = "Please use a different approach entirely"
        await clarification_manager.respond(request_id, custom_answer)

        answer = await request_task
        assert answer == custom_answer

    @pytest.mark.asyncio
    async def test_clarification_timeout_raises_error(
        self,
        clarification_manager: ClarificationManager,
    ) -> None:
        """Test that request times out when user doesn't respond."""
        options = [
            ClarificationOption(id="opt1", label="Option 1"),
        ]

        with pytest.raises(asyncio.TimeoutError):
            await clarification_manager.create_request(
                question="Quick question?",
                clarification_type=ClarificationType.SCOPE,
                options=options,
                timeout=0.1,  # Very short timeout
            )

    @pytest.mark.asyncio
    async def test_clarification_tool_execute_emits_events(
        self,
        clarification_tool: ClarificationTool,
        clarification_manager: ClarificationManager,
    ) -> None:
        """Test that ClarificationTool.execute works end-to-end."""

        # Simulate user response after a delay
        async def auto_respond():
            await asyncio.sleep(0.1)
            if clarification_manager._pending_requests:
                request_id = list(clarification_manager._pending_requests.keys())[0]
                await clarification_manager.respond(request_id, "option_a")

        respond_task = asyncio.create_task(auto_respond())

        # Execute the tool
        result = await clarification_tool.execute(
            question="Which option should I choose?",
            clarification_type="approach",
            options=[
                {"id": "option_a", "label": "Option A", "recommended": True},
                {"id": "option_b", "label": "Option B"},
            ],
            timeout=5.0,
        )

        await respond_task
        assert result == "option_a"


# =============================================================================
# DECISION TOOL E2E TESTS
# =============================================================================


@pytest.mark.integration
class TestDecisionToolE2E:
    """End-to-end tests for DecisionTool."""

    @pytest.fixture
    def decision_manager(self) -> DecisionManager:
        """Create a fresh decision manager for each test."""
        return DecisionManager()

    @pytest.fixture
    def decision_tool(self, decision_manager: DecisionManager) -> DecisionTool:
        """Create decision tool with test manager."""
        return DecisionTool(manager=decision_manager)

    @pytest.mark.asyncio
    async def test_decision_request_creation_with_options(
        self,
        decision_manager: DecisionManager,
    ) -> None:
        """Test that decision request is created with all option metadata."""
        options = [
            DecisionOption(
                id="fast",
                label="Fast method",
                description="Quick but risky",
                recommended=False,
                estimated_time="5 minutes",
                estimated_cost="Low",
                risks=["May fail on edge cases"],
            ),
            DecisionOption(
                id="safe",
                label="Safe method",
                description="Slower but reliable",
                recommended=True,
                estimated_time="30 minutes",
                estimated_cost="Medium",
            ),
        ]

        request_task = asyncio.create_task(
            decision_manager.create_request(
                question="Which method should I use?",
                decision_type=DecisionType.METHOD,
                options=options,
                allow_custom=False,
                context={"operation": "database migration"},
                timeout=5.0,
            )
        )

        await asyncio.sleep(0.1)
        request_id = list(decision_manager._pending_requests.keys())[0]
        request = decision_manager._pending_requests[request_id]

        # Verify request data structure
        request_dict = request.to_dict()
        assert request_dict["question"] == "Which method should I use?"
        assert request_dict["decision_type"] == "method"
        assert request_dict["allow_custom"] is False
        assert len(request_dict["options"]) == 2

        # Verify first option has all metadata
        fast_option = request_dict["options"][0]
        assert fast_option["id"] == "fast"
        assert fast_option["estimated_time"] == "5 minutes"
        assert fast_option["risks"] == ["May fail on edge cases"]

        # Cleanup
        await decision_manager.respond(request_id, "safe")
        await request_task

    @pytest.mark.asyncio
    async def test_decision_user_choice_resolves_correctly(
        self,
        decision_manager: DecisionManager,
    ) -> None:
        """Test that user decision resolves the Future with correct choice."""
        options = [
            DecisionOption(id="proceed", label="Proceed"),
            DecisionOption(id="cancel", label="Cancel"),
            DecisionOption(id="modify", label="Modify and proceed"),
        ]

        request_task = asyncio.create_task(
            decision_manager.create_request(
                question="The operation will delete 100 files. Proceed?",
                decision_type=DecisionType.CONFIRMATION,
                options=options,
                timeout=5.0,
            )
        )

        await asyncio.sleep(0.1)
        request_id = list(decision_manager._pending_requests.keys())[0]

        # User chooses to modify
        await decision_manager.respond(request_id, "modify")
        decision = await request_task

        assert decision == "modify"
        assert len(decision_manager._pending_requests) == 0

    @pytest.mark.asyncio
    async def test_decision_timeout_uses_default_option(
        self,
        decision_manager: DecisionManager,
    ) -> None:
        """Test that timeout uses default_option when provided."""
        options = [
            DecisionOption(id="yes", label="Yes"),
            DecisionOption(id="no", label="No"),
        ]

        decision = await decision_manager.create_request(
            question="Continue?",
            decision_type=DecisionType.CONFIRMATION,
            options=options,
            default_option="no",  # Default to "no" on timeout
            timeout=0.1,
        )

        # Should return default instead of raising TimeoutError
        assert decision == "no"

    @pytest.mark.asyncio
    async def test_decision_timeout_raises_without_default(
        self,
        decision_manager: DecisionManager,
    ) -> None:
        """Test that timeout raises error when no default_option."""
        options = [
            DecisionOption(id="yes", label="Yes"),
        ]

        with pytest.raises(asyncio.TimeoutError):
            await decision_manager.create_request(
                question="Urgent decision needed",
                decision_type=DecisionType.RISK,
                options=options,
                default_option=None,  # No default
                timeout=0.1,
            )

    @pytest.mark.asyncio
    async def test_decision_branch_type_with_multiple_options(
        self,
        decision_manager: DecisionManager,
    ) -> None:
        """Test branch decision with multiple execution paths."""
        options = [
            DecisionOption(id="path_a", label="Path A - Full reindex"),
            DecisionOption(id="path_b", label="Path B - Incremental update"),
            DecisionOption(id="path_c", label="Path C - Skip and continue"),
        ]

        async def user_responds_after_delay():
            await asyncio.sleep(0.1)
            if decision_manager._pending_requests:
                request_id = list(decision_manager._pending_requests.keys())[0]
                await decision_manager.respond(request_id, "path_b")

        respond_task = asyncio.create_task(user_responds_after_delay())

        decision = await decision_manager.create_request(
            question="How should I handle the outdated index?",
            decision_type=DecisionType.BRANCH,
            options=options,
            context={"index_age_days": 30},
            timeout=5.0,
        )

        await respond_task
        assert decision == "path_b"


# =============================================================================
# ENVIRONMENT VARIABLE TOOL E2E TESTS
# =============================================================================


@pytest.mark.integration
class TestEnvVarToolE2E:
    """End-to-end tests for environment variable tools."""

    @pytest.fixture
    def env_var_manager(self) -> EnvVarManager:
        """Create a fresh env var manager for each test."""
        return EnvVarManager()

    @pytest.mark.asyncio
    async def test_env_var_request_with_multiple_fields(
        self,
        env_var_manager: EnvVarManager,
    ) -> None:
        """Test env var request with multiple field types."""
        fields = [
            EnvVarField(
                variable_name="API_KEY",
                display_name="API Key",
                description="Your API key for authentication",
                input_type=EnvVarInputType.PASSWORD,
                is_required=True,
                is_secret=True,
            ),
            EnvVarField(
                variable_name="API_ENDPOINT",
                display_name="API Endpoint",
                description="The API endpoint URL",
                input_type=EnvVarInputType.TEXT,
                is_required=True,
                is_secret=False,
                default_value="https://api.example.com",
            ),
            EnvVarField(
                variable_name="REGION",
                display_name="Region",
                description="Select your region",
                input_type=EnvVarInputType.SELECT,
                is_required=False,
                is_secret=False,
                options=["us-east-1", "us-west-2", "eu-west-1"],
            ),
        ]

        request_task = asyncio.create_task(
            env_var_manager.create_request(
                tool_name="external_api",
                fields=fields,
                context={"purpose": "Connect to external service"},
                timeout=5.0,
            )
        )

        await asyncio.sleep(0.1)
        request_id = list(env_var_manager._pending_requests.keys())[0]
        request = env_var_manager._pending_requests[request_id]

        # Verify request data structure
        request_dict = request.to_dict()
        assert request_dict["tool_name"] == "external_api"
        assert len(request_dict["fields"]) == 3

        # Verify field types are correct
        api_key_field = request_dict["fields"][0]
        assert api_key_field["variable_name"] == "API_KEY"
        assert api_key_field["input_type"] == "password"
        assert api_key_field["is_secret"] is True

        region_field = request_dict["fields"][2]
        assert region_field["input_type"] == "select"
        assert region_field["options"] == ["us-east-1", "us-west-2", "eu-west-1"]

        # User provides values
        await env_var_manager.respond(
            request_id,
            {
                "API_KEY": "sk-secret-key",
                "API_ENDPOINT": "https://api.custom.com",
                "REGION": "us-west-2",
            },
        )

        values = await request_task
        assert values["API_KEY"] == "sk-secret-key"
        assert values["API_ENDPOINT"] == "https://api.custom.com"
        assert values["REGION"] == "us-west-2"

    @pytest.mark.asyncio
    async def test_env_var_partial_response_accepted(
        self,
        env_var_manager: EnvVarManager,
    ) -> None:
        """Test that partial responses (optional fields omitted) are accepted."""
        fields = [
            EnvVarField(
                variable_name="REQUIRED_VAR",
                display_name="Required Variable",
                is_required=True,
            ),
            EnvVarField(
                variable_name="OPTIONAL_VAR",
                display_name="Optional Variable",
                is_required=False,
            ),
        ]

        request_task = asyncio.create_task(
            env_var_manager.create_request(
                tool_name="test_tool",
                fields=fields,
                timeout=5.0,
            )
        )

        await asyncio.sleep(0.1)
        request_id = list(env_var_manager._pending_requests.keys())[0]

        # User only provides required field
        await env_var_manager.respond(
            request_id,
            {
                "REQUIRED_VAR": "required_value",
            },
        )

        values = await request_task
        assert values["REQUIRED_VAR"] == "required_value"
        assert "OPTIONAL_VAR" not in values

    @pytest.mark.asyncio
    async def test_env_var_timeout_raises_error(
        self,
        env_var_manager: EnvVarManager,
    ) -> None:
        """Test that request times out when user doesn't provide values."""
        fields = [
            EnvVarField(variable_name="API_KEY", display_name="API Key"),
        ]

        with pytest.raises(asyncio.TimeoutError):
            await env_var_manager.create_request(
                tool_name="timeout_test",
                fields=fields,
                timeout=0.1,
            )

    @pytest.mark.asyncio
    async def test_env_var_request_cleanup_after_response(
        self,
        env_var_manager: EnvVarManager,
    ) -> None:
        """Test that request is cleaned up after response."""
        fields = [
            EnvVarField(variable_name="VAR1", display_name="Variable 1"),
        ]

        request_task = asyncio.create_task(
            env_var_manager.create_request(
                tool_name="cleanup_test",
                fields=fields,
                timeout=5.0,
            )
        )

        await asyncio.sleep(0.1)
        assert len(env_var_manager._pending_requests) == 1

        request_id = list(env_var_manager._pending_requests.keys())[0]
        await env_var_manager.respond(request_id, {"VAR1": "value1"})
        await request_task

        # Should be cleaned up
        assert len(env_var_manager._pending_requests) == 0


# =============================================================================
# PROCESSOR INTEGRATION TESTS
# =============================================================================


@pytest.mark.integration
class TestProcessorHITLIntegration:
    """Test processor handling of HITL tools with SSE events.

    These tests verify that the processor correctly:
    1. Creates pending requests in the manager
    2. Emits SSE events before blocking
    3. Resolves when user responds
    4. Emits completion events
    """

    @pytest.mark.asyncio
    async def test_clarification_flow_emits_correct_events(self) -> None:
        """Test that clarification flow emits events in correct order."""
        # Clear any existing state
        clarification_manager = get_clarification_manager()
        clarification_manager._pending_requests.clear()

        collected_events: List[Dict[str, Any]] = []

        # Simulate the processor's _handle_clarification_tool logic
        async def simulate_clarification_tool_call():
            """Simulate what processor does when handling clarification tool."""
            import uuid

            from src.infrastructure.agent.tools.clarification import (
                ClarificationOption,
                ClarificationType,
            )

            request_id = f"clarif_{uuid.uuid4().hex[:8]}"
            question = "Which approach?"
            clarification_type = "approach"
            options = [
                {"id": "a", "label": "Option A", "recommended": True},
                {"id": "b", "label": "Option B"},
            ]

            # Create request object (what processor does)
            option_objects = [
                ClarificationOption(
                    id=opt["id"],
                    label=opt["label"],
                    recommended=opt.get("recommended", False),
                )
                for opt in options
            ]

            request = ClarificationRequest(
                request_id=request_id,
                question=question,
                clarification_type=ClarificationType(clarification_type),
                options=option_objects,
                allow_custom=True,
                context={},
            )

            # Register with manager
            async with clarification_manager._lock:
                clarification_manager._pending_requests[request_id] = request

            # Emit clarification_asked event (before blocking)
            event = AgentClarificationAskedEvent(
                request_id=request_id,
                question=question,
                clarification_type=clarification_type,
                options=options,
                allow_custom=True,
                context={},
            )
            collected_events.append({"type": "clarification_asked", "data": event})

            # Wait for response (this is where processor blocks)
            try:
                answer = await asyncio.wait_for(request.future, timeout=5.0)

                # Emit answered event
                answered_event = AgentClarificationAnsweredEvent(
                    request_id=request_id,
                    answer=answer,
                )
                collected_events.append({"type": "clarification_answered", "data": answered_event})

                return answer
            finally:
                async with clarification_manager._lock:
                    clarification_manager._pending_requests.pop(request_id, None)

        # Run simulation in background
        simulation_task = asyncio.create_task(simulate_clarification_tool_call())

        # Wait for request to be registered and event emitted
        await asyncio.sleep(0.1)

        # Verify event was emitted
        assert len(collected_events) == 1
        assert collected_events[0]["type"] == "clarification_asked"
        event = collected_events[0]["data"]
        assert event.question == "Which approach?"
        assert event.clarification_type == "approach"

        # User responds
        await clarification_manager.respond(event.request_id, "a")

        # Wait for completion
        result = await simulation_task

        # Verify full flow
        assert result == "a"
        assert len(collected_events) == 2
        assert collected_events[1]["type"] == "clarification_answered"
        assert collected_events[1]["data"].answer == "a"

    @pytest.mark.asyncio
    async def test_decision_flow_emits_correct_events(self) -> None:
        """Test that decision flow emits events in correct order."""
        decision_manager = get_decision_manager()
        decision_manager._pending_requests.clear()

        collected_events: List[Dict[str, Any]] = []

        async def simulate_decision_tool_call():
            """Simulate what processor does when handling decision tool."""
            import uuid

            from src.infrastructure.agent.tools.decision import (
                DecisionOption,
                DecisionType,
            )

            request_id = f"decision_{uuid.uuid4().hex[:8]}"
            question = "Should I proceed?"
            decision_type = "confirmation"
            options = [
                {"id": "yes", "label": "Yes", "recommended": True},
                {"id": "no", "label": "No"},
            ]

            option_objects = [
                DecisionOption(
                    id=opt["id"],
                    label=opt["label"],
                    recommended=opt.get("recommended", False),
                )
                for opt in options
            ]

            request = DecisionRequest(
                request_id=request_id,
                question=question,
                decision_type=DecisionType(decision_type),
                options=option_objects,
                allow_custom=False,
                context={},
            )

            async with decision_manager._lock:
                decision_manager._pending_requests[request_id] = request

            # Emit decision_asked event
            event = AgentDecisionAskedEvent(
                request_id=request_id,
                question=question,
                decision_type=decision_type,
                options=options,
                allow_custom=False,
                default_option=None,
                context={},
            )
            collected_events.append({"type": "decision_asked", "data": event})

            # Wait for response
            try:
                decision = await asyncio.wait_for(request.future, timeout=5.0)

                answered_event = AgentDecisionAnsweredEvent(
                    request_id=request_id,
                    decision=decision,
                )
                collected_events.append({"type": "decision_answered", "data": answered_event})

                return decision
            finally:
                async with decision_manager._lock:
                    decision_manager._pending_requests.pop(request_id, None)

        simulation_task = asyncio.create_task(simulate_decision_tool_call())

        await asyncio.sleep(0.1)

        assert len(collected_events) == 1
        assert collected_events[0]["type"] == "decision_asked"
        event = collected_events[0]["data"]
        assert event.question == "Should I proceed?"
        assert event.decision_type == "confirmation"

        await decision_manager.respond(event.request_id, "yes")

        result = await simulation_task

        assert result == "yes"
        assert len(collected_events) == 2
        assert collected_events[1]["type"] == "decision_answered"
        assert collected_events[1]["data"].decision == "yes"

    @pytest.mark.asyncio
    async def test_env_var_flow_emits_correct_events(self) -> None:
        """Test that env var flow emits events in correct order."""
        env_var_manager = get_env_var_manager()
        env_var_manager._pending_requests.clear()

        collected_events: List[Dict[str, Any]] = []

        async def simulate_env_var_tool_call():
            """Simulate what processor does when handling env var tool."""
            import uuid

            request_id = str(uuid.uuid4())
            tool_name = "external_api"
            fields = [
                {
                    "variable_name": "API_KEY",
                    "display_name": "API Key",
                    "is_required": True,
                    "is_secret": True,
                    "input_type": "password",
                }
            ]

            field_objects = [
                EnvVarField(
                    variable_name=f["variable_name"],
                    display_name=f["display_name"],
                    is_required=f.get("is_required", True),
                    is_secret=f.get("is_secret", True),
                    input_type=EnvVarInputType(f.get("input_type", "text")),
                )
                for f in fields
            ]

            request = EnvVarRequest(
                request_id=request_id,
                tool_name=tool_name,
                fields=field_objects,
                context={},
            )

            async with env_var_manager._lock:
                env_var_manager._pending_requests[request_id] = request

            # Emit env_var_requested event
            event = AgentEnvVarRequestedEvent(
                request_id=request_id,
                tool_name=tool_name,
                fields=[f.to_dict() for f in field_objects],
                context={},
            )
            collected_events.append({"type": "env_var_requested", "data": event})

            # Wait for response
            try:
                values = await asyncio.wait_for(request.future, timeout=5.0)

                provided_event = AgentEnvVarProvidedEvent(
                    request_id=request_id,
                    tool_name=tool_name,
                    saved_variables=list(values.keys()),
                )
                collected_events.append({"type": "env_var_provided", "data": provided_event})

                return values
            finally:
                async with env_var_manager._lock:
                    env_var_manager._pending_requests.pop(request_id, None)

        simulation_task = asyncio.create_task(simulate_env_var_tool_call())

        await asyncio.sleep(0.1)

        assert len(collected_events) == 1
        assert collected_events[0]["type"] == "env_var_requested"
        event = collected_events[0]["data"]
        assert event.tool_name == "external_api"
        assert len(event.fields) == 1

        await env_var_manager.respond(event.request_id, {"API_KEY": "test-key"})

        result = await simulation_task

        assert result == {"API_KEY": "test-key"}
        assert len(collected_events) == 2
        assert collected_events[1]["type"] == "env_var_provided"
        assert collected_events[1]["data"].saved_variables == ["API_KEY"]


# =============================================================================
# CONCURRENT REQUESTS TESTS
# =============================================================================


@pytest.mark.integration
class TestConcurrentHITLRequests:
    """Test handling of multiple concurrent HITL requests."""

    @pytest.mark.asyncio
    async def test_multiple_clarification_requests_isolated(self) -> None:
        """Test that multiple concurrent clarification requests are isolated."""
        manager = ClarificationManager()

        options = [ClarificationOption(id="opt1", label="Option 1")]

        # Start multiple requests
        task1 = asyncio.create_task(
            manager.create_request(
                question="Question 1",
                clarification_type=ClarificationType.SCOPE,
                options=options,
                timeout=5.0,
            )
        )

        task2 = asyncio.create_task(
            manager.create_request(
                question="Question 2",
                clarification_type=ClarificationType.APPROACH,
                options=options,
                timeout=5.0,
            )
        )

        await asyncio.sleep(0.1)

        # Should have 2 pending requests
        assert len(manager._pending_requests) == 2

        # Get request IDs
        request_ids = list(manager._pending_requests.keys())

        # Respond to each with different answers
        await manager.respond(request_ids[0], "answer_1")
        await manager.respond(request_ids[1], "answer_2")

        result1 = await task1
        result2 = await task2

        # Results should be independent
        assert result1 == "answer_1"
        assert result2 == "answer_2"

    @pytest.mark.asyncio
    async def test_respond_to_nonexistent_request_returns_false(self) -> None:
        """Test that responding to non-existent request returns False."""
        manager = ClarificationManager()

        result = await manager.respond("nonexistent-id", "some answer")
        assert result is False

    @pytest.mark.asyncio
    async def test_respond_to_already_answered_request(self) -> None:
        """Test that responding twice to same request is handled gracefully."""
        manager = ClarificationManager()

        options = [ClarificationOption(id="opt1", label="Option 1")]

        task = asyncio.create_task(
            manager.create_request(
                question="Test question",
                clarification_type=ClarificationType.CUSTOM,
                options=options,
                timeout=5.0,
            )
        )

        await asyncio.sleep(0.1)
        request_id = list(manager._pending_requests.keys())[0]

        # First response
        result1 = await manager.respond(request_id, "first_answer")
        assert result1 is True

        # Wait for task to complete and cleanup
        await task

        # Second response should fail (request already cleaned up)
        result2 = await manager.respond(request_id, "second_answer")
        assert result2 is False
