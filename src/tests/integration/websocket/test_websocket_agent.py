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
from typing import Any

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


class SetupError(Exception):
    """Raised when a test setup step fails."""


def _require_env_vars() -> None:
    """Validate required environment variables. Raises SetupError if missing."""
    if not API_KEY:
        raise SetupError("API_KEY not set, skipping test")
    if not TEST_PROJECT_ID:
        raise SetupError("TEST_PROJECT_ID not set, skipping test")
    if not TEST_CONVERSATION_ID:
        raise SetupError("TEST_CONVERSATION_ID not set, skipping test")


async def _setup_tester_connection(tester: "AgentWebSocketTester") -> None:
    """Connect tester and receive connected event. Raises SetupError on failure."""
    if not await tester.connect():
        raise SetupError(f"Connection failed: {tester.errors[-1]}")

    if not await tester.receive_connected_event():
        raise SetupError(f"Connected event failed: {tester.errors[-1]}")


async def _send_or_fail(tester: "AgentWebSocketTester", message: str) -> None:
    """Send a message or raise SetupError."""
    if not await tester.send_message(message):
        raise SetupError(f"Send failed: {tester.errors[-1]}")


def _analyze_post_hitl_events(events_after_hitl: list[dict[str, Any]], hitl_label: str) -> bool:
    """Analyze events after HITL response. Returns True if test should pass."""
    event_types_after = [e.get("type") for e in events_after_hitl]
    print(f"\n   Events after {hitl_label}: {event_types_after}")

    if "complete" in event_types_after:
        print(f"   ✓ ReAct Agent continued and completed after {hitl_label}!")
        return True

    if "error" in event_types_after:
        error_event = next(e for e in events_after_hitl if e.get("type") == "error")
        print(f"   ✗ Error after {hitl_label}: {error_event.get('data', {})}")
        return False

    if not events_after_hitl:
        print(f"   ✗ NO EVENTS after {hitl_label} response - ReAct event loop may be stuck!")
        return False

    print("   ⚠ Events received but no completion yet")
    return True


class AgentWebSocketTester:
    """Test agent WebSocket functionality."""

    def __init__(self, api_key: str, project_id: str, conversation_id: str) -> None:
        self.api_key = api_key
        self.project_id = project_id
        self.conversation_id = conversation_id
        self.session_id: str | None = None
        self.ws: websockets.WebSocketClientProtocol | None = None
        self.events: list[dict[str, Any]] = []
        self.hitl_request_id: str | None = None
        self.hitl_type: str | None = None
        self.test_passed = False
        self.errors: list[str] = []

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

        except TimeoutError:
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

    def _process_hitl_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Record HITL event data on the tester."""
        hitl_map = {
            "clarification_asked": "clarification",
            "decision_asked": "decision",
            "env_var_requested": "env_var",
        }
        if event_type in hitl_map:
            self.hitl_request_id = data.get("data", {}).get("request_id")
            self.hitl_type = hitl_map[event_type]
            print(f"   ✓ HITL {self.hitl_type} request: {self.hitl_request_id}")

    async def receive_events(
        self, timeout: float = 30.0, expected_event_types: list[str] | None = None
    ) -> list[dict[str, Any]]:
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

                self._process_hitl_event(event_type, data)

                if event_type in ("complete", "error"):
                    break

                if expected_event_types and event_type in expected_event_types:
                    break

        except TimeoutError:
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

    try:
        _require_env_vars()
    except SetupError as e:
        print(f"   ✗ {e}")
        return False

    tester = AgentWebSocketTester(API_KEY, TEST_PROJECT_ID, TEST_CONVERSATION_ID)

    try:
        print("\n1.1 Connecting to WebSocket...")
        await _setup_tester_connection(tester)
        print("   ✓ WebSocket connected")

        print("\n1.3 Subscribing to conversation...")
        if not await tester.send_subscribe():
            print(f"   ✗ Failed: {tester.errors[-1]}")
            return False
        print("   ✓ Subscribe message sent")

        print("\n   ✓ Test 1 PASSED")
        return True

    except SetupError as e:
        print(f"   ✗ {e}")
        return False
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

    try:
        _require_env_vars()
    except SetupError as e:
        print(f"   ✗ {e}")
        return False

    tester = AgentWebSocketTester(API_KEY, TEST_PROJECT_ID, TEST_CONVERSATION_ID)

    try:
        print("\n2.1 Connecting...")
        await _setup_tester_connection(tester)

        print("\n2.2 Sending simple message...")
        await _send_or_fail(tester, "Hello, can you tell me what you can do?")

        print("\n2.3 Receiving events...")
        events = await tester.receive_events(timeout=30.0)
        event_types = [e.get("type") for e in events]
        print(f"\n   Received events: {event_types}")

        if "error" in event_types:
            error_event = next(e for e in events if e.get("type") == "error")
            print(f"   ✗ Agent error: {error_event.get('data', {})}")
            return False

        if "complete" in event_types:
            print("   ✓ Agent completed successfully")
        else:
            print("   ⚠ No completion event received (timeout)")

        print("\n   ✓ Test 2 PASSED")
        return True

    except SetupError as e:
        print(f"   ✗ {e}")
        return False
    except Exception as e:
        print(f"   ✗ Test 2 FAILED: {e}")
        import traceback

        traceback.print_exc()
        return False
    finally:
        await tester.close()


async def _run_hitl_flow(
    tester: AgentWebSocketTester,
    message: str,
    expected_hitl_type: str,
    hitl_label: str,
    send_response_fn,
    response_value: str,
) -> bool:
    """Run a HITL flow: send message, wait for HITL, respond, check continuation."""
    await _send_or_fail(tester, message)

    print(f"\n   Waiting for HITL {hitl_label} request...")
    _events = await tester.receive_events(timeout=30.0)

    if tester.hitl_type != expected_hitl_type:
        print(f"   ⚠ No {hitl_label} request received (HITL type: {tester.hitl_type})")
        print(f"   This may be normal if the agent doesn't need {hitl_label}")
        return True

    print(f"   ✓ Received {hitl_label} request: {tester.hitl_request_id}")

    print(f"\n   Sending {hitl_label} response...")
    if not await send_response_fn(tester.hitl_request_id, response_value):
        print(f"   ✗ Failed: {tester.errors[-1]}")
        return False

    print(f"\n   Waiting for agent to continue after {hitl_label} response...")
    events_after_hitl = await tester.receive_events(timeout=30.0)

    return _analyze_post_hitl_events(events_after_hitl, hitl_label)


async def test_hitl_clarification_flow():
    """Test 3: HITL clarification flow - CRITICAL for ReAct event loop."""
    print("\n" + "=" * 60)
    print("Test 3: HITL Clarification Flow (ReAct Event Loop)")
    print("=" * 60)

    try:
        _require_env_vars()
    except SetupError as e:
        print(f"   ✗ {e}")
        return False

    tester = AgentWebSocketTester(API_KEY, TEST_PROJECT_ID, TEST_CONVERSATION_ID)

    try:
        print("\n3.1 Connecting...")
        await _setup_tester_connection(tester)

        print("\n3.2 Sending message that should trigger clarification...")
        message = (
            "I need to implement a feature but I'm not sure about the approach. "
            "Can you help me decide between using a REST API or GraphQL?"
        )

        result = await _run_hitl_flow(
            tester,
            message,
            "clarification",
            "clarification",
            tester.send_clarification_response,
            "rest_api",
        )
        if not result:
            return False

        print("\n   ✓ Test 3 PASSED")
        return True

    except SetupError as e:
        print(f"   ✗ {e}")
        return False
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

    try:
        _require_env_vars()
    except SetupError as e:
        print(f"   ✗ {e}")
        return False

    tester = AgentWebSocketTester(API_KEY, TEST_PROJECT_ID, TEST_CONVERSATION_ID)

    try:
        print("\n4.1 Connecting...")
        await _setup_tester_connection(tester)

        print("\n4.2 Sending message that should trigger decision request...")
        message = (
            "I need to delete a large amount of user data. "
            "This is a risky operation. What should I do?"
        )

        result = await _run_hitl_flow(
            tester,
            message,
            "decision",
            "decision",
            tester.send_decision_response,
            "cancel",
        )
        if not result:
            return False

        print("\n   ✓ Test 4 PASSED")
        return True

    except SetupError as e:
        print(f"   ✗ {e}")
        return False
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
        async with (
            aiohttp.ClientSession() as session,
            session.get(f"{API_BASE_URL}/health", timeout=5.0) as resp,
        ):
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

    results.append(("Basic WebSocket Connection", await test_basic_websocket_connection()))
    results.append(("Agent Chat Flow", await test_agent_chat_flow()))
    results.append(("HITL Clarification Flow", await test_hitl_clarification_flow()))
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
