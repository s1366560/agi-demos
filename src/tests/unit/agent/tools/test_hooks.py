"""Tests for ToolHookRegistry, HookDecision, HookResult, HookPriority."""

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.hooks import (
    HookDecision,
    HookPriority,
    HookResult,
    ToolHookRegistry,
)
from src.infrastructure.agent.tools.result import ToolResult


def _make_ctx() -> ToolContext:
    return ToolContext(
        session_id="s",
        message_id="m",
        call_id="c",
        agent_name="a",
        conversation_id="conv",
    )


@pytest.mark.unit
class TestHookDecision:
    """Tests for HookDecision enum."""

    def test_values(self) -> None:
        assert HookDecision.CONTINUE.value == "continue"
        assert HookDecision.DENY.value == "deny"
        assert HookDecision.ASK.value == "ask"

    def test_members(self) -> None:
        assert len(HookDecision) == 3


@pytest.mark.unit
class TestHookResult:
    """Tests for HookResult dataclass."""

    def test_defaults(self) -> None:
        result = HookResult()
        assert result.decision == HookDecision.CONTINUE
        assert result.args is None
        assert result.reason == ""

    def test_custom_values(self) -> None:
        result = HookResult(
            decision=HookDecision.DENY,
            args={"modified": True},
            reason="not allowed",
        )
        assert result.decision == HookDecision.DENY
        assert result.args == {"modified": True}
        assert result.reason == "not allowed"


@pytest.mark.unit
class TestHookPriority:
    """Tests for HookPriority constants."""

    def test_ordering(self) -> None:
        assert HookPriority.SECURITY < HookPriority.VALIDATION
        assert HookPriority.VALIDATION < HookPriority.DEFAULT
        assert HookPriority.DEFAULT < HookPriority.LOGGING
        assert HookPriority.LOGGING < HookPriority.CLEANUP

    def test_values(self) -> None:
        assert HookPriority.SECURITY == 10
        assert HookPriority.VALIDATION == 50
        assert HookPriority.DEFAULT == 100
        assert HookPriority.LOGGING == 200
        assert HookPriority.CLEANUP == 500


@pytest.mark.unit
class TestToolHookRegistry:
    """Tests for ToolHookRegistry."""

    def test_empty_registry(self) -> None:
        registry = ToolHookRegistry()
        assert registry.before_hook_count == 0
        assert registry.after_hook_count == 0

    def test_register_before_hook(self) -> None:
        registry = ToolHookRegistry()
        hook = AsyncMock(return_value=HookResult())
        registry.register_before(hook, pattern="*", name="test_hook")

        assert registry.before_hook_count == 1

    def test_register_after_hook(self) -> None:
        registry = ToolHookRegistry()
        hook = AsyncMock(return_value=ToolResult(output="ok"))
        registry.register_after(hook, pattern="terminal*", name="logging")

        assert registry.after_hook_count == 1

    def test_clear_removes_all_hooks(self) -> None:
        registry = ToolHookRegistry()
        registry.register_before(AsyncMock(return_value=HookResult()))
        registry.register_after(AsyncMock(return_value=ToolResult(output="")))
        registry.clear()

        assert registry.before_hook_count == 0
        assert registry.after_hook_count == 0

    async def test_run_before_no_hooks_returns_continue(self) -> None:
        # Arrange
        registry = ToolHookRegistry()
        ctx = _make_ctx()

        # Act
        result = await registry.run_before("bash", {"cmd": "ls"}, ctx)

        # Assert
        assert result.decision == HookDecision.CONTINUE
        assert result.args == {"cmd": "ls"}

    async def test_run_before_continue_passes_args(self) -> None:
        registry = ToolHookRegistry()
        ctx = _make_ctx()

        async def modify_hook(tool_name: str, args: dict, ctx: ToolContext) -> HookResult:
            return HookResult(args={**args, "injected": True})

        registry.register_before(modify_hook)

        result = await registry.run_before("bash", {"cmd": "ls"}, ctx)
        assert result.decision == HookDecision.CONTINUE
        assert result.args == {"cmd": "ls", "injected": True}

    async def test_run_before_deny_stops_execution(self) -> None:
        registry = ToolHookRegistry()
        ctx = _make_ctx()
        second_hook = AsyncMock(return_value=HookResult())

        async def deny_hook(tool_name: str, args: dict, ctx: ToolContext) -> HookResult:
            return HookResult(decision=HookDecision.DENY, reason="blocked")

        registry.register_before(deny_hook, priority=HookPriority.SECURITY)
        registry.register_before(second_hook, priority=HookPriority.DEFAULT)

        result = await registry.run_before("bash", {}, ctx)
        assert result.decision == HookDecision.DENY
        assert result.reason == "blocked"
        second_hook.assert_not_called()

    async def test_run_before_ask_stops_execution(self) -> None:
        registry = ToolHookRegistry()
        ctx = _make_ctx()

        async def ask_hook(tool_name: str, args: dict, ctx: ToolContext) -> HookResult:
            return HookResult(decision=HookDecision.ASK, reason="needs approval")

        registry.register_before(ask_hook)

        result = await registry.run_before("bash", {}, ctx)
        assert result.decision == HookDecision.ASK

    async def test_run_before_pattern_filtering(self) -> None:
        registry = ToolHookRegistry()
        ctx = _make_ctx()

        hook = AsyncMock(return_value=HookResult(decision=HookDecision.DENY))
        registry.register_before(hook, pattern="mcp__*")

        # Should not match
        result = await registry.run_before("bash", {}, ctx)
        assert result.decision == HookDecision.CONTINUE
        hook.assert_not_called()

        # Should match
        result = await registry.run_before("mcp__server__tool", {}, ctx)
        assert result.decision == HookDecision.DENY

    async def test_run_before_priority_order(self) -> None:
        registry = ToolHookRegistry()
        ctx = _make_ctx()
        call_order: list[str] = []

        async def hook_a(tn: str, args: dict, ctx: ToolContext) -> HookResult:
            call_order.append("a")
            return HookResult()

        async def hook_b(tn: str, args: dict, ctx: ToolContext) -> HookResult:
            call_order.append("b")
            return HookResult()

        registry.register_before(hook_b, priority=HookPriority.LOGGING)
        registry.register_before(hook_a, priority=HookPriority.SECURITY)

        await registry.run_before("bash", {}, ctx)
        assert call_order == ["a", "b"]

    async def test_run_before_hook_exception_does_not_block(self) -> None:
        registry = ToolHookRegistry()
        ctx = _make_ctx()

        async def bad_hook(tn: str, args: dict, ctx: ToolContext) -> HookResult:
            raise RuntimeError("boom")

        registry.register_before(bad_hook)
        result = await registry.run_before("bash", {"cmd": "ls"}, ctx)
        assert result.decision == HookDecision.CONTINUE

    async def test_run_before_arg_modification_chaining(self) -> None:
        registry = ToolHookRegistry()
        ctx = _make_ctx()

        async def hook1(tn: str, args: dict, ctx: ToolContext) -> HookResult:
            return HookResult(args={**args, "step": 1})

        async def hook2(tn: str, args: dict, ctx: ToolContext) -> HookResult:
            return HookResult(args={**args, "step": args.get("step", 0) + 1})

        registry.register_before(hook1, priority=10)
        registry.register_before(hook2, priority=20)

        result = await registry.run_before("tool", {}, ctx)
        assert result.args == {"step": 2}

    async def test_run_after_no_hooks_returns_same_result(self) -> None:
        registry = ToolHookRegistry()
        ctx = _make_ctx()
        original = ToolResult(output="original")

        result = await registry.run_after("bash", original, ctx)
        assert result is original

    async def test_run_after_modifies_result(self) -> None:
        registry = ToolHookRegistry()
        ctx = _make_ctx()

        async def annotate(tool_name: str, result: ToolResult, ctx: ToolContext) -> ToolResult:
            return ToolResult(output=result.output + " [annotated]")

        registry.register_after(annotate)

        original = ToolResult(output="hello")
        result = await registry.run_after("bash", original, ctx)
        assert result.output == "hello [annotated]"

    async def test_run_after_pattern_filtering(self) -> None:
        registry = ToolHookRegistry()
        ctx = _make_ctx()

        hook = AsyncMock(return_value=ToolResult(output="modified"))
        registry.register_after(hook, pattern="terminal*")

        original = ToolResult(output="original")
        result = await registry.run_after("bash", original, ctx)
        assert result.output == "original"
        hook.assert_not_called()

    async def test_run_after_hook_exception_preserves_result(self) -> None:
        registry = ToolHookRegistry()
        ctx = _make_ctx()

        async def bad_hook(tn: str, result: ToolResult, ctx: ToolContext) -> ToolResult:
            raise RuntimeError("crash")

        registry.register_after(bad_hook)

        original = ToolResult(output="safe")
        result = await registry.run_after("bash", original, ctx)
        assert result.output == "safe"

    async def test_run_after_chaining(self) -> None:
        registry = ToolHookRegistry()
        ctx = _make_ctx()

        async def hook1(tn: str, r: ToolResult, ctx: ToolContext) -> ToolResult:
            return ToolResult(output=r.output + "-1")

        async def hook2(tn: str, r: ToolResult, ctx: ToolContext) -> ToolResult:
            return ToolResult(output=r.output + "-2")

        registry.register_after(hook1, priority=10)
        registry.register_after(hook2, priority=20)

        result = await registry.run_after("t", ToolResult(output="base"), ctx)
        assert result.output == "base-1-2"
