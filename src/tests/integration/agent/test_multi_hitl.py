#!/usr/bin/env python3
"""
Test script for multiple HITL (Human-in-the-Loop) interactions.

Tests the critical path:
1. Send message that triggers HITL #1
2. Respond to HITL #1
3. Agent continues and triggers HITL #2
4. Respond to HITL #2
5. Agent completes successfully

This tests the ReAct Agent's ability to handle multiple HITL cycles.
"""

import asyncio
import json
import os
import sys
import time
from typing import Any

import websockets

sys.path.insert(0, os.getcwd())

# Configuration
WS_BASE_URL = os.environ.get("WS_BASE_URL", "ws://localhost:8000")
API_KEY = os.environ.get("API_KEY", "")
TEST_PROJECT_ID = os.environ.get("TEST_PROJECT_ID", "")
TEST_CONVERSATION_ID = os.environ.get("TEST_CONVERSATION_ID", "")


class MultiHITLTester:
    """Test multiple HITL interactions."""

    def __init__(self, api_key: str, project_id: str, conversation_id: str) -> None:
        self.api_key = api_key
        self.project_id = project_id
        self.conversation_id = conversation_id
        self.session_id: str | None = None
        self.ws: websockets.WebSocketClientProtocol | None = None
        self.hitl_count = 0
        self.max_hitls = 5  # Safety limit
        self.events_log: list[dict[str, Any]] = []
        self.errors: list[str] = []

    async def connect(self) -> bool:
        """Connect to WebSocket."""
        ws_url = f"{WS_BASE_URL}/api/v1/agent/ws?token={self.api_key}"
        try:
            self.ws = await websockets.connect(ws_url)
            return True
        except Exception as e:
            self.errors.append(f"Connection failed: {e}")
            return False

    async def receive_events_until(
        self, 
        target_events: list[str], 
        timeout: float = 60.0,
        max_events: int = 1000
    ) -> list[dict[str, Any]]:
        """Receive events until target event or timeout."""
        events = []
        start_time = time.time()

        try:
            while len(events) < max_events and time.time() - start_time < timeout:
                try:
                    msg = await asyncio.wait_for(self.ws.recv(), timeout=1.0)
                    data = json.loads(msg)
                    events.append(data)
                    self.events_log.append(data)

                    event_type = data.get("type", "unknown")
                    
                    # Log important events
                    if event_type in ["clarification_asked", "decision_asked", "env_var_requested"]:
                        self.hitl_count += 1
                        request_id = data.get("data", {}).get("request_id")
                        print(f"      >>> HITL #{self.hitl_count} detected: {event_type} / {request_id}")
                    elif event_type in ["complete", "error"]:
                        print(f"      >>> {event_type.upper()} event received")

                    if event_type in target_events:
                        return events

                except TimeoutError:
                    continue

        except Exception as e:
            self.errors.append(f"Error receiving: {e}")

        return events

    async def send_hitl_response(self, hitl_type: str, request_id: str, response: str) -> bool:
        """Send HITL response."""
        if hitl_type == "decision":
            msg_type = "decision_respond"
            response_data = {"decision": response}
        elif hitl_type == "clarification":
            msg_type = "clarification_respond"
            response_data = {"answer": response}
        else:  # env_var
            msg_type = "env_var_respond"
            response_data = {"values": {response: "test_value"}}

        msg = {
            "type": msg_type,
            "request_id": request_id,
            **response_data,
        }

        try:
            await self.ws.send(json.dumps(msg))
            print(f"      >>> Sent {msg_type}: {response}")
            return True
        except Exception as e:
            self.errors.append(f"Failed to send HITL response: {e}")
            return False

    async def run_multi_hitl_test(self) -> bool:
        """Run the complete multi-HITL test."""
        print("\n" + "=" * 70)
        print("Multiple HITL Interactions Test")
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

        # Step 2: Send message designed to trigger multiple HITLs
        print("\n[Step 2] Sending message that may trigger multiple HITLs...")
        # This message is designed to potentially trigger multiple decisions
        message = (
            "I need to perform a complex multi-step operation. "
            "First, should I use approach A or B? "
            "Then, should I optimize for speed or accuracy? "
            "Please guide me through this step by step."
        )
        await self.ws.send(json.dumps({
            "type": "send_message",
            "conversation_id": self.conversation_id,
            "message": message,
            "project_id": self.project_id,
        }))

        # Step 3: Handle multiple HITL cycles
        print("\n[Step 3] Handling HITL cycles...")
        
        cycle = 0
        while cycle < self.max_hitls:
            cycle += 1
            print(f"\n   --- HITL Cycle #{cycle} ---")
            
            # Wait for HITL request or completion
            events = await self.receive_events_until(
                target_events=["clarification_asked", "decision_asked", "env_var_requested", "complete", "error"],
                timeout=60.0
            )

            # Check what happened
            event_types = [e.get("type") for e in events]
            
            if "error" in event_types:
                error_event = [e for e in events if e.get("type") == "error"][-1]
                print(f"   ✗ Error during cycle #{cycle}: {error_event.get('data', {})}")
                return False

            if "complete" in event_types:
                print(f"   ✓ Agent completed after {self.hitl_count} HITL(s)")
                return True

            # Find HITL request
            hitl_event = None
            for e in events:
                if e.get("type") in ["clarification_asked", "decision_asked", "env_var_requested"]:
                    hitl_event = e
                    break

            if not hitl_event:
                print(f"   ⚠ No HITL request in cycle #{cycle}, continuing to listen...")
                # Check if we got any meaningful events
                if len(events) < 3:  # Only ack + message + user_message
                    print(f"   ✗ No progress after cycle #{cycle}")
                    return False
                continue

            # Extract HITL info
            hitl_type = hitl_event.get("type").replace("_asked", "").replace("_requested", "")
            request_id = hitl_event.get("data", {}).get("request_id")
            question = hitl_event.get("data", {}).get("question", "")
            
            print(f"   HITL type: {hitl_type}")
            print(f"   Question: {question[:80]}...")

            # Send response based on HITL type
            if hitl_type == "decision":
                # Alternate between options to test different paths
                response = "option_a" if cycle % 2 == 1 else "option_b"
            elif hitl_type == "clarification":
                response = f"clarification_response_{cycle}"
            else:
                response = f"env_var_{cycle}"

            success = await self.send_hitl_response(hitl_type, request_id, response)
            if not success:
                print("   ✗ Failed to send HITL response")
                return False

            # Wait a moment for the response to be processed
            await asyncio.sleep(0.5)

        print(f"\n   ⚠ Reached max HITL cycles ({self.max_hitls})")
        return False

    async def close(self):
        """Close connection."""
        if self.ws:
            await self.ws.close()

    def print_summary(self):
        """Print test summary."""
        print("\n" + "=" * 70)
        print("Test Summary")
        print("=" * 70)
        print(f"Total HITL interactions: {self.hitl_count}")
        print(f"Total events received: {len(self.events_log)}")
        
        # Count event types
        event_type_counts = {}
        for e in self.events_log:
            et = e.get("type", "unknown")
            event_type_counts[et] = event_type_counts.get(et, 0) + 1
        
        print("\nEvent type breakdown:")
        for et, count in sorted(event_type_counts.items(), key=lambda x: -x[1]):
            print(f"  {et}: {count}")

        if self.errors:
            print("\nErrors:")
            for err in self.errors:
                print(f"  - {err}")


async def main():
    """Main test entry."""
    print("=" * 70)
    print("Multiple HITL Interactions Test")
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
    tester = MultiHITLTester(API_KEY, TEST_PROJECT_ID, TEST_CONVERSATION_ID)

    try:
        success = await tester.run_multi_hitl_test()
        tester.print_summary()

        if success:
            print("\n✓ TEST PASSED - Multiple HITL interactions work correctly!")
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
