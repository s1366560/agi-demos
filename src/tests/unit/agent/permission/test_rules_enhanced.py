"""Tests for permission rules module."""

import pytest

from src.infrastructure.agent.permission.rules import (
    PermissionAction,
    PermissionRule,
    RuleScope,
    classify_sandbox_tool_permission,
    default_ruleset,
    evaluate_rules,
    explore_mode_ruleset,
    get_disabled_tools,
    sandbox_mcp_ruleset,
)


@pytest.mark.unit
class TestRuleScope:
    """Tests for RuleScope enum."""

    def test_values(self) -> None:
        assert RuleScope.AGENT.value == "agent"
        assert RuleScope.USER.value == "user"
        assert RuleScope.SESSION.value == "session"

    def test_is_str_enum(self) -> None:
        assert isinstance(RuleScope.AGENT, str)


@pytest.mark.unit
class TestPermissionAction:
    """Tests for PermissionAction enum."""

    def test_values(self) -> None:
        assert PermissionAction.ALLOW.value == "allow"
        assert PermissionAction.DENY.value == "deny"
        assert PermissionAction.ASK.value == "ask"


@pytest.mark.unit
class TestPermissionRule:
    """Tests for PermissionRule dataclass."""

    def test_create_defaults(self) -> None:
        rule = PermissionRule("read", "*.py", PermissionAction.ALLOW)
        assert rule.scope == RuleScope.AGENT
        assert rule.arg_pattern is None

    def test_matches_exact(self) -> None:
        rule = PermissionRule("read", "*.py", PermissionAction.ALLOW)
        assert rule.matches("read", "file.py") is True
        assert rule.matches("write", "file.py") is False
        assert rule.matches("read", "file.txt") is False

    def test_matches_wildcard_permission(self) -> None:
        rule = PermissionRule("*", "*", PermissionAction.ALLOW)
        assert rule.matches("read", "anything") is True
        assert rule.matches("bash", "command") is True

    def test_matches_wildcard_pattern(self) -> None:
        rule = PermissionRule("read", "*", PermissionAction.ALLOW)
        assert rule.matches("read", "any_file") is True

    def test_matches_with_arg_pattern(self) -> None:
        rule = PermissionRule("bash", "*", PermissionAction.DENY, arg_pattern="cmd:rm*")
        assert rule.matches("bash", "terminal", args={"cmd": "rm -rf /"}) is True
        assert rule.matches("bash", "terminal", args={"cmd": "ls"}) is False
        assert rule.matches("bash", "terminal", args={"cmd": "rmdir foo"}) is True

    def test_matches_arg_pattern_missing_key(self) -> None:
        rule = PermissionRule("bash", "*", PermissionAction.DENY, arg_pattern="cmd:rm*")
        assert rule.matches("bash", "terminal", args={"other": "value"}) is False

    def test_matches_arg_pattern_no_args(self) -> None:
        rule = PermissionRule("bash", "*", PermissionAction.DENY, arg_pattern="cmd:rm*")
        # No args to check -- matches permission+target
        assert rule.matches("bash", "terminal", args=None) is True

    def test_matches_arg_pattern_none(self) -> None:
        rule = PermissionRule("bash", "*", PermissionAction.DENY, arg_pattern=None)
        assert rule.matches("bash", "terminal") is True

    def test_matches_malformed_arg_pattern(self) -> None:
        # No colon in arg_pattern
        rule = PermissionRule("bash", "*", PermissionAction.DENY, arg_pattern="nocol")
        assert rule.matches("bash", "terminal", args={"cmd": "ls"}) is True

    def test_to_dict_minimal(self) -> None:
        rule = PermissionRule("read", "*.py", PermissionAction.ALLOW)
        d = rule.to_dict()
        assert d == {"permission": "read", "pattern": "*.py", "action": "allow"}
        assert "scope" not in d
        assert "arg_pattern" not in d

    def test_to_dict_full(self) -> None:
        rule = PermissionRule(
            "bash",
            "terminal",
            PermissionAction.ASK,
            scope=RuleScope.SESSION,
            arg_pattern="cmd:sudo*",
        )
        d = rule.to_dict()
        assert d["scope"] == "session"
        assert d["arg_pattern"] == "cmd:sudo*"

    def test_from_dict_minimal(self) -> None:
        data = {"permission": "read", "pattern": "*", "action": "allow"}
        rule = PermissionRule.from_dict(data)
        assert rule.permission == "read"
        assert rule.action == PermissionAction.ALLOW
        assert rule.scope == RuleScope.AGENT

    def test_from_dict_full(self) -> None:
        data = {
            "permission": "bash",
            "pattern": "*",
            "action": "deny",
            "scope": "session",
            "arg_pattern": "cmd:rm*",
        }
        rule = PermissionRule.from_dict(data)
        assert rule.scope == RuleScope.SESSION
        assert rule.arg_pattern == "cmd:rm*"

    def test_roundtrip_dict(self) -> None:
        original = PermissionRule(
            "write",
            "*.env",
            PermissionAction.ASK,
            scope=RuleScope.USER,
            arg_pattern="path:*.secret",
        )
        restored = PermissionRule.from_dict(original.to_dict())
        assert restored.permission == original.permission
        assert restored.pattern == original.pattern
        assert restored.action == original.action
        assert restored.scope == original.scope
        assert restored.arg_pattern == original.arg_pattern


@pytest.mark.unit
class TestEvaluateRules:
    """Tests for evaluate_rules function."""

    def test_no_rules_returns_default_ask(self) -> None:
        rule = evaluate_rules("read", "file.py")
        assert rule.action == PermissionAction.ASK

    def test_single_match(self) -> None:
        rules = [PermissionRule("read", "*", PermissionAction.ALLOW)]
        rule = evaluate_rules("read", "file.py", rules)
        assert rule.action == PermissionAction.ALLOW

    def test_last_match_wins(self) -> None:
        rules = [
            PermissionRule("read", "*", PermissionAction.ALLOW),
            PermissionRule("read", "*.env", PermissionAction.DENY),
        ]
        rule = evaluate_rules("read", "config.env", rules)
        assert rule.action == PermissionAction.DENY

    def test_no_match_returns_ask(self) -> None:
        rules = [PermissionRule("write", "*.py", PermissionAction.ALLOW)]
        rule = evaluate_rules("read", "file.txt", rules)
        assert rule.action == PermissionAction.ASK

    def test_multiple_rulesets_merged(self) -> None:
        set1 = [PermissionRule("read", "*", PermissionAction.ALLOW)]
        set2 = [PermissionRule("read", "*.env", PermissionAction.DENY)]
        rule = evaluate_rules("read", "app.env", set1, set2)
        assert rule.action == PermissionAction.DENY

    def test_with_args(self) -> None:
        rules = [
            PermissionRule("bash", "*", PermissionAction.ALLOW),
            PermissionRule("bash", "*", PermissionAction.DENY, arg_pattern="cmd:rm*"),
        ]
        # Non-rm command should be allowed (last match wins; DENY doesn't match)
        rule = evaluate_rules("bash", "terminal", rules, args={"cmd": "ls"})
        assert rule.action == PermissionAction.ALLOW

        # rm command should be denied
        rule = evaluate_rules("bash", "terminal", rules, args={"cmd": "rm -rf /"})
        assert rule.action == PermissionAction.DENY

    def test_empty_rulesets_handled(self) -> None:
        rule = evaluate_rules("read", "file", [], [], [])
        assert rule.action == PermissionAction.ASK


@pytest.mark.unit
class TestGetDisabledTools:
    """Tests for get_disabled_tools function."""

    def test_no_disabled(self) -> None:
        rules = [PermissionRule("*", "*", PermissionAction.ALLOW)]
        result = get_disabled_tools(["bash", "read"], rules)
        assert result == set()

    def test_deny_with_wildcard_pattern(self) -> None:
        rules = [PermissionRule("bash", "*", PermissionAction.DENY)]
        result = get_disabled_tools(["bash", "read"], rules)
        assert "bash" in result
        assert "read" not in result

    def test_edit_tools_share_permission(self) -> None:
        rules = [PermissionRule("edit", "*", PermissionAction.DENY)]
        result = get_disabled_tools(["edit", "write", "patch", "multiedit", "bash"], rules)
        assert result == {"edit", "write", "patch", "multiedit"}

    def test_deny_non_wildcard_pattern_does_not_disable(self) -> None:
        rules = [PermissionRule("bash", "specific_tool", PermissionAction.DENY)]
        result = get_disabled_tools(["bash"], rules)
        # Only wildcard pattern * disables
        assert result == set()


@pytest.mark.unit
class TestDefaultRuleset:
    """Tests for default_ruleset function."""

    def test_returns_list(self) -> None:
        rules = default_ruleset()
        assert isinstance(rules, list)
        assert len(rules) > 0

    def test_first_rule_allows_all(self) -> None:
        rules = default_ruleset()
        assert rules[0].permission == "*"
        assert rules[0].pattern == "*"
        assert rules[0].action == PermissionAction.ALLOW

    def test_env_file_rules(self) -> None:
        rules = default_ruleset()
        actions = {r.pattern: r.action for r in rules if "env" in r.pattern.lower()}
        assert actions.get("*.env") == PermissionAction.ASK
        assert actions.get("*.env.example") == PermissionAction.ALLOW


@pytest.mark.unit
class TestExploreModeRuleset:
    """Tests for explore_mode_ruleset function."""

    def test_denies_modifications(self) -> None:
        rules = explore_mode_ruleset()
        deny_permissions = {r.permission for r in rules if r.action == PermissionAction.DENY}
        assert "edit" in deny_permissions
        assert "write" in deny_permissions
        assert "bash" in deny_permissions

    def test_allows_reads(self) -> None:
        rules = explore_mode_ruleset()
        allow_permissions = {r.permission for r in rules if r.action == PermissionAction.ALLOW}
        assert "read" in allow_permissions
        assert "glob" in allow_permissions
        assert "grep" in allow_permissions


@pytest.mark.unit
class TestClassifySandboxToolPermission:
    """Tests for classify_sandbox_tool_permission function."""

    def test_read_tools(self) -> None:
        assert classify_sandbox_tool_permission("file_read") == "read"
        assert classify_sandbox_tool_permission("grep") == "read"
        assert classify_sandbox_tool_permission("glob") == "read"

    def test_write_tools(self) -> None:
        assert classify_sandbox_tool_permission("file_write") == "write"
        assert classify_sandbox_tool_permission("create_file") == "write"
        assert classify_sandbox_tool_permission("delete_file") == "write"

    def test_execute_tools(self) -> None:
        assert classify_sandbox_tool_permission("bash") == "bash"
        assert classify_sandbox_tool_permission("execute") == "bash"
        assert classify_sandbox_tool_permission("python") == "bash"

    def test_unknown_defaults_to_ask(self) -> None:
        assert classify_sandbox_tool_permission("unknown_tool") == "ask"

    def test_case_insensitive(self) -> None:
        assert classify_sandbox_tool_permission("BASH") == "bash"
        assert classify_sandbox_tool_permission("File_Read") == "read"


@pytest.mark.unit
class TestSandboxMCPRuleset:
    """Tests for sandbox_mcp_ruleset function."""

    def test_returns_list(self) -> None:
        rules = sandbox_mcp_ruleset()
        assert isinstance(rules, list)
        assert len(rules) > 0

    def test_read_tools_allowed(self) -> None:
        rules = sandbox_mcp_ruleset()
        read_rules = [
            r for r in rules if r.permission == "read" and r.action == PermissionAction.ALLOW
        ]
        read_patterns = {r.pattern for r in read_rules}
        assert "file_read" in read_patterns
        assert "grep" in read_patterns

    def test_write_tools_ask(self) -> None:
        rules = sandbox_mcp_ruleset()
        write_rules = [
            r for r in rules if r.permission == "write" and r.action == PermissionAction.ASK
        ]
        write_patterns = {r.pattern for r in write_rules}
        assert "file_write" in write_patterns

    def test_bash_tools_ask(self) -> None:
        rules = sandbox_mcp_ruleset()
        bash_rules = [
            r for r in rules if r.permission == "bash" and r.action == PermissionAction.ASK
        ]
        bash_patterns = {r.pattern for r in bash_rules}
        assert "bash" in bash_patterns
