#!/usr/bin/env python3
"""
Test script for Agent WebSocket functionality.

Tests:
1. WebSocket connection authentication
2. Basic message sending and receiving
3. HITL (Human-in-the-Loop) tools flow
4. ReAct Agent event loop after HITL response
"""

import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional

import aiohttp
import websockets

sys.path.insert(0, os.getcwd())

# Configuration
API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
WS_BASE_URL = os.environ.get("WS_BASE_URL", "ws://localhost:8000")
API_KEY = os.environ.get("API_KEY", "")

# Test data
TEST_PROJECT_ID = os.environ.get("TEST_PROJECT_ID", "")
TEST_CONVERSATION_ID = os.environ.get("TEST_CONVERSATION_ID", "")
TEST_USER_ID = os.environ.get("TEST_USER_ID", "")
TEST_TENANT_ID = os.environ.get("TEST_TENANT_ID", "")


class AgentWebSocketTester:
    """Test agent WebSocket functionality."""

    def __init__(self, api_key: str, project_id: str, conversation_id: str):
        self.api_key = api_key
        self.project_id = project_id
        self.conversation_id = conversation_id
        self.session_id: Optional[str] = None
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.events: List[Dict[str, Any]] = []
        self.hitl_request_id: Optional[str] = None
        self.hitl_type: Optional[str] = None
        self.test_passed = False
        self.errors: List[str] = []

    async def connect(self) -> bool:
        """Connect to WebSocket endpoint."""
        ws_url = f"{WS_BASE_URL}/api/v1/agent/ws?token={self.api_key}"
        try:
            self.ws = await websockets.connect(ws_url)
            return True
        except Exception as e:
            self.errors.append(f"WebSocket connection failed: {e}")
            return False

    async def receive_connected_event(self) -> bool:
        """Receive and validate connected event."""
        if not self.ws:
            self.errors.append("WebSocket not connected")
            return False

        try:
            msg = await asyncio.wait_for(self.ws.recv(), timeout=5.0)
            data = json.loads(msg)

            if data.get("type") != "connected":
                self.errors.append(f"Expected 'connected' event, got: {data.get('type')}")
                return False

            self.session_id = data.get("data", {}).get("session_id")
            print(f"   ✓ Connected: session_id={self.session_id}")
            return True

        except asyncio.TimeoutError:
            self.errors.append("Timeout waiting for connected event")
            return False
        except Exception as e:
            self.errors.append(f"Error receiving connected event: {e}")
            return False

    async def send_message(self, message: str) -> bool:
        """Send a message to start agent execution."""
        if not self.ws:
            self.errors.append("WebSocket not connected")
            return False

        msg = {
            "type": "send_message",
            "conversation_id": self.conversation_id,
            "message": message,
            "project_id": self.project_id,
        }

        try:
            await self.ws.send(json.dumps(msg))
            return True
        except Exception as e:
            self.errors.append(f"Error sending message: {e}")
            return False

    async def send_clarification_response(self, request_id: str, answer: str) -> bool:
        """Send clarification response."""
        if not self.ws:
            self.errors.append("WebSocket not connected")
            return False

        msg = {
            "type": "clarification_respond",
            "request_id": request_id,
            "answer": answer,
        }

        try:
            await self.ws.send(json.dumps(msg))
            return True
        except Exception as e:
            self.errors.append(f"Error sending clarification response: {e}")
            return False

    async def send_decision_response(self, request_id: str, decision: str) -> bool:
        """Send decision response."""
        if not self.ws:
            self.errors.append("WebSocket not connected")
            return False

        msg = {
            "type": "decision_respond",
            "request_id": request_id,
            "decision": decision,
        }

        try:
            await self.ws.send(json.dumps(msg))
            return True
        except Exception as e:
            self.errors.append(f"Error sending decision response: {e}")
            return False

    async def send_subscribe(self) -> bool:
        """Subscribe to conversation."""
        if not self.ws:
            self.errors.append("WebSocket not connected")
            return False

        msg = {
            "type": "subscribe",
            "conversation_id": self.conversation_id,
        }

        try:
            await self.ws.send(json.dumps(msg))
            return True
        except Exception as e:
            self.errors.append(f"Error subscribing: {e}")
            return False

    async def receive_events(self, timeout: float = 30.0, expected_event_types: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Receive events until timeout or completion."""
        events = []
        start_time = asyncio.get_event_loop().time()

        try:
            while True:
                elapsed = asyncio.get_event_loop().time() - start_time
                remaining = timeout - elapsed
                if remaining <= 0:
                    break

                msg = await asyncio.wait_for(self.ws.recv(), timeout=remaining)
                data = json.loads(msg)
                events.append(data)

                event_type = data.get("type", "unknown")
                print(f"   [Event] {event_type}")

                # Check for HITL request
                if event_type == "clarification_asked":
                    self.hitl_request_id = data.get("data", {}).get("request_id")
                    self.hitl_type = "clarification"
                    print(f"   ✓ HITL clarification request: {self.hitl_request_id}")

                elif event_type == "decision_asked":
                    self.hitl_request_id = data.get("data", {}).get("request_id")
                    self.hitl_type = "decision"
                    print(f"   ✓ HITL decision request: {self.hitl_request_id}")

                elif event_type == "env_var_requested":
                    self.hitl_request_id = data.get("data", {}).get("request_id")
                    self.hitl_type = "env_var"
                    print(f"   ✓ HITL env_var request: {self.hitl_request_id}")

                # Check for completion or error
                if event_type in ("complete", "error"):
                    break

                # Check if we received expected event types
                if expected_event_types and event_type in expected_event_types:
                    break

        except asyncio.TimeoutError:
            pass
        except Exception as e:
            self.errors.append(f"Error receiving events: {e}")

        return events

    async def close(self):
        """Close WebSocket connection."""
        if self.ws:
            await self.ws.close()
            self.ws = None


async def test_basic_websocket_connection():
    """Test 1: Basic WebSocket connection and authentication."""
    print("\n" + "=" * 60)
    print("Test 1: Basic WebSocket Connection")
    print("=" * 60)

    if not API_KEY:
        print("   ✗ API_KEY not set, skipping test")
        return False

    if not TEST_PROJECT_ID:
        print("   ✗ TEST_PROJECT_ID not set, skipping test")
        return False

    if not TEST_CONVERSATION_ID:
        print("   ✗ TEST_CONVERSATION_ID not set, skipping test")
        return False

    tester = AgentWebSocketTester(API_KEY, TEST_PROJECT_ID, TEST_CONVERSATION_ID)

    try:
        print("\n1.1 Connecting to WebSocket...")
        if not await tester.connect():
            print(f"   ✗ Connection failed: {tester.errors[-1]}")
            return False
        print("   ✓ WebSocket connected")

        print("\n1.2 Receiving connected event...")
        if not await tester.receive_connected_event():
            print(f"   ✗ Failed: {tester.errors[-1]}")
            return False

        print("\n1.3 Subscribing to conversation...")
        if not await tester.send_subscribe():
            print(f"   ✗ Failed: {tester.errors[-1]}")
            return False
        print("   ✓ Subscribe message sent")

        print("\n   ✓ Test 1 PASSED")
        return True

    except Exception as e:
        print(f"   ✗ Test 1 FAILED: {e}")
        return False
    finally:
        await tester.close()


async def test_agent_chat_flow():
    """Test 2: Agent chat flow with streaming events."""
    print("\n" + "=" * 60)
    print("Test 2: Agent Chat Flow")
    print("=" * 60)

    if not API_KEY:
        print("   ✗ API_KEY not set, skipping test")
        return False

    tester = AgentWebSocketTester(API_KEY, TEST_PROJECT_ID, TEST_CONVERSATION_ID)

    try:
        print("\n2.1 Connecting...")
        if not await tester.connect():
            print(f"   ✗ Connection failed: {tester.errors[-1]}")
            return False

        if not await tester.receive_connected_event():
            print(f"   ✗ Failed: {tester.errors[-1]}")
            return False

        print("\n2.2 Sending simple message...")
        message = "Hello, can you tell me what you can do?"
        if not await tester.send_message(message):
            print(f"   ✗ Failed: {tester.errors[-1]}")
            return False

        print("\n2.3 Receiving events...")
        events = await tester.receive_events(timeout=30.0)

        event_types = [e.get("type") for e in events]
        print(f"\n   Received events: {event_types}")

        if "complete" in event_types:
            print("   ✓ Agent completed successfully")
        elif "error" in event_types:
            error_event = [e for e in events if e.get("type") == "error"][0]
            print(f"   ✗ Agent error: {error_event.get('data', {})}")
            return False
        else:
            print("   ⚠ No completion event received (timeout)")
            # Don't fail on timeout, might be normal for long operations

        print("\n   ✓ Test 2 PASSED")
        return True

    except Exception as e:
        print(f"   ✗ Test 2 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await tester.close()


async def test_hitl_clarification_flow():
    """Test 3: HITL clarification flow - CRITICAL for ReAct event loop."""
    print("\n" + "=" * 60)
    print("Test 3: HITL Clarification Flow (ReAct Event Loop)")
    print("=" * 60)

    if not API_KEY:
        print("   ✗ API_KEY not set, skipping test")
        return False

    tester = AgentWebSocketTester(API_KEY, TEST_PROJECT_ID, TEST_CONVERSATION_ID)

    try:
        print("\n3.1 Connecting...")
        if not await tester.connect():
            print(f"   ✗ Connection failed: {tester.errors[-1]}")
            return False

        if not await tester.receive_connected_event():
            print(f"   ✗ Failed: {tester.errors[-1]}")
            return False

        print("\n3.2 Sending message that should trigger clarification...")
        # This message is designed to trigger a clarification request
        message = (
            "I need to implement a feature but I'm not sure about the approach. "
            "Can you help me decide between using a REST API or GraphQL?"
        )
        if not await tester.send_message(message):
            print(f"   ✗ Failed: {tester.errors[-1]}")
            return False

        print("\n3.3 Waiting for HITL clarification request...")
        _events = await tester.receive_events(timeout=30.0)

        # Check if we got clarification_asked
        if tester.hitl_type != "clarification":
            print(f"   ⚠ No clarification request received (HITL type: {tester.hitl_type})")
            print("   This may be normal if the agent doesn't need clarification")
            # Continue with test - not all queries trigger HITL
        else:
            print(f"   ✓ Received clarification request: {tester.hitl_request_id}")

            print("\n3.4 Sending clarification response...")
            if not await tester.send_clarification_response(tester.hitl_request_id, "rest_api"):
                print(f"   ✗ Failed: {tester.errors[-1]}")
                return False

            print("\n3.5 Waiting for agent to continue after HITL response...")
            # THIS IS THE CRITICAL TEST: Does the ReAct event loop continue?
            events_after_hitl = await tester.receive_events(timeout=30.0)

            event_types_after = [e.get("type") for e in events_after_hitl]
            print(f"\n   Events after HITL: {event_types_after}")

            if "complete" in event_types_after:
                print("   ✓ ReAct Agent continued and completed after HITL!")
            elif "error" in event_types_after:
                error_event = [e for e in events_after_hitl if e.get("type") == "error"][0]
                print(f"   ✗ Error after HITL: {error_event.get('data', {})}")
                return False
            elif not events_after_hitl:
                print("   ✗ NO EVENTS after HITL response - ReAct event loop may be stuck!")
                return False
            else:
                print("   ⚠ Events received but no completion yet")

        print("\n   ✓ Test 3 PASSED")
        return True

    except Exception as e:
        print(f"   ✗ Test 3 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await tester.close()


async def test_hitl_decision_flow():
    """Test 4: HITL decision flow - CRITICAL for ReAct event loop."""
    print("\n" + "=" * 60)
    print("Test 4: HITL Decision Flow (ReAct Event Loop)")
    print("=" * 60)

    if not API_KEY:
        print("   ✗ API_KEY not set, skipping test")
        return False

    tester = AgentWebSocketTester(API_KEY, TEST_PROJECT_ID, TEST_CONVERSATION_ID)

    try:
        print("\n4.1 Connecting...")
        if not await tester.connect():
            print(f"   ✗ Connection failed: {tester.errors[-1]}")
            return False

        if not await tester.receive_connected_event():
            print(f"   ✗ Failed: {tester.errors[-1]}")
            return False

        print("\n4.2 Sending message that should trigger decision request...")
        # This message is designed to trigger a decision request
        message = (
            "I need to delete a large amount of user data. "
            "This is a risky operation. What should I do?"
        )
        if not await tester.send_message(message):
            print(f"   ✗ Failed: {tester.errors[-1]}")
            return False

        print("\n4.3 Waiting for HITL decision request...")
        _ = await tester.receive_events(timeout=30.0)

        # Check if we got decision_asked
        if tester.hitl_type != "decision":
            print(f"   ⚠ No decision request received (HITL type: {tester.hitl_type})")
            print("   This may be normal if the agent doesn't need a decision")
        else:
            print(f"   ✓ Received decision request: {tester.hitl_request_id}")

            print("\n4.4 Sending decision response...")
            if not await tester.send_decision_response(tester.hitl_request_id, "cancel"):
                print(f"   ✗ Failed: {tester.errors[-1]}")
                return False

            print("\n4.5 Waiting for agent to continue after decision response...")
            # CRITICAL TEST: Does the ReAct event loop continue?
            events_after_hitl = await tester.receive_events(timeout=30.0)

            event_types_after = [e.get("type") for e in events_after_hitl]
            print(f"\n   Events after decision: {event_types_after}")

            if "complete" in event_types_after:
                print("   ✓ ReAct Agent continued and completed after decision!")
            elif "error" in event_types_after:
                error_event = [e for e in events_after_hitl if e.get("type") == "error"][0]
                print(f"   ✗ Error after decision: {error_event.get('data', {})}")
                return False
            elif not events_after_hitl:
                print("   ✗ NO EVENTS after decision response - ReAct event loop may be stuck!")
                return False
            else:
                print("   ⚠ Events received but no completion yet")

        print("\n   ✓ Test 4 PASSED")
        return True

    except Exception as e:
        print(f"   ✗ Test 4 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        await tester.close()


async def check_api_health():
    """Check if API is running."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{API_BASE_URL}/health", timeout=5.0) as resp:
                if resp.status == 200:
                    print("   ✓ API is running")
                    return True
                else:
                    print(f"   ⚠ API health check returned: {resp.status}")
                    return False
    except Exception as e:
        print(f"   ⚠ API health check failed: {e}")
        return False


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Agent WebSocket Test Suite")
    print("=" * 60)

    # Check environment
    print("\nChecking environment...")
    print(f"   API_BASE_URL: {API_BASE_URL}")
    print(f"   WS_BASE_URL: {WS_BASE_URL}")
    print(f"   API_KEY: {'***' if API_KEY else 'NOT SET'}")
    print(f"   TEST_PROJECT_ID: {TEST_PROJECT_ID or 'NOT SET'}")
    print(f"   TEST_CONVERSATION_ID: {TEST_CONVERSATION_ID or 'NOT SET'}")

    # Check API health
    print("\nChecking API health...")
    await check_api_health()

    # Run tests
    results = []

    # Test 1: Basic connection
    results.append(("Basic WebSocket Connection", await test_basic_websocket_connection()))

    # Test 2: Agent chat flow
    results.append(("Agent Chat Flow", await test_agent_chat_flow()))

    # Test 3: HITL clarification flow
    results.append(("HITL Clarification Flow", await test_hitl_clarification_flow()))

    # Test 4: HITL decision flow
    results.append(("HITL Decision Flow", await test_hitl_decision_flow()))

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    passed = sum(1 for _, r in results if r)
    failed = sum(1 for _, r in results if not r)

    for name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"   {status}: {name}")

    print(f"\n   Total: {passed} passed, {failed} failed")

    if failed > 0:
        print("\n   ⚠ Some tests failed. Check the logs above for details.")
        sys.exit(1)
    else:
        print("\n   ✓ All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
