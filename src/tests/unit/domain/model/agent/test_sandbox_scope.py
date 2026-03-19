"""Tests for sandbox scope definitions and resolver."""

import pytest

from src.domain.model.agent.sandbox_scope import SandboxScope, SandboxScopeResolver


@pytest.mark.unit
class TestSandboxScope:
    """SandboxScope enum tests."""

    def test_session_scope_value(self):
        """Test SESSION scope has correct string value."""
        assert SandboxScope.SESSION.value == "session"

    def test_agent_scope_value(self):
        """Test AGENT scope has correct string value."""
        assert SandboxScope.AGENT.value == "agent"

    def test_shared_scope_value(self):
        """Test SHARED scope has correct string value."""
        assert SandboxScope.SHARED.value == "shared"

    def test_session_scope_is_string(self):
        """Test SESSION scope is a string instance."""
        assert isinstance(SandboxScope.SESSION, str)

    def test_agent_scope_is_string(self):
        """Test AGENT scope is a string instance."""
        assert isinstance(SandboxScope.AGENT, str)

    def test_shared_scope_is_string(self):
        """Test SHARED scope is a string instance."""
        assert isinstance(SandboxScope.SHARED, str)

    def test_all_scopes_are_enum_members(self):
        """Test there are exactly three scope members."""
        scopes = [SandboxScope.SESSION, SandboxScope.AGENT, SandboxScope.SHARED]
        assert len(scopes) == 3

    def test_scopes_equality_by_value(self):
        """Test scopes compare equal to their string values."""
        assert SandboxScope.SESSION == "session"
        assert SandboxScope.AGENT == "agent"
        assert SandboxScope.SHARED == "shared"

    def test_session_scope_is_not_agent_scope(self):
        """Test different scopes are not equal."""
        assert SandboxScope.SESSION != SandboxScope.AGENT

    def test_agent_scope_is_not_shared_scope(self):
        """Test different scopes are not equal."""
        assert SandboxScope.AGENT != SandboxScope.SHARED

    def test_shared_scope_is_not_session_scope(self):
        """Test different scopes are not equal."""
        assert SandboxScope.SHARED != SandboxScope.SESSION


@pytest.mark.unit
class TestSandboxScopeResolver:
    """SandboxScopeResolver static resolver tests."""

    def test_explicit_scope_takes_precedence_over_depth(self):
        """Test explicit scope overrides depth-based resolution."""
        result = SandboxScopeResolver.resolve(
            explicit_scope=SandboxScope.SHARED,
            agent_depth=0,
            has_shared_files=False,
        )
        assert result is SandboxScope.SHARED

    def test_explicit_scope_takes_precedence_over_shared_files(self):
        """Test explicit scope overrides shared_files flag."""
        result = SandboxScopeResolver.resolve(
            explicit_scope=SandboxScope.SESSION,
            agent_depth=1,
            has_shared_files=True,
        )
        assert result is SandboxScope.SESSION

    def test_explicit_scope_agent_with_root_depth(self):
        """Test explicit AGENT scope overrides root agent default."""
        result = SandboxScopeResolver.resolve(
            explicit_scope=SandboxScope.AGENT,
            agent_depth=0,
            has_shared_files=False,
        )
        assert result is SandboxScope.AGENT

    def test_shared_files_returns_shared_when_no_explicit_scope(self):
        """Test shared_files flag triggers SHARED scope."""
        result = SandboxScopeResolver.resolve(
            explicit_scope=None,
            agent_depth=1,
            has_shared_files=True,
        )
        assert result is SandboxScope.SHARED

    def test_shared_files_returns_shared_for_root_agent(self):
        """Test shared_files returns SHARED even for root agents."""
        result = SandboxScopeResolver.resolve(
            explicit_scope=None,
            agent_depth=0,
            has_shared_files=True,
        )
        assert result is SandboxScope.SHARED

    def test_root_agent_depth_zero_returns_session(self):
        """Test root agent (depth 0) defaults to SESSION scope."""
        result = SandboxScopeResolver.resolve(
            explicit_scope=None,
            agent_depth=0,
            has_shared_files=False,
        )
        assert result is SandboxScope.SESSION

    def test_child_agent_depth_one_returns_agent(self):
        """Test child agent (depth 1) defaults to AGENT scope."""
        result = SandboxScopeResolver.resolve(
            explicit_scope=None,
            agent_depth=1,
            has_shared_files=False,
        )
        assert result is SandboxScope.AGENT

    def test_child_agent_depth_two_returns_agent(self):
        """Test deeper child agent (depth 2) defaults to AGENT scope."""
        result = SandboxScopeResolver.resolve(
            explicit_scope=None,
            agent_depth=2,
            has_shared_files=False,
        )
        assert result is SandboxScope.AGENT

    def test_child_agent_large_depth_returns_agent(self):
        """Test very deep child agent still uses AGENT scope."""
        result = SandboxScopeResolver.resolve(
            explicit_scope=None,
            agent_depth=100,
            has_shared_files=False,
        )
        assert result is SandboxScope.AGENT

    def test_negative_agent_depth_raises_value_error(self):
        """Test negative depth raises ValueError."""
        with pytest.raises(ValueError, match="Agent depth cannot be negative"):
            _ = SandboxScopeResolver.resolve(
                explicit_scope=None,
                agent_depth=-1,
                has_shared_files=False,
            )

    def test_negative_depth_raises_error_with_explicit_scope_none(self):
        """Test negative depth error happens before explicit scope check."""
        with pytest.raises(ValueError, match="Agent depth cannot be negative"):
            _ = SandboxScopeResolver.resolve(
                explicit_scope=None,
                agent_depth=-5,
                has_shared_files=False,
            )

    def test_resolution_precedence_explicit_first(self):
        """Test resolution order: explicit scope > shared_files > depth."""
        # All conditions would make different decisions, explicit wins
        result = SandboxScopeResolver.resolve(
            explicit_scope=SandboxScope.AGENT,
            agent_depth=0,  # Would give SESSION
            has_shared_files=True,  # Would give SHARED
        )
        assert result is SandboxScope.AGENT

    def test_resolution_precedence_shared_files_second(self):
        """Test shared_files checked before depth."""
        result = SandboxScopeResolver.resolve(
            explicit_scope=None,
            agent_depth=0,  # Would give SESSION
            has_shared_files=True,  # Overrides depth logic
        )
        assert result is SandboxScope.SHARED

    def test_default_parameters(self):
        """Test resolve with default parameters uses SESSION."""
        result = SandboxScopeResolver.resolve()
        assert result is SandboxScope.SESSION

    def test_default_parameters_are_as_documented(self):
        """Test documented defaults: explicit_scope=None, agent_depth=0, has_shared_files=False."""
        result_defaults = SandboxScopeResolver.resolve()
        result_explicit = SandboxScopeResolver.resolve(
            explicit_scope=None,
            agent_depth=0,
            has_shared_files=False,
        )
        assert result_defaults is result_explicit

    def test_only_explicit_scope_provided(self):
        """Test providing only explicit scope parameter."""
        result = SandboxScopeResolver.resolve(explicit_scope=SandboxScope.SHARED)
        assert result is SandboxScope.SHARED

    def test_only_agent_depth_provided(self):
        """Test providing only agent_depth parameter."""
        result = SandboxScopeResolver.resolve(agent_depth=1)
        assert result is SandboxScope.AGENT

    def test_only_has_shared_files_provided(self):
        """Test providing only has_shared_files parameter."""
        result = SandboxScopeResolver.resolve(has_shared_files=True)
        assert result is SandboxScope.SHARED

    def test_shared_files_false_with_root_depth_uses_session(self):
        """Test root agent with shared_files=False uses SESSION."""
        result = SandboxScopeResolver.resolve(
            explicit_scope=None,
            agent_depth=0,
            has_shared_files=False,
        )
        assert result is SandboxScope.SESSION

    def test_explicit_none_is_same_as_not_provided(self):
        """Test explicit_scope=None behaves same as omitted."""
        result_none = SandboxScopeResolver.resolve(
            explicit_scope=None,
            agent_depth=1,
            has_shared_files=False,
        )
        result_omitted = SandboxScopeResolver.resolve(
            agent_depth=1,
            has_shared_files=False,
        )
        assert result_none is result_omitted
