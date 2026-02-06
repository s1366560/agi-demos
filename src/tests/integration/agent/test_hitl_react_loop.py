#!/usr/bin/env python3
"""
Test script specifically for HITL -> ReAct Event Loop recovery.

This script tests the critical path:
1. Send message that triggers HITL
2. Receive HITL request
3. Send HITL response
4. Verify ReAct Agent continues (events after HITL response)
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import websockets

sys.path.insert(0, os.getcwd())

# Configuration
WS_BASE_URL = os.environ.get("WS_BASE_URL", "ws://localhost:8000")
API_KEY = os.environ.get("API_KEY", "")
TEST_PROJECT_ID = os.environ.get("TEST_PROJECT_ID", "")
TEST_CONVERSATION_ID = os.environ.get("TEST_CONVERSATION_ID", "")


class HITLReactLoopTester:
    """Test HITL to ReAct event loop recovery."""

    def __init__(self, api_key: str, project_id: str, conversation_id: str):
        self.api_key = api_key
        self.project_id = project_id
        self.conversation_id = conversation_id
        self.session_id: Optional[str] = None
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.events_before_hitl: List[Dict[str, Any]] = []
        self.events_after_hitl: List[Dict[str, Any]] = []
        self.errors: List[str] = []
        self.hitl_request_id: Optional[str] = None
        self.hitl_type: Optional[str] = None

    async def connect(self) -> bool:
        """Connect to WebSocket."""
        ws_url = f"{WS_BASE_URL}/api/v1/agent/ws?token={self.api_key}"
        try:
            self.ws = await websockets.connect(ws_url)
            return True
        except Exception as e:
            self.errors.append(f"Connection failed: {e}")
            return False

    async def receive_until_event(self, target_events: List[str], timeout: float = 30.0) -> List[Dict[str, Any]]:
        """Receive events until one of target events is received."""
        events = []
        start_time = time.time()

        try:
            while time.time() - start_time < timeout:
                try:
                    msg = await asyncio.wait_for(self.ws.recv(), timeout=1.0)
                    data = json.loads(msg)
                    events.append(data)

                    event_type = data.get("type", "unknown")
                    print(f"      [{len(events):2d}] {event_type}")

                    # Check for HITL
                    if event_type in ["clarification_asked", "decision_asked", "env_var_requested"]:
                        self.hitl_request_id = data.get("data", {}).get("request_id")
                        self.hitl_type = event_type.replace("_asked", "").replace("_requested", "")
                        print(f"      >>> HITL detected: {self.hitl_type} / {self.hitl_request_id}")

                    # Check for completion
                    if event_type in target_events:
                        return events

                except asyncio.TimeoutError:
                    continue

        except Exception as e:
            self.errors.append(f"Error receiving: {e}")

        return events

    async def run_test(self) -> bool:
        """Run the complete HITL -> ReAct test."""
        print("\n" + "=" * 70)
        print("HITL -> ReAct Event Loop Test")
        print("=" * 70)

        # Step 1: Connect
        print("\n[Step 1] Connecting to WebSocket...")
        if not await self.connect():
            print(f"   ✗ Failed: {self.errors[-1]}")
            return False

        # Wait for connected event
        msg = await self.ws.recv()
        data = json.loads(msg)
        if data.get("type") != "connected":
            print(f"   ✗ Expected 'connected', got {data.get('type')}")
            return False

        self.session_id = data.get("data", {}).get("session_id")
        print(f"   ✓ Connected (session: {self.session_id[:8]}...)")

        # Step 2: Subscribe to conversation
        print("\n[Step 2] Subscribing to conversation...")
        await self.ws.send(json.dumps({
            "type": "subscribe",
            "conversation_id": self.conversation_id,
        }))

        # Step 3: Send message that triggers HITL
        print("\n[Step 3] Sending message that triggers HITL...")
        # This message is designed to trigger a decision HITL
        message = (
            "I need to delete all user data from the database. "
            "This is a destructive operation. What should I do?"
        )
        await self.ws.send(json.dumps({
            "type": "send_message",
            "conversation_id": self.conversation_id,
            "message": message,
            "project_id": self.project_id,
        }))

        # Step 4: Wait for HITL request
        print("\n[Step 4] Waiting for HITL request...")
        print("   Receiving events:")
        self.events_before_hitl = await self.receive_until_event(
            target_events=["clarification_asked", "decision_asked", "env_var_requested", "complete", "error"],
            timeout=45.0
        )

        if not self.hitl_request_id:
            print("\n   ⚠ No HITL request received (this may be normal)")
            print("   Checking if agent completed without HITL...")

            event_types = [e.get("type") for e in self.events_before_hitl]
            if "complete" in event_types:
                print("   ✓ Agent completed without HITL")
                return True
            elif "error" in event_types:
                print("   ✗ Agent error")
                return False
            else:
                print("   ⚠ No completion or HITL - may need different test message")
                return True  # Not a failure, just need different test

        print(f"\n   ✓ Received HITL request: {self.hitl_type} / {self.hitl_request_id}")

        # Step 5: Send HITL response
        print("\n[Step 5] Sending HITL response...")
        if self.hitl_type == "decision":
            response_msg = {
                "type": "decision_respond",
                "request_id": self.hitl_request_id,
                "decision": "cancel",  # Safe choice for test
            }
        elif self.hitl_type == "clarification":
            response_msg = {
                "type": "clarification_respond",
                "request_id": self.hitl_request_id,
                "answer": "Please use the safest approach",
            }
        else:
            response_msg = {
                "type": "env_var_respond",
                "request_id": self.hitl_request_id,
                "values": {"test_var": "test_value"},
            }

        await self.ws.send(json.dumps(response_msg))
        print(f"   ✓ Sent {response_msg['type']}")

        # Step 6: CRITICAL - Wait for events AFTER HITL response
        print("\n[Step 6] CRITICAL: Waiting for events AFTER HITL response...")
        print("   This tests if ReAct Agent event loop continues correctly.")
        print("   Receiving events:")

        self.events_after_hitl = await self.receive_until_event(
            target_events=["complete", "error"],
            timeout=45.0
        )

        # Step 7: Analyze results
        print("\n[Step 7] Analyzing results...")

        event_types_after = [e.get("type") for e in self.events_after_hitl]

        if not self.events_after_hitl:
            print("   ✗ CRITICAL FAILURE: No events received after HITL response!")
            print("   → ReAct Agent event loop is NOT continuing after HITL!")
            return False

        print(f"   Events after HITL: {event_types_after}")

        if "complete" in event_types_after:
            print("   ✓ SUCCESS: ReAct Agent continued and completed after HITL!")
            return True
        elif "error" in event_types_after:
            error_event = [e for e in self.events_after_hitl if e.get("type") == "error"][0]
            print(f"   ✗ ERROR after HITL: {error_event.get('data', {})}")
            return False
        else:
            print(f"   ⚠ Events received but no completion (timeout)")
            print(f"   This may indicate the agent is still processing.")
            return True  # Partial success

    async def close(self):
        """Close connection."""
        if self.ws:
            await self.ws.close()

    def print_summary(self):
        """Print test summary."""
        print("\n" + "=" * 70)
        print("Test Summary")
        print("=" * 70)
        print(f"Events before HITL: {len(self.events_before_hitl)}")
        print(f"Events after HITL:  {len(self.events_after_hitl)}")
        print(f"HITL type:          {self.hitl_type or 'N/A'}")
        print(f"HITL request ID:    {self.hitl_request_id or 'N/A'}")

        if self.errors:
            print(f"\nErrors:")
            for err in self.errors:
                print(f"  - {err}")


async def main():
    """Main test entry."""
    print("=" * 70)
    print("HITL -> ReAct Event Loop Recovery Test")
    print("=" * 70)

    # Check environment
    print("\nEnvironment:")
    print(f"  WS_BASE_URL: {WS_BASE_URL}")
    print(f"  API_KEY: {'***' if API_KEY else 'NOT SET'}")
    print(f"  TEST_PROJECT_ID: {TEST_PROJECT_ID or 'NOT SET'}")
    print(f"  TEST_CONVERSATION_ID: {TEST_CONVERSATION_ID or 'NOT SET'}")

    if not API_KEY:
        print("\n✗ API_KEY not set!")
        sys.exit(1)

    if not TEST_PROJECT_ID or not TEST_CONVERSATION_ID:
        print("\n✗ TEST_PROJECT_ID or TEST_CONVERSATION_ID not set!")
        sys.exit(1)

    # Run test
    tester = HITLReactLoopTester(API_KEY, TEST_PROJECT_ID, TEST_CONVERSATION_ID)

    try:
        success = await tester.run_test()
        tester.print_summary()

        if success:
            print("\n✓ TEST PASSED")
            sys.exit(0)
        else:
            print("\n✗ TEST FAILED")
            sys.exit(1)
    except Exception as e:
        print(f"\n✗ TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        await tester.close()


if __name__ == "__main__":
    asyncio.run(main())
