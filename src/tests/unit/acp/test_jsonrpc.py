from typing import Any

from acp.exceptions import RequestError
from acp.schema import NewSessionResponse

from src.infrastructure.acp.jsonrpc import ACPWebSocketJSONRPCPeer


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[str] = []

    async def send_text(self, payload: str) -> None:
        self.sent.append(payload)


async def test_dispatch_sends_model_result() -> None:
    async def handler(method: str, params: Any, is_notification: bool) -> Any:
        assert method == "session/new"
        assert params == {"cwd": "/tmp"}
        assert not is_notification
        return NewSessionResponse(session_id="session-1")

    websocket = FakeWebSocket()
    peer = ACPWebSocketJSONRPCPeer(websocket, handler)

    await peer._dispatch(
        {"jsonrpc": "2.0", "id": 7, "method": "session/new", "params": {"cwd": "/tmp"}}
    )

    assert websocket.sent == [
        '{"jsonrpc":"2.0","id":7,"result":{"sessionId":"session-1"}}'
    ]


async def test_dispatch_sends_request_error() -> None:
    async def handler(method: str, params: Any, is_notification: bool) -> Any:
        del method, params, is_notification
        raise RequestError.invalid_params({"field": "cwd"})

    websocket = FakeWebSocket()
    peer = ACPWebSocketJSONRPCPeer(websocket, handler)

    await peer._dispatch(
        {"jsonrpc": "2.0", "id": "a", "method": "session/new", "params": {}}
    )

    assert websocket.sent == [
        (
            '{"jsonrpc":"2.0","id":"a","error":'
            '{"code":-32602,"message":"Invalid params","data":{"field":"cwd"}}}'
        )
    ]
