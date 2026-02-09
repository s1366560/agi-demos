"""
Integration tests for the unified HITL (Human-in-the-Loop) system.

These tests verify:
1. Type system consistency
2. Handler strategy patterns
3. Service port implementations
4. API endpoint responses
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.integration
class TestHITLTypeSystemIntegration:
    """Integration tests for the unified HITL type system."""

    def test_all_hitl_types_can_be_imported(self):
        """Test all HITL types can be imported from hitl_types module."""
        from src.domain.model.agent.hitl_types import (
            HITLType,
            HITLStatus,
            ClarificationType,
            DecisionType,
            PermissionAction,
            RiskLevel,
            ClarificationOption,
            DecisionOption,
            EnvVarField,
            ClarificationRequestData,
            DecisionRequestData,
            EnvVarRequestData,
            PermissionRequestData,
            ClarificationResponse,
            DecisionResponse,
            EnvVarResponse,
            PermissionResponse,
            HITLRequest,
            HITLResponse,
            HITLSignalPayload,
            HITL_RESPONSE_SIGNAL,
        )

        # Verify enums have expected values
        assert HITLType.CLARIFICATION.value == "clarification"
        assert HITLType.DECISION.value == "decision"
        assert HITLType.ENV_VAR.value == "env_var"
        assert HITLType.PERMISSION.value == "permission"

        assert HITLStatus.PENDING.value == "pending"
        assert HITLStatus.ANSWERED.value == "answered"
        assert HITLStatus.COMPLETED.value == "completed"
        assert HITLStatus.TIMEOUT.value == "timeout"
        assert HITLStatus.CANCELLED.value == "cancelled"

        # Verify signal name
        assert HITL_RESPONSE_SIGNAL == "hitl_response"

    def test_factory_functions_create_valid_requests(self):
        """Test factory functions create valid HITLRequest objects."""
        from src.domain.model.agent.hitl_types import (
            create_clarification_request,
            create_decision_request,
            create_env_var_request,
            create_permission_request,
            HITLType,
            HITLStatus,
            ClarificationOption,
            DecisionOption,
            EnvVarField,
            RiskLevel,
        )

        # Clarification request
        clar_req = create_clarification_request(
            request_id="clar_test123",
            conversation_id="conv_1",
            question="What color?",
            options=[
                ClarificationOption(id="red", label="Red"),
                ClarificationOption(id="blue", label="Blue"),
            ],
        )
        assert clar_req.hitl_type == HITLType.CLARIFICATION
        assert clar_req.status == HITLStatus.PENDING
        assert clar_req.clarification_data is not None
        assert clar_req.clarification_data.question == "What color?"

        # Decision request
        dec_req = create_decision_request(
            request_id="deci_test456",
            conversation_id="conv_1",
            question="Choose option",
            options=[DecisionOption(id="a", label="Option A")],
        )
        assert dec_req.hitl_type == HITLType.DECISION
        assert dec_req.decision_data is not None
        assert dec_req.decision_data.question == "Choose option"

        # EnvVar request
        env_req = create_env_var_request(
            request_id="env_test789",
            conversation_id="conv_1",
            tool_name="api_tool",
            fields=[EnvVarField(name="API_KEY", label="API Key", required=True)],
        )
        assert env_req.hitl_type == HITLType.ENV_VAR
        assert env_req.env_var_data is not None
        assert env_req.env_var_data.tool_name == "api_tool"

        # Permission request - use RiskLevel enum
        perm_req = create_permission_request(
            request_id="perm_testabc",
            conversation_id="conv_1",
            tool_name="file_write",
            action="write to /etc/hosts",
            risk_level=RiskLevel.HIGH,
        )
        assert perm_req.hitl_type == HITLType.PERMISSION
        assert perm_req.permission_data is not None
        assert perm_req.permission_data.risk_level == RiskLevel.HIGH

    def test_helper_functions_work_correctly(self):
        """Test helper functions for request expiry."""
        from src.domain.model.agent.hitl_types import (
            HITLRequest,
            HITLType,
            HITLStatus,
            ClarificationRequestData,
            ClarificationOption,
            is_request_expired,
            get_remaining_time_seconds,
        )
        from datetime import datetime, timezone, timedelta

        # Create a request manually with timezone-aware datetime
        now = datetime.now(timezone.utc)
        request = HITLRequest(
            request_id="test_exp",
            hitl_type=HITLType.CLARIFICATION,
            conversation_id="conv_1",
            created_at=now,
            timeout_seconds=300.0,
            expires_at=now + timedelta(seconds=300),
            clarification_data=ClarificationRequestData(
                question="Test?",
                options=[ClarificationOption(id="yes", label="Yes")],
            ),
        )

        # Should not be expired immediately
        assert not is_request_expired(request)

        # Should have remaining time
        remaining = get_remaining_time_seconds(request)
        assert remaining is not None
        assert remaining > 290  # Should be close to 300


@pytest.mark.integration
class TestHITLHandlerIntegration:
    """Integration tests for the HITL strategies."""

    def test_strategy_request_id_prefixes(self):
        """Test each strategy generates correct request ID prefix."""
        from src.infrastructure.agent.hitl.hitl_strategies import (
            ClarificationStrategy,
            DecisionStrategy,
            EnvVarStrategy,
            PermissionStrategy,
        )

        clar_strategy = ClarificationStrategy()
        dec_strategy = DecisionStrategy()
        env_strategy = EnvVarStrategy()
        perm_strategy = PermissionStrategy()

        clar_id = clar_strategy.generate_request_id()
        assert clar_id.startswith("clar_")

        dec_id = dec_strategy.generate_request_id()
        assert dec_id.startswith("deci_")

        env_id = env_strategy.generate_request_id()
        assert env_id.startswith("env_")

        perm_id = perm_strategy.generate_request_id()
        assert perm_id.startswith("perm_")


@pytest.mark.integration
class TestHITLServicePortIntegration:
    """Integration tests for the HITLServicePort interface."""

    def test_service_port_interface_is_abstract(self):
        """Test HITLServicePort is an abstract interface."""
        from src.domain.ports.services.hitl_service_port import HITLServicePort
        import abc

        assert abc.ABC in HITLServicePort.__bases__

        # Should have abstract methods
        abstract_methods = getattr(HITLServicePort, "__abstractmethods__", set())
        assert "create_request" in abstract_methods
        assert "get_request" in abstract_methods
        assert "submit_response" in abstract_methods

    def test_signal_name_constant_exists(self):
        """Test HITL signal name constant is accessible."""
        from src.domain.model.agent.hitl_types import HITL_RESPONSE_SIGNAL

        assert HITL_RESPONSE_SIGNAL == "hitl_response"


@pytest.mark.integration
class TestHITLAPIIntegration:
    """Integration tests for HITL REST API endpoints."""

    def test_response_schema_can_be_imported(self):
        """Test HITLResponseRequest schema can be imported."""
        from src.infrastructure.adapters.primary.web.routers.agent.schemas import (
            HITLResponseRequest,
        )

        # Verify schema structure
        assert hasattr(HITLResponseRequest, "model_fields")
        fields = HITLResponseRequest.model_fields
        assert "request_id" in fields
        assert "hitl_type" in fields
        assert "response_data" in fields

    def test_hitl_router_has_respond_endpoint(self):
        """Test HITL router has the unified respond endpoint."""
        from src.infrastructure.adapters.primary.web.routers.agent.hitl import router

        # Check router has routes
        routes = [route.path for route in router.routes]
        assert any("/respond" in path for path in routes)


@pytest.mark.integration
class TestHITLEndToEndFlow:
    """End-to-end integration tests for HITL flow."""

    def test_request_creation_to_signal_payload(self):
        """Test creating a request and converting to signal payload."""
        from src.domain.model.agent.hitl_types import (
            create_clarification_request,
            HITLSignalPayload,
            HITLType,
            ClarificationOption,
        )

        # Create a request
        request = create_clarification_request(
            request_id="e2e_test_1",
            conversation_id="conv_e2e",
            question="Confirm action?",
            options=[
                ClarificationOption(id="yes", label="Yes"),
                ClarificationOption(id="no", label="No"),
            ],
        )

        # Create signal payload (simulating what frontend would send)
        # HITLSignalPayload uses response_data dict, not typed response objects
        payload = HITLSignalPayload(
            request_id=request.request_id,
            hitl_type=HITLType.CLARIFICATION,
            response_data={"answer": "yes"},
            user_id="user_123",
        )

        assert payload.request_id == "e2e_test_1"
        assert payload.hitl_type == HITLType.CLARIFICATION
        assert payload.response_data["answer"] == "yes"
        assert payload.user_id == "user_123"

    def test_full_hitl_type_coverage(self):
        """Test all HITL types have complete coverage."""
        from src.domain.model.agent.hitl_types import (
            HITLType,
            create_clarification_request,
            create_decision_request,
            create_env_var_request,
            create_permission_request,
        )
        from src.infrastructure.agent.hitl.hitl_strategies import (
            ClarificationStrategy,
            DecisionStrategy,
            EnvVarStrategy,
            PermissionStrategy,
        )

        # All types should have factory functions
        factory_map = {
            HITLType.CLARIFICATION: create_clarification_request,
            HITLType.DECISION: create_decision_request,
            HITLType.ENV_VAR: create_env_var_request,
            HITLType.PERMISSION: create_permission_request,
        }

        # All types should have strategy implementations
        strategy_map = {
            HITLType.CLARIFICATION: ClarificationStrategy,
            HITLType.DECISION: DecisionStrategy,
            HITLType.ENV_VAR: EnvVarStrategy,
            HITLType.PERMISSION: PermissionStrategy,
        }

        for hitl_type in HITLType:
            assert hitl_type in factory_map, f"Missing factory for {hitl_type}"
            assert hitl_type in strategy_map, f"Missing strategy for {hitl_type}"
