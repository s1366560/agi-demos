"""Device host operations available to an explicitly approved signed release."""

import json

import rfc8785

DESCRIPTOR = "targets/desktop-capability.json"
LOCAL_CHAT = "device.local-chat"
LOCAL_CHAT_TOOL = "local_chat"


def local_chat_descriptor() -> dict[str, str]:
    return {
        "schema": "memstack.device-capability/1",
        "permission": LOCAL_CHAT,
        "tool": LOCAL_CHAT_TOOL,
    }


def device_capability_tool(raw: bytes) -> str:
    if json.loads(raw) != local_chat_descriptor():
        raise ValueError("unsupported device host capability")
    return LOCAL_CHAT_TOOL


def attach_device_capability(
    capability: object,
    files: dict[str, bytes],
    permissions: set[str],
    target: str,
    archive: bytes | None,
) -> str:
    if capability != LOCAL_CHAT or target != "python" or archive is not None:
        raise ValueError("unsupported device host capability")
    files[DESCRIPTOR] = rfc8785.dumps(local_chat_descriptor())
    permissions.add(LOCAL_CHAT)
    return LOCAL_CHAT_TOOL
