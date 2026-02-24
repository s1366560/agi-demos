#!/usr/bin/env python3
"""Test WebSocket chat functionality."""

import asyncio
import json
import sys

import websockets

# Configuration
BASE_URL = "ws://localhost:8000"
TOKEN = "ms_sk_bd1bd990b0c37bcba7fdb8c58d9817580b7ec89b1d2e06c156e2fa3dfd0d2435"
CONVERSATION_ID = "66297d9b-3545-4714-9834-a1305e714d13"
PROJECT_ID = "37bd3365-9155-456d-927c-6c50a9515eb9"


async def test_websocket_chat():
    """Test WebSocket chat."""
    uri = f"{BASE_URL}/api/v1/agent/ws?token={TOKEN}"

    print(f"Connecting to {uri}...")

    try:
        async with websockets.connect(uri) as ws:
            print("✓ WebSocket connected")

            # Subscribe to conversation
            subscribe_msg = {"type": "subscribe", "conversation_id": CONVERSATION_ID}
            await ws.send(json.dumps(subscribe_msg))
            print(f"✓ Sent subscribe message for conversation {CONVERSATION_ID}")

            # Wait for subscription acknowledgment
            response = await asyncio.wait_for(ws.recv(), timeout=5.0)
            print(f"← Received: {response}")

            # Send a test message
            chat_msg = {
                "type": "send_message",
                "conversation_id": CONVERSATION_ID,
                "project_id": PROJECT_ID,
                "message": "Hello! What can you help me with?",
            }
            await ws.send(json.dumps(chat_msg))
            print("✓ Sent chat message")

            # Listen for events
            print("\n=== Listening for events (30 seconds) ===\n")
            event_count = 0

            try:
                while event_count < 20:
                    response = await asyncio.wait_for(ws.recv(), timeout=30.0)
                    event = json.loads(response)
                    event_type = event.get("type", "unknown")
                    event_count += 1

                    print(f"[{event_count}] Type: {event_type}")

                    # Print specific event details
                    if event_type == "text_delta":
                        delta = event.get("data", {}).get("delta", "")
                        print(f"    Text: {delta[:50]}...")
                    elif event_type == "thought":
                        thought = event.get("data", {}).get("thought", "")
                        print(f"    Thought: {thought[:50]}...")
                    elif event_type == "error":
                        print(f"    ERROR: {event.get('data', {})}")
                    elif event_type == "complete":
                        print("    ✓ Chat completed!")
                        break
                    elif event_type == "ack":
                        print(f"    Ack: {event}")

            except TimeoutError:
                print("\n✓ Timeout - no more events received")

            print(f"\n=== Total events received: {event_count} ===")

    except websockets.exceptions.InvalidStatus as e:
        print(f"✗ Connection rejected: {e}")
        return False
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback

        traceback.print_exc()
        return False

    return True


if __name__ == "__main__":
    success = asyncio.run(test_websocket_chat())
    sys.exit(0 if success else 1)
