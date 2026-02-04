"""
Unit tests for HITL (Human-in-the-Loop) unified types.

Tests the domain model types in src/domain/model/agent/hitl_types.py
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.domain.model.agent.hitl_types import (
    # Enums
    HITLType,
    HITLStatus,
    ClarificationType,
    DecisionType,
    RiskLevel,
    PermissionAction,
    EnvVarInputType,
    # Data classes
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
    # Factory functions
    create_clarification_request,
    create_decision_request,
    create_env_var_request,
    create_permission_request,
    # Helpers
    is_request_expired,
    get_remaining_time_seconds,
)


@pytest.mark.unit
class TestHITLEnums:
    """Test HITL enum types."""

    def test_hitl_type_values(self):
        """Test HITLType enum has expected values."""
        assert HITLType.CLARIFICATION.value == "clarification"
        assert HITLType.DECISION.value == "decision"
        assert HITLType.ENV_VAR.value == "env_var"
        assert HITLType.PERMISSION.value == "permission"

    def test_hitl_status_values(self):
        """Test HITLStatus enum has expected values."""
        assert HITLStatus.PENDING.value == "pending"
        assert HITLStatus.ANSWERED.value == "answered"
        assert HITLStatus.COMPLETED.value == "completed"
        assert HITLStatus.TIMEOUT.value == "timeout"
        assert HITLStatus.CANCELLED.value == "cancelled"

    def test_clarification_type_values(self):
        """Test ClarificationType enum has expected values."""
        assert ClarificationType.SCOPE.value == "scope"
        assert ClarificationType.APPROACH.value == "approach"
        assert ClarificationType.PREREQUISITE.value == "prerequisite"

    def test_decision_type_values(self):
        """Test DecisionType enum has expected values."""
        assert DecisionType.BRANCH.value == "branch"
        assert DecisionType.METHOD.value == "method"
        assert DecisionType.CONFIRMATION.value == "confirmation"
        assert DecisionType.RISK.value == "risk"

    def test_risk_level_values(self):
        """Test RiskLevel enum has expected values."""
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"
        assert RiskLevel.CRITICAL.value == "critical"

    def test_permission_action_values(self):
        """Test PermissionAction enum has expected values."""
        assert PermissionAction.ALLOW.value == "allow"
        assert PermissionAction.DENY.value == "deny"
        assert PermissionAction.ALLOW_ALWAYS.value == "allow_always"
        assert PermissionAction.DENY_ALWAYS.value == "deny_always"


@pytest.mark.unit
class TestClarificationOption:
    """Test ClarificationOption data class."""

    def test_create_basic_option(self):
        """Test creating a basic clarification option."""
        option = ClarificationOption(
            id="opt-1",
            label="Option 1",
        )
        assert option.id == "opt-1"
        assert option.label == "Option 1"
        assert option.description is None
        assert option.recommended is False

    def test_create_recommended_option(self):
        """Test creating a recommended option."""
        option = ClarificationOption(
            id="opt-2",
            label="Recommended Option",
            description="This is the recommended choice",
            recommended=True,
        )
        assert option.recommended is True
        assert option.description == "This is the recommended choice"


@pytest.mark.unit
class TestDecisionOption:
    """Test DecisionOption data class."""

    def test_create_basic_option(self):
        """Test creating a basic decision option."""
        option = DecisionOption(
            id="dec-1",
            label="Decision 1",
        )
        assert option.id == "dec-1"
        assert option.label == "Decision 1"
        # risks has a default_factory of list, so it's []
        assert option.risks == []
        assert option.estimated_time is None

    def test_create_option_with_risks(self):
        """Test creating an option with risks."""
        option = DecisionOption(
            id="dec-2",
            label="Risky Decision",
            description="This might cause issues",
            recommended=False,
            risk_level=RiskLevel.HIGH,
            risks=["Data loss possible", "Downtime expected"],
            estimated_time="2 hours",
            estimated_cost="$50",
        )
        assert option.risk_level == RiskLevel.HIGH
        assert len(option.risks) == 2
        assert option.estimated_time == "2 hours"


@pytest.mark.unit
class TestEnvVarField:
    """Test EnvVarField data class."""

    def test_create_text_field(self):
        """Test creating a text input field."""
        field = EnvVarField(
            name="API_KEY",
            label="API Key",
            required=True,
            secret=True,
            input_type=EnvVarInputType.PASSWORD,
        )
        assert field.name == "API_KEY"
        assert field.required is True
        assert field.secret is True
        assert field.input_type == EnvVarInputType.PASSWORD

    def test_create_optional_field(self):
        """Test creating an optional field with default."""
        field = EnvVarField(
            name="TIMEOUT",
            label="Timeout (seconds)",
            required=False,
            secret=False,
            input_type=EnvVarInputType.TEXT,
            default_value="30",
            placeholder="Enter timeout in seconds",
        )
        assert field.required is False
        assert field.default_value == "30"


@pytest.mark.unit
class TestRequestDataClasses:
    """Test request data classes."""

    def test_clarification_request_data(self):
        """Test ClarificationRequestData creation."""
        data = ClarificationRequestData(
            question="Which approach should we use?",
            clarification_type=ClarificationType.APPROACH,
            options=[
                ClarificationOption(id="a", label="Approach A"),
                ClarificationOption(id="b", label="Approach B"),
            ],
            allow_custom=True,
        )
        assert data.question == "Which approach should we use?"
        assert len(data.options) == 2
        assert data.allow_custom is True

    def test_decision_request_data(self):
        """Test DecisionRequestData creation."""
        data = DecisionRequestData(
            question="Continue with deployment?",
            decision_type=DecisionType.CONFIRMATION,
            options=[
                DecisionOption(id="yes", label="Yes, proceed"),
                DecisionOption(id="no", label="No, abort"),
            ],
            default_option="no",
        )
        assert data.decision_type == DecisionType.CONFIRMATION
        assert data.default_option == "no"

    def test_env_var_request_data(self):
        """Test EnvVarRequestData creation."""
        data = EnvVarRequestData(
            tool_name="web_search",
            fields=[
                EnvVarField(
                    name="SERPER_API_KEY",
                    label="Serper API Key",
                    required=True,
                    secret=True,
                    input_type=EnvVarInputType.PASSWORD,
                ),
            ],
            message="Web search requires an API key",
        )
        assert data.tool_name == "web_search"
        assert len(data.fields) == 1

    def test_permission_request_data(self):
        """Test PermissionRequestData creation."""
        data = PermissionRequestData(
            tool_name="terminal",
            action="execute_command",
            risk_level=RiskLevel.HIGH,
            description="Execute shell command: rm -rf /tmp/test",
            allow_remember=True,
        )
        assert data.tool_name == "terminal"
        assert data.risk_level == RiskLevel.HIGH


@pytest.mark.unit
class TestResponseDataClasses:
    """Test response data classes."""

    def test_clarification_response(self):
        """Test ClarificationResponse."""
        response = ClarificationResponse(answer="approach-a")
        assert response.answer == "approach-a"

    def test_clarification_response_list(self):
        """Test ClarificationResponse with list answer."""
        response = ClarificationResponse(answer=["opt-1", "opt-2"])
        assert isinstance(response.answer, list)
        assert len(response.answer) == 2

    def test_decision_response(self):
        """Test DecisionResponse."""
        response = DecisionResponse(decision="yes")
        assert response.decision == "yes"

    def test_env_var_response(self):
        """Test EnvVarResponse."""
        response = EnvVarResponse(
            values={"API_KEY": "secret123", "TIMEOUT": "60"},
            save=True,
        )
        assert len(response.values) == 2
        assert response.save is True

    def test_permission_response(self):
        """Test PermissionResponse."""
        response = PermissionResponse(
            action=PermissionAction.ALLOW_ALWAYS,
            remember=True,
        )
        assert response.action == PermissionAction.ALLOW_ALWAYS
        assert response.remember is True


@pytest.mark.unit
class TestHITLRequest:
    """Test HITLRequest data class."""

    def test_create_request(self):
        """Test creating a HITL request."""
        request = HITLRequest(
            request_id="req-123",
            hitl_type=HITLType.CLARIFICATION,
            conversation_id="conv-456",
            status=HITLStatus.PENDING,
            timeout_seconds=300,
            clarification_data=ClarificationRequestData(
                question="Test question?",
                clarification_type=ClarificationType.CUSTOM,
                options=[],
            ),
        )

        assert request.request_id == "req-123"
        assert request.hitl_type == HITLType.CLARIFICATION
        assert request.status == HITLStatus.PENDING
        assert request.clarification_data is not None
        # expires_at should be auto-computed
        assert request.expires_at is not None

    def test_request_optional_fields(self):
        """Test request with optional fields."""
        request = HITLRequest(
            request_id="req-789",
            hitl_type=HITLType.DECISION,
            conversation_id="conv-abc",
            status=HITLStatus.PENDING,
            timeout_seconds=600,
            message_id="msg-xyz",
            user_id="user-001",
            tenant_id="tenant-1",
            project_id="project-1",
        )

        assert request.message_id == "msg-xyz"
        assert request.user_id == "user-001"
        assert request.tenant_id == "tenant-1"


@pytest.mark.unit
class TestHITLResponse:
    """Test HITLResponse data class."""

    def test_create_response(self):
        """Test creating a HITL response."""
        response = HITLResponse(
            request_id="req-123",
            hitl_type=HITLType.CLARIFICATION,
            clarification_response=ClarificationResponse(answer="option-1"),
            user_id="user-001",
        )

        assert response.request_id == "req-123"
        assert response.user_id == "user-001"
        assert response.clarification_response is not None
        assert response.response_value == "option-1"


@pytest.mark.unit
class TestHITLSignalPayload:
    """Test HITLSignalPayload data class."""

    def test_create_signal_payload(self):
        """Test creating a signal payload for Temporal."""
        payload = HITLSignalPayload(
            request_id="req-123",
            hitl_type=HITLType.PERMISSION,
            response_data={"action": "allow", "remember": False},
            user_id="user-001",
        )

        assert payload.request_id == "req-123"
        assert payload.hitl_type == HITLType.PERMISSION
        assert payload.response_data["action"] == "allow"
        assert payload.timestamp is not None


@pytest.mark.unit
class TestFactoryFunctions:
    """Test HITL request factory functions."""

    def test_create_clarification_request(self):
        """Test create_clarification_request factory."""
        request = create_clarification_request(
            request_id="hitl_test_123",
            conversation_id="conv-1",
            question="What scope?",
            clarification_type=ClarificationType.SCOPE,
            options=[
                ClarificationOption(id="full", label="Full scope"),
                ClarificationOption(id="partial", label="Partial scope"),
            ],
            timeout_seconds=120,
        )

        assert request.hitl_type == HITLType.CLARIFICATION
        assert request.conversation_id == "conv-1"
        assert request.timeout_seconds == 120
        assert request.clarification_data is not None
        assert request.clarification_data.question == "What scope?"
        assert len(request.clarification_data.options) == 2
        assert request.request_id == "hitl_test_123"

    def test_create_decision_request(self):
        """Test create_decision_request factory."""
        request = create_decision_request(
            request_id="hitl_dec_123",
            conversation_id="conv-2",
            question="Proceed with migration?",
            decision_type=DecisionType.RISK,
            options=[
                DecisionOption(
                    id="proceed",
                    label="Proceed",
                    risks=["Potential data loss"],
                    risk_level=RiskLevel.HIGH,
                ),
                DecisionOption(id="cancel", label="Cancel"),
            ],
            default_option="cancel",
        )

        assert request.hitl_type == HITLType.DECISION
        assert request.decision_data is not None
        assert request.decision_data.default_option == "cancel"

    def test_create_env_var_request(self):
        """Test create_env_var_request factory."""
        request = create_env_var_request(
            request_id="hitl_env_123",
            conversation_id="conv-3",
            tool_name="github_search",
            fields=[
                EnvVarField(
                    name="GITHUB_TOKEN",
                    label="GitHub Token",
                    required=True,
                    secret=True,
                    input_type=EnvVarInputType.PASSWORD,
                ),
            ],
            message="GitHub access requires authentication",
        )

        assert request.hitl_type == HITLType.ENV_VAR
        assert request.env_var_data is not None
        assert request.env_var_data.tool_name == "github_search"

    def test_create_permission_request(self):
        """Test create_permission_request factory."""
        request = create_permission_request(
            request_id="hitl_perm_123",
            conversation_id="conv-4",
            tool_name="file_write",
            action="write_file",
            risk_level=RiskLevel.MEDIUM,
            description="Write to /tmp/output.txt",
            details={"path": "/tmp/output.txt", "size": 1024},
        )

        assert request.hitl_type == HITLType.PERMISSION
        assert request.permission_data is not None
        assert request.permission_data.tool_name == "file_write"
        assert request.permission_data.details["path"] == "/tmp/output.txt"


@pytest.mark.unit
class TestHelperFunctions:
    """Test HITL helper functions."""

    def test_is_request_expired_not_expired(self):
        """Test is_request_expired for non-expired request."""
        future = datetime.now(timezone.utc) + timedelta(minutes=5)
        request = HITLRequest(
            request_id="req-1",
            hitl_type=HITLType.CLARIFICATION,
            conversation_id="conv-1",
            status=HITLStatus.PENDING,
            timeout_seconds=300,
        )
        # Override expires_at to be in the future
        request.expires_at = future

        assert is_request_expired(request) is False

    def test_is_request_expired_expired(self):
        """Test is_request_expired for expired request."""
        past = datetime.now(timezone.utc) - timedelta(minutes=5)
        request = HITLRequest(
            request_id="req-2",
            hitl_type=HITLType.CLARIFICATION,
            conversation_id="conv-2",
            status=HITLStatus.PENDING,
            timeout_seconds=300,
        )
        # Override expires_at to be in the past
        request.expires_at = past

        assert is_request_expired(request) is True

    def test_is_request_expired_no_expiry(self):
        """Test is_request_expired when expires_at is None."""
        request = HITLRequest(
            request_id="req-3",
            hitl_type=HITLType.CLARIFICATION,
            conversation_id="conv-3",
            status=HITLStatus.PENDING,
            timeout_seconds=300,
        )
        # Set expires_at to None
        request.expires_at = None

        assert is_request_expired(request) is False

    def test_get_remaining_time_seconds(self):
        """Test get_remaining_time_seconds."""
        future = datetime.now(timezone.utc) + timedelta(seconds=120)
        request = HITLRequest(
            request_id="req-4",
            hitl_type=HITLType.CLARIFICATION,
            conversation_id="conv-4",
            status=HITLStatus.PENDING,
            timeout_seconds=300,
        )
        request.expires_at = future

        remaining = get_remaining_time_seconds(request)
        # Should be around 120, allow some tolerance
        assert 115 <= remaining <= 125

    def test_get_remaining_time_expired(self):
        """Test get_remaining_time_seconds for expired request."""
        past = datetime.now(timezone.utc) - timedelta(seconds=60)
        request = HITLRequest(
            request_id="req-5",
            hitl_type=HITLType.CLARIFICATION,
            conversation_id="conv-5",
            status=HITLStatus.PENDING,
            timeout_seconds=300,
        )
        request.expires_at = past

        remaining = get_remaining_time_seconds(request)
        assert remaining < 0

    def test_get_remaining_time_no_expiry(self):
        """Test get_remaining_time_seconds when no expiry set."""
        request = HITLRequest(
            request_id="req-6",
            hitl_type=HITLType.CLARIFICATION,
            conversation_id="conv-6",
            status=HITLStatus.PENDING,
            timeout_seconds=300,
        )
        request.expires_at = None

        remaining = get_remaining_time_seconds(request)
        assert remaining is None


@pytest.mark.unit
class TestHITLPendingException:
    """Test HITLPendingException for HITL pause/resume mechanism."""

    def test_create_exception(self):
        """Test creating HITLPendingException with all fields."""
        from src.domain.model.agent.hitl_types import HITLPendingException

        ex = HITLPendingException(
            request_id="clarif_abc123",
            hitl_type=HITLType.CLARIFICATION,
            request_data={"question": "Which approach?"},
            conversation_id="conv-123",
            message_id="msg-456",
            timeout_seconds=300.0,
        )

        assert ex.request_id == "clarif_abc123"
        assert ex.hitl_type == HITLType.CLARIFICATION
        assert ex.request_data["question"] == "Which approach?"
        assert ex.conversation_id == "conv-123"
        assert ex.message_id == "msg-456"
        assert ex.timeout_seconds == 300.0

    def test_exception_string_representation(self):
        """Test exception string representation."""
        from src.domain.model.agent.hitl_types import HITLPendingException

        ex = HITLPendingException(
            request_id="decision_xyz",
            hitl_type=HITLType.DECISION,
            request_data={"question": "Confirm action?"},
            conversation_id="conv-789",
            timeout_seconds=60.0,
        )

        str_repr = str(ex)
        assert "decision_xyz" in str_repr
        assert "DECISION" in str_repr or "decision" in str_repr

    def test_exception_can_be_raised_and_caught(self):
        """Test that exception can be properly raised and caught."""
        from src.domain.model.agent.hitl_types import HITLPendingException

        with pytest.raises(HITLPendingException) as exc_info:
            raise HITLPendingException(
                request_id="env_var_123",
                hitl_type=HITLType.ENV_VAR,
                request_data={"tool_name": "github_api"},
                conversation_id="conv-test",
            )

        ex = exc_info.value
        assert ex.request_id == "env_var_123"
        assert ex.hitl_type == HITLType.ENV_VAR

    def test_exception_with_optional_fields(self):
        """Test exception with optional fields set to None."""
        from src.domain.model.agent.hitl_types import HITLPendingException

        ex = HITLPendingException(
            request_id="perm_test",
            hitl_type=HITLType.PERMISSION,
            request_data={},
            conversation_id="conv-optional",
            message_id=None,
            timeout_seconds=None,
        )

        assert ex.message_id is None
        assert ex.timeout_seconds is None
