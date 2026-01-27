"""Tests for Agent Session Workflow recovery mechanisms.

This test suite ensures that the Workflow layer can properly recover
from session cache issues using the automatic recovery mechanism.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest


class TestAgentSessionWorkflowRecovery:
    """Test automatic recovery mechanisms in AgentSessionWorkflow."""

    def test_should_attempt_recovery_with_session_errors(self):
        """Test that _should_attempt_recovery returns True for session-related errors."""
        # Mock workflow logger
        with patch(
            "src.infrastructure.adapters.secondary.temporal.workflows.agent_session.workflow.logger"
        ):
            from src.infrastructure.adapters.secondary.temporal.workflows.agent_session import (
                AgentSessionWorkflow,
            )

            workflow = AgentSessionWorkflow()
            workflow._recovery_attempts = 0

            # Test various error messages
            assert workflow._should_attempt_recovery("Session not found") is True
            assert workflow._should_attempt_recovery("Cache expired") is True
            assert workflow._should_attempt_recovery("Invalid session") is True
            assert workflow._should_attempt_recovery("Session cache cleared") is True

    def test_should_attempt_recovery_with_non_session_errors(self):
        """Test that _should_attempt_recovery returns False for non-session errors."""
        with patch(
            "src.infrastructure.adapters.secondary.temporal.workflows.agent_session.workflow.logger"
        ):
            from src.infrastructure.adapters.secondary.temporal.workflows.agent_session import (
                AgentSessionWorkflow,
            )

            workflow = AgentSessionWorkflow()
            workflow._recovery_attempts = 0

            # Test non-recoverable errors
            assert workflow._should_attempt_recovery("Database connection failed") is False
            assert workflow._should_attempt_recovery("Network timeout") is False
            assert workflow._should_attempt_recovery("Permission denied") is False

    def test_should_attempt_recovery_limits_attempts(self):
        """Test that _should_attempt_recovery stops after max attempts."""
        with patch(
            "src.infrastructure.adapters.secondary.temporal.workflows.agent_session.workflow.logger"
        ):
            from src.infrastructure.adapters.secondary.temporal.workflows.agent_session import (
                AgentSessionWorkflow,
            )

            workflow = AgentSessionWorkflow()
            workflow._recovery_attempts = 3  # At max attempts
            workflow._max_recovery_attempts = 3

            # Should not attempt recovery even for session errors
            assert workflow._should_attempt_recovery("Session not found") is False

    def test_should_attempt_recovery_resets_on_success(self):
        """Test that recovery attempts reset after successful recovery."""
        with patch(
            "src.infrastructure.adapters.secondary.temporal.workflows.agent_session.workflow.logger"
        ):
            from src.infrastructure.adapters.secondary.temporal.workflows.agent_session import (
                AgentSessionWorkflow,
            )

            workflow = AgentSessionWorkflow()
            workflow._recovery_attempts = 1
            workflow._max_recovery_attempts = 3

            # Should still allow recovery
            assert workflow._should_attempt_recovery("Session not found") is True

            # Simulate successful recovery (reset to 0)
            workflow._recovery_attempts = 0

            # Should allow recovery again
            assert workflow._should_attempt_recovery("Session not found") is True

    def test_workflow_initialization_tracks_recovery_state(self):
        """Test that Workflow properly initializes recovery tracking."""
        with patch(
            "src.infrastructure.adapters.secondary.temporal.workflows.agent_session.workflow.logger"
        ):
            from src.infrastructure.adapters.secondary.temporal.workflows.agent_session import (
                AgentSessionWorkflow,
            )

            workflow = AgentSessionWorkflow()

            # Verify default values
            assert workflow._recovery_attempts == 0
            assert workflow._max_recovery_attempts == 3
            assert workflow._initialized is False
            assert workflow._stop_requested is False


class TestWorkflowRecoveryIntegration:
    """Integration tests for workflow recovery scenarios."""

    def test_recovery_error_patterns_comprehensive(self):
        """Test comprehensive list of error patterns that trigger recovery."""
        with patch(
            "src.infrastructure.adapters.secondary.temporal.workflows.agent_session.workflow.logger"
        ):
            from src.infrastructure.adapters.secondary.temporal.workflows.agent_session import (
                AgentSessionWorkflow,
            )

            workflow = AgentSessionWorkflow()
            workflow._recovery_attempts = 0

            # Error patterns that should trigger recovery
            recoverable_errors = [
                "Session cache cleared for tenant1:project1:default",
                "Session not found in pool",
                "Cache expired for tenant1",
                "Invalid session state",
                "Session context is None",
                "Cache miss for session key",
            ]

            for error_msg in recoverable_errors:
                assert workflow._should_attempt_recovery(error_msg) is True, \
                    f"Should recover from: {error_msg}"

            # Error patterns that should NOT trigger recovery
            non_recoverable_errors = [
                "Database connection lost",
                "Network timeout after 30s",
                "Permission denied for user",
                "Rate limit exceeded",
                "Authentication failed",
            ]

            for error_msg in non_recoverable_errors:
                assert workflow._should_attempt_recovery(error_msg) is False, \
                    f"Should NOT recover from: {error_msg}"
