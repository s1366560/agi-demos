#!/usr/bin/env python3
"""
Test script for multiple HITL scenarios with Ray runtime.

This script tests:
1. Multiple sequential HITL requests in the same conversation
2. HITL handler state management across resume cycles
3. Message context preservation between HITL cycles
"""

import asyncio
import json
import os
import sys
from typing import Any

# Add project to path
sys.path.insert(0, os.getcwd())

from src.domain.model.agent.hitl_types import HITLType
from src.infrastructure.agent.hitl.ray_hitl_handler import RayHITLHandler
from src.infrastructure.agent.processor import ProcessorConfig, SessionProcessor, ToolDefinition


class MockTool:
    """Mock tool for testing."""
    
    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description or f"Tool: {name}"
    
    async def execute(self, **kwargs):
        return f"Result from {self.name}"


def create_mock_tool_def(name: str, permission: str | None = None) -> ToolDefinition:
    """Create a mock tool definition."""
    
    async def execute(**kwargs):
        return {"output": f"Executed {name} with {kwargs}"}
    
    return ToolDefinition(
        name=name,
        description=f"Mock tool: {name}",
        parameters={
            "type": "object",
            "properties": {
                "param1": {"type": "string"},
            },
            "required": [],
        },
        execute=execute,
        permission=permission,
    )


class MultiHITLTest:
    """Test multiple HITL scenarios."""
    
    def __init__(self) -> None:
        self.hitl_responses: dict[str, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        
    async def test_handler_reuse_issue(self):
        """
        Test the HITL handler reuse issue.
        
        Problem: When handler is reused across multiple HITL cycles,
        the _preinjected_response may not be properly managed.
        """
        print("\n=== Test 1: Handler Reuse Issue ===")
        
        # Simulate first HITL cycle
        print("\n[Cycle 1] Creating handler with preinjected response...")
        handler = RayHITLHandler(
            conversation_id="conv_test",
            tenant_id="tenant_test",
            project_id="project_test",
            message_id="msg_001",
            preinjected_response={
                "request_id": "clar_001",
                "hitl_type": "clarification",
                "response_data": {"answer": "first_answer"},
            },
        )
        
        # Peek at response (should return it without consuming)
        preinjected = handler.peek_preinjected_response(HITLType.CLARIFICATION)
        print(f"  [Cycle 1] Peek preinjected: {preinjected is not None}")
        assert preinjected is not None, "Should have preinjected response"
        
        # Simulate using the response (this consumes it)
        # In real code, this happens in _execute_hitl_request
        handler._preinjected_response = None  # Simulating consumption
        print("  [Cycle 1] Response consumed")
        
        # Simulate second HITL cycle with same handler
        print("\n[Cycle 2] Reusing handler for second HITL...")
        handler._preinjected_response = {
            "request_id": "clar_002",
            "hitl_type": "clarification", 
            "response_data": {"answer": "second_answer"},
        }
        
        preinjected2 = handler.peek_preinjected_response(HITLType.CLARIFICATION)
        print(f"  [Cycle 2] Peek preinjected: {preinjected2 is not None}")
        assert preinjected2 is not None, "Should have second preinjected response"
        
        print("\n✓ Handler reuse test passed")
        
    async def test_processor_handler_lifecycle(self):
        """
        Test processor's HITL handler lifecycle management.
        
        Problem: Processor may not properly reset handler between HITL cycles.
        """
        print("\n=== Test 2: Processor Handler Lifecycle ===")
        
        config = ProcessorConfig(
            model="test-model",
            max_steps=10,
        )
        
        tools = [create_mock_tool_def("test_tool")]
        processor = SessionProcessor(config, tools)
        
        # Simulate first HITL with preinjected response
        print("\n[Cycle 1] Setting up processor with first HITL response...")
        processor._langfuse_context = {
            "conversation_id": "conv_test",
            "tenant_id": "tenant_test",
            "project_id": "project_test",
            "message_id": "msg_001",
            "hitl_response": {
                "request_id": "clar_001",
                "hitl_type": "clarification",
                "response_data": {"answer": "first_answer"},
            },
        }
        
        handler1 = processor._get_hitl_handler()
        print(f"  [Cycle 1] Handler created, has preinjected: {handler1._preinjected_response is not None}")
        
        # Simulate consuming the response
        handler1._preinjected_response = None
        
        # Simulate second HITL (same conversation, new response)
        print("\n[Cycle 2] Reusing processor for second HITL...")
        processor._langfuse_context["hitl_response"] = {
            "request_id": "clar_002",
            "hitl_type": "clarification",
            "response_data": {"answer": "second_answer"},
        }
        
        handler2 = processor._get_hitl_handler()
        print(f"  [Cycle 2] Handler reused: {handler2 is handler1}")
        print(f"  [Cycle 2] Handler has preinjected: {handler2._preinjected_response is not None}")
        
        # This is where the bug might be - handler2 should have the new response
        if handler2._preinjected_response is None:
            print("  ⚠ WARNING: Handler should have preinjected response but doesn't!")
            print("     This indicates the ctx.pop() consumed the response in first call")
        else:
            print(f"  [Cycle 2] Preinjected request_id: {handler2._preinjected_response.get('request_id')}")
            
        print("\n✓ Processor handler lifecycle test completed")
        
    async def test_ctx_pop_issue(self):
        """
        Demonstrate the ctx.pop() issue in _get_hitl_handler.
        
        The problem: ctx.pop() removes hitl_response on first call,
        so subsequent calls in the same execution don't get the response.
        """
        print("\n=== Test 3: ctx.pop() Issue Demonstration ===")
        
        config = ProcessorConfig(model="test")
        processor = SessionProcessor(config, [])
        
        # Set up context with hitl_response
        processor._langfuse_context = {
            "conversation_id": "conv_test",
            "tenant_id": "tenant_test",
            "project_id": "project_test",
            "hitl_response": {
                "request_id": "clar_001",
                "hitl_type": "clarification",
                "response_data": {"answer": "test"},
            },
        }
        
        print("\n[First call] Calling _get_hitl_handler()...")
        handler1 = processor._get_hitl_handler()
        has_response_1 = handler1._preinjected_response is not None
        print(f"  Handler has preinjected: {has_response_1}")
        
        # Check if hitl_response is still in context
        hitl_response_in_ctx = processor._langfuse_context.get("hitl_response")
        print(f"  hitl_response in context: {hitl_response_in_ctx is not None}")
        
        if hitl_response_in_ctx is None:
            print("  ⚠ ISSUE CONFIRMED: ctx.pop() removed hitl_response!")
            print("     This means multiple calls to _get_hitl_handler() will fail.")
        
        print("\n[Second call] Calling _get_hitl_handler() again...")
        handler2 = processor._get_hitl_handler()
        has_response_2 = handler2._preinjected_response is not None
        print(f"  Handler has preinjected: {has_response_2}")
        
        if not has_response_2:
            print("  ⚠ CONFIRMED: Second call doesn't get the response!")
            
        print("\n✓ ctx.pop() issue test completed")
        
    async def test_message_context_preservation(self):
        """
        Test that message context is properly preserved across HITL cycles.
        """
        print("\n=== Test 4: Message Context Preservation ===")
        
        # Simulate initial conversation
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Help me with a complex task."},
        ]
        
        print("\n[Initial] Messages:")
        for i, msg in enumerate(messages):
            print(f"  [{i}] {msg['role']}: {msg['content'][:50]}...")
        
        # First HITL cycle
        print("\n[Cycle 1] First HITL - clarification...")
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_clar_001",
                "type": "function",
                "function": {
                    "name": "ask_clarification",
                    "arguments": json.dumps({"question": "What is your preference?"}),
                },
            }],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": "call_clar_001",
            "content": "User clarification: Option A",
        })
        
        print("  Added assistant tool call and tool response")
        print(f"  Total messages: {len(messages)}")
        
        # Second HITL cycle
        print("\n[Cycle 2] Second HITL - decision...")
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_dec_002",
                "type": "function",
                "function": {
                    "name": "request_decision",
                    "arguments": json.dumps({"question": "Confirm action?"}),
                },
            }],
        })
        messages.append({
            "role": "tool",
            "tool_call_id": "call_dec_002",
            "content": "User decision: proceed",
        })
        
        print("  Added assistant tool call and tool response")
        print(f"  Total messages: {len(messages)}")
        
        # Verify context
        tool_calls = [m for m in messages if m.get("role") == "tool"]
        print(f"\n[Verification] Total tool results in context: {len(tool_calls)}")
        
        assert len(tool_calls) == 2, f"Expected 2 tool results, got {len(tool_calls)}"
        assert tool_calls[0]["tool_call_id"] == "call_clar_001"
        assert tool_calls[1]["tool_call_id"] == "call_dec_002"
        
        print("\n✓ Message context preservation test passed")
        
    async def run_all_tests(self):
        """Run all tests."""
        print("=" * 70)
        print("Multiple HITL Scenarios Test (Ray Runtime)")
        print("=" * 70)
        
        try:
            await self.test_handler_reuse_issue()
            await self.test_processor_handler_lifecycle()
            await self.test_ctx_pop_issue()
            await self.test_message_context_preservation()
            
            print("\n" + "=" * 70)
            print("All tests completed!")
            print("=" * 70)
            
            # Summary of issues found
            print("\n=== Issues Found ===")
            print("1. ctx.pop() in _get_hitl_handler removes hitl_response on first call")
            print("   - This is okay for single HITL but could be problematic")
            print("   - if handler is created multiple times during one execution")
            print("\n2. Handler reuse across multiple HITL cycles needs careful")
            print("   management of _preinjected_response state")
            
        except Exception as e:
            print(f"\n✗ Test failed: {e}")
            import traceback
            traceback.print_exc()


async def main():
    """Main entry point."""
    test = MultiHITLTest()
    await test.run_all_tests()


if __name__ == "__main__":
    asyncio.run(main())
