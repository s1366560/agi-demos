from src.infrastructure.acp.event_mapper import memstack_event_to_acp_updates, update_to_payload


def test_maps_text_delta_to_agent_message_chunk() -> None:
    updates = memstack_event_to_acp_updates(
        {
            "type": "text_delta",
            "data": {"delta": "hello", "message_id": "message-1"},
            "timestamp": "2026-06-24T00:00:00Z",
        }
    )

    payload = update_to_payload(updates[0])

    assert payload["sessionUpdate"] == "agent_message_chunk"
    assert payload["content"] == {"text": "hello", "type": "text"}
    assert payload["messageId"] == "message-1"
    assert payload["_meta"]["memstack"]["eventType"] == "text_delta"


def test_maps_task_list_to_plan_update() -> None:
    updates = memstack_event_to_acp_updates(
        {
            "type": "task_list_updated",
            "data": {
                "tasks": [
                    {"content": "inspect", "status": "running", "priority": "high"},
                    {"title": "verify", "status": "done", "priority": "low"},
                ]
            },
        }
    )

    payload = update_to_payload(updates[0])

    assert payload["sessionUpdate"] == "plan"
    assert payload["entries"] == [
        {"content": "inspect", "priority": "high", "status": "in_progress"},
        {"content": "verify", "priority": "low", "status": "completed"},
    ]


def test_maps_tool_event_to_tool_call_update() -> None:
    updates = memstack_event_to_acp_updates(
        {
            "type": "observe",
            "id": "event-1",
            "data": {
                "tool_call_id": "tool-1",
                "tool_name": "terminal.exec",
                "output": "ok",
            },
        }
    )

    payload = update_to_payload(updates[0])

    assert payload["sessionUpdate"] == "tool_call_update"
    assert payload["toolCallId"] == "tool-1"
    assert payload["kind"] == "execute"
    assert payload["status"] == "completed"
    assert payload["rawOutput"] == "ok"


def test_unknown_event_preserves_memstack_metadata() -> None:
    updates = memstack_event_to_acp_updates({"type": "custom_event", "data": {"value": 1}})

    payload = update_to_payload(updates[0])

    assert payload["sessionUpdate"] == "session_info_update"
    assert payload["_meta"]["memstack"]["eventType"] == "custom_event"


def test_error_event_maps_to_visible_agent_message() -> None:
    updates = memstack_event_to_acp_updates(
        {"type": "error", "data": {"message": "backend failed"}}
    )

    payload = update_to_payload(updates[0])

    assert payload["sessionUpdate"] == "agent_message_chunk"
    assert payload["content"] == {"text": "backend failed", "type": "text"}
    assert payload["_meta"]["memstack"]["eventType"] == "error"
