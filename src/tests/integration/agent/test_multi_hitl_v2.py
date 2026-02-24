#!/usr/bin/env python3
"""
Test script for multiple HITL (Human-in-the-Loop) interactions - Version 2.

This version waits longer after each HITL response to see if:
1. Agent triggers another HITL
2. Agent completes the task
"""

import asyncio
import json
import os
import sys
import time
from typing import Any

import websockets

sys.path.insert(0, os.getcwd())

WS_BASE_URL = os.environ.get("WS_BASE_URL", "ws://localhost:8000")
API_KEY = os.environ.get("API_KEY", "")
TEST_PROJECT_ID = os.environ.get("TEST_PROJECT_ID", "")
TEST_CONVERSATION_ID = os.environ.get("TEST_CONVERSATION_ID", "")


class MultiHITLTester:
    def __init__(self, api_key: str, project_id: str, conversation_id: str) -> None:
        self.api_key = api_key
        self.project_id = project_id
        self.conversation_id = conversation_id
        self.session_id: str | None = None
        self.ws: websockets.WebSocketClientProtocol | None = None
        self.hitl_count = 0
        self.events_log: list[dict[str, Any]] = []
        self.errors: list[str] = []

    async def connect(self) -> bool:
        ws_url = f"{WS_BASE_URL}/api/v1/agent/ws?token={self.api_key}"
        try:
            self.ws = await websockets.connect(ws_url)
            return True
        except Exception as e:
            self.errors.append(f"Connection failed: {e}")
            return False

    async def receive_events_until(
        self, target_events: list[str], timeout: float = 60.0, max_events: int = 2000
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

                    if event_type in ["clarification_asked", "decision_asked", "env_var_requested"]:
                        self.hitl_count += 1
                        request_id = data.get("data", {}).get("request_id")
                        print(f"      >>> HITL #{self.hitl_count}: {event_type} / {request_id}")
                    elif event_type == "complete":
                        print("      >>> COMPLETE event received!")
                    elif event_type == "error":
                        error_msg = data.get("data", {}).get("message", "Unknown error")
                        print(f"      >>> ERROR: {error_msg[:80]}")

                    if event_type in target_events:
                        return events

                except TimeoutError:
                    continue

        except Exception as e:
            self.errors.append(f"Error receiving: {e}")

        return events

    async def send_hitl_response(self, hitl_type: str, request_id: str, response: str) -> bool:
        if hitl_type == "decision":
            msg_type = "decision_respond"
            response_data = {"decision": response}
        elif hitl_type == "clarification":
            msg_type = "clarification_respond"
            response_data = {"answer": response}
        else:
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
        print("\n" + "=" * 70)
        print("Multiple HITL Interactions Test v2")
        print("=" * 70)

        # Connect
        print("\n[Step 1] Connecting to WebSocket...")
        if not await self.connect():
            print(f"   ✗ Failed: {self.errors[-1]}")
            return False

        msg = await self.ws.recv()
        data = json.loads(msg)
        if data.get("type") != "connected":
            print(f"   ✗ Expected 'connected', got {data.get('type')}")
            return False

        self.session_id = data.get("data", {}).get("session_id")
        print(f"   ✓ Connected (session: {self.session_id[:8]}...)")

        # Send message designed to trigger multiple HITLs
        print("\n[Step 2] Sending message that may trigger multiple HITLs...")
        message = (
            "I need to perform a complex multi-step operation. "
            "First, should I use approach A or B? "
            "Then, should I optimize for speed or accuracy? "
            "Please guide me through this step by step."
        )
        await self.ws.send(
            json.dumps(
                {
                    "type": "send_message",
                    "conversation_id": self.conversation_id,
                    "message": message,
                    "project_id": self.project_id,
                }
            )
        )

        # Handle HITL cycles
        print("\n[Step 3] Handling HITL cycles...")

        max_cycles = 5
        for cycle in range(1, max_cycles + 1):
            print(f"\n   --- Cycle #{cycle}: Waiting for HITL or completion ---")

            events = await self.receive_events_until(
                target_events=[
                    "clarification_asked",
                    "decision_asked",
                    "env_var_requested",
                    "complete",
                    "error",
                ],
                timeout=60.0,
            )

            event_types = [e.get("type") for e in events]

            if "error" in event_types:
                error_event = [e for e in events if e.get("type") == "error"][-1]
                error_data = error_event.get("data", {})
                print(f"   ✗ Error: {error_data}")
                return False

            if "complete" in event_types:
                print(f"   ✓ Agent completed after {self.hitl_count} HITL interaction(s)!")
                return True

            # Find HITL request
            hitl_event = None
            hitl_type = None
            for e in events:
                if e.get("type") == "clarification_asked":
                    hitl_event = e
                    hitl_type = "clarification"
                    break
                elif e.get("type") == "decision_asked":
                    hitl_event = e
                    hitl_type = "decision"
                    break
                elif e.get("type") == "env_var_requested":
                    hitl_event = e
                    hitl_type = "env_var"
                    break

            if not hitl_event:
                print(f"   ⚠ No HITL or completion in cycle #{cycle}")
                # Check if we're still getting events
                if len(events) > 10:
                    print(f"   Agent is still processing ({len(events)} events)")
                    # Try one more cycle
                    continue
                else:
                    print("   No progress, stopping")
                    return False

            request_id = hitl_event.get("data", {}).get("request_id")
            question = hitl_event.get("data", {}).get("question", "")[:60]
            print(f"   HITL: {hitl_type}")
            print(f"   Q: {question}...")

            # Send response
            if hitl_type == "decision":
                response = "option_a" if cycle % 2 == 1 else "option_b"
            else:
                response = f"response_{cycle}"

            success = await self.send_hitl_response(hitl_type, request_id, response)
            if not success:
                return False

            # Wait for the response to be processed
            print("   Waiting for Agent to process response...")
            await asyncio.sleep(1.0)

        print(f"\n   ⚠ Reached max cycles ({max_cycles})")
        return False

    async def close(self):
        if self.ws:
            await self.ws.close()

    def print_summary(self):
        print("\n" + "=" * 70)
        print("Test Summary")
        print("=" * 70)
        print(f"Total HITL interactions: {self.hitl_count}")
        print(f"Total events received: {len(self.events_log)}")

        event_type_counts = {}
        for e in self.events_log:
            et = e.get("type", "unknown")
            event_type_counts[et] = event_type_counts.get(et, 0) + 1

        print("\nEvent type breakdown:")
        for et, count in sorted(event_type_counts.items(), key=lambda x: -x[1])[:10]:
            print(f"  {et}: {count}")

        if self.errors:
            print("\nErrors:")
            for err in self.errors:
                print(f"  - {err}")


async def main():
    print("=" * 70)
    print("Multiple HITL Interactions Test v2")
    print("=" * 70)

    print("\nEnvironment:")
    print(f"  WS_BASE_URL: {WS_BASE_URL}")
    print(f"  API_KEY: {'***' if API_KEY else 'NOT SET'}")
    print(f"  TEST_PROJECT_ID: {TEST_PROJECT_ID or 'NOT SET'}")
    print(f"  TEST_CONVERSATION_ID: {TEST_CONVERSATION_ID or 'NOT SET'}")

    if not API_KEY or not TEST_PROJECT_ID or not TEST_CONVERSATION_ID:
        print("\n✗ Missing required environment variables!")
        sys.exit(1)

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
