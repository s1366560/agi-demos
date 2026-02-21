"""Unit tests for Feishu adapter message normalization."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from src.domain.model.channels.message import ChannelConfig, ChatType
from src.infrastructure.adapters.secondary.channels.feishu.adapter import FeishuAdapter


@pytest.fixture
def adapter() -> FeishuAdapter:
    """Create adapter with minimal valid config."""
    return FeishuAdapter(ChannelConfig(app_id="cli_test", app_secret="secret"))


@pytest.mark.unit
def test_parse_message_handles_none_mentions(adapter: FeishuAdapter) -> None:
    """Parser should tolerate null mentions payload from Feishu events."""
    message = adapter._parse_message(
        message_data={
            "chat_type": "group",
            "chat_id": "chat-1",
            "content": '{"text":"hello"}',
            "message_type": "text",
            "mentions": None,
        },
        sender_data={"sender_id": {"open_id": "ou_sender"}, "sender_type": "user"},
    )

    assert message.sender.id == "ou_sender"
    assert message.chat_type == ChatType.GROUP
    assert message.mentions == []


@pytest.mark.unit
def test_parse_message_handles_object_mentions(adapter: FeishuAdapter) -> None:
    """Parser should extract mentions from SDK object-shaped payloads."""

    class _SenderId:
        def __init__(self, open_id: str) -> None:
            self.open_id = open_id

    class _MentionId:
        def __init__(self, open_id: str) -> None:
            self.open_id = open_id

    class _Mention:
        def __init__(self, open_id: str) -> None:
            self.id = _MentionId(open_id)

    message = adapter._parse_message(
        message_data={
            "chat_type": "group",
            "chat_id": "chat-1",
            "content": '{"text":"hello"}',
            "message_type": "text",
            "mentions": [_Mention("ou_mention_1"), {"id": {"open_id": "ou_mention_2"}}],
        },
        sender_data={"sender_id": _SenderId("ou_sender"), "sender_type": "user"},
    )

    assert message.sender.id == "ou_sender"
    assert message.mentions == ["ou_mention_1", "ou_mention_2"]


@pytest.mark.unit
def test_parse_message_fallback_for_unknown_chat_type(adapter: FeishuAdapter) -> None:
    """Unknown chat_type should fallback to p2p instead of raising."""
    message = adapter._parse_message(
        message_data={
            "chat_type": "unknown",
            "chat_id": "chat-1",
            "content": {"text": "hello"},
            "message_type": "text",
            "mentions": [],
        },
        sender_data={"sender_id": {"open_id": "ou_sender"}, "sender_type": "user"},
    )

    assert message.chat_type == ChatType.P2P
    assert message.content.text == "hello"


@pytest.mark.unit
def test_parse_message_fallback_for_invalid_chat_type_shape(adapter: FeishuAdapter) -> None:
    """Malformed chat_type payload should fallback safely."""
    message = adapter._parse_message(
        message_data={
            "chat_type": {"bad": "shape"},
            "chat_id": "chat-1",
            "content": '{"text":"hello"}',
            "message_type": "text",
            "mentions": [],
        },
        sender_data={"sender_id": {"open_id": "ou_sender"}, "sender_type": "user"},
    )

    assert message.chat_type == ChatType.P2P


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw_content,expected_text",
    [
        ('["a", "b"]', "['a', 'b']"),
        ("123", "123"),
        ('"hello"', "hello"),
    ],
)
def test_parse_message_handles_non_object_json_content(
    adapter: FeishuAdapter, raw_content: str, expected_text: str
) -> None:
    """Text parser should handle valid JSON scalars/arrays without crashing."""
    message = adapter._parse_message(
        message_data={
            "chat_type": "p2p",
            "chat_id": "chat-1",
            "content": raw_content,
            "message_type": "text",
            "mentions": [],
        },
        sender_data={"sender_id": {"open_id": "ou_sender"}, "sender_type": "user"},
    )

    assert message.content.text == expected_text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connect_websocket_starts_dedicated_thread(adapter: FeishuAdapter) -> None:
    """WebSocket connect should start lark client in dedicated daemon thread."""

    class _Builder:
        def __init__(self, **_kwargs) -> None:
            pass

        def register_p2_im_message_receive_v1(self, _handler):
            return self

        def register_p2_im_message_recalled_v1(self, _handler):
            return self

        def register_p2_im_chat_member_bot_added_v1(self, _handler):
            return self

        def register_p2_im_chat_member_bot_deleted_v1(self, _handler):
            return self

        def build(self):
            return object()

    class _FakeThread:
        def __init__(self, *, target=None, kwargs=None, name=None, daemon=None):
            self.target = target
            self.kwargs = kwargs or {}
            self.name = name
            self.daemon = daemon
            self.started = False

        def start(self):
            self.started = True

    with (
        pytest.MonkeyPatch.context() as monkeypatch,
        patch(
            "src.infrastructure.adapters.secondary.channels.feishu.adapter.threading.Thread",
            new=_FakeThread,
        ),
        patch.object(adapter, "_wait_for_websocket_ready", new=AsyncMock()),
    ):
        monkeypatch.setitem(sys.modules, "lark_oapi", SimpleNamespace())
        monkeypatch.setitem(sys.modules, "lark_oapi.event", SimpleNamespace())
        monkeypatch.setitem(
            sys.modules,
            "lark_oapi.event.dispatcher_handler",
            SimpleNamespace(EventDispatcherHandlerBuilder=_Builder),
        )
        await adapter._connect_websocket()

    assert adapter._ws_thread is not None
    assert adapter._ws_thread.started is True
    assert adapter._ws_thread.daemon is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connect_websocket_cleans_up_when_wait_fails(
    adapter: FeishuAdapter,
) -> None:
    """WebSocket startup wait failure should trigger cleanup."""

    class _Builder:
        def __init__(self, **_kwargs) -> None:
            pass

        def register_p2_im_message_receive_v1(self, _handler):
            return self

        def register_p2_im_message_recalled_v1(self, _handler):
            return self

        def register_p2_im_chat_member_bot_added_v1(self, _handler):
            return self

        def register_p2_im_chat_member_bot_deleted_v1(self, _handler):
            return self

        def build(self):
            return object()

    class _FakeThread:
        def __init__(self, *, target=None, kwargs=None, name=None, daemon=None):
            self.target = target
            self.kwargs = kwargs or {}
            self.name = name
            self.daemon = daemon
            self.started = False

        def start(self):
            self.started = True

    with (
        pytest.MonkeyPatch.context() as monkeypatch,
        patch(
            "src.infrastructure.adapters.secondary.channels.feishu.adapter.threading.Thread",
            new=_FakeThread,
        ),
        patch.object(
            adapter,
            "_wait_for_websocket_ready",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
        patch.object(adapter, "disconnect", new=AsyncMock()) as disconnect_mock,
    ):
        monkeypatch.setitem(sys.modules, "lark_oapi", SimpleNamespace())
        monkeypatch.setitem(sys.modules, "lark_oapi.event", SimpleNamespace())
        monkeypatch.setitem(
            sys.modules,
            "lark_oapi.event.dispatcher_handler",
            SimpleNamespace(EventDispatcherHandlerBuilder=_Builder),
        )
        with pytest.raises(RuntimeError, match="boom"):
            await adapter._connect_websocket()

    disconnect_mock.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connect_raises_when_websocket_thread_not_alive(
    adapter: FeishuAdapter,
) -> None:
    """connect should fail when websocket thread is not alive after startup."""

    class _DeadThread:
        @staticmethod
        def is_alive() -> bool:
            return False

    adapter._ws_thread = _DeadThread()
    adapter._ws_ready.set()

    with patch.object(adapter, "_connect_websocket", new=AsyncMock()):
        with pytest.raises(RuntimeError, match="failed to stay alive"):
            await adapter.connect()

    assert adapter.connected is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_for_websocket_ready_raises_startup_error(adapter: FeishuAdapter) -> None:
    """Startup waiter should fail fast when websocket thread reported an error."""
    adapter._ws_start_error = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="startup failed"):
        await adapter._wait_for_websocket_ready()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_wait_for_websocket_ready_returns_when_ready_event_set(
    adapter: FeishuAdapter,
) -> None:
    """Startup waiter should succeed when readiness event is set."""

    class _AliveThread:
        @staticmethod
        def is_alive() -> bool:
            return True

    adapter._ws_thread = _AliveThread()
    adapter._ws_ready.set()

    await adapter._wait_for_websocket_ready()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disconnect_stops_thread_and_clears_runtime_state(adapter: FeishuAdapter) -> None:
    """disconnect should stop websocket loop, join thread, and reset runtime refs."""

    class _FakeFuture:
        def result(self, timeout=None):
            return None

    class _FakeLoop:
        def __init__(self) -> None:
            self.stopped = False

        @staticmethod
        def is_running() -> bool:
            return True

        def stop(self) -> None:
            self.stopped = True

        def call_soon_threadsafe(self, _fn) -> None:
            self.stopped = True

    class _FakeThread:
        def __init__(self) -> None:
            self.joined = False
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

        def join(self, timeout=None) -> None:
            self.joined = True
            self._alive = False

    class _FakeClient:
        async def _disconnect(self) -> None:
            return None

    def _run_coroutine_threadsafe(coro, _loop):
        coro.close()
        return _FakeFuture()

    fake_loop = _FakeLoop()
    fake_thread = _FakeThread()

    adapter._connected = True
    adapter._ws_client = _FakeClient()
    adapter._ws_loop = fake_loop
    adapter._ws_thread = fake_thread
    adapter._ws_start_error = RuntimeError("old error")

    with patch(
        "src.infrastructure.adapters.secondary.channels.feishu.adapter.asyncio.run_coroutine_threadsafe",
        side_effect=_run_coroutine_threadsafe,
    ):
        await adapter.disconnect()

    assert adapter.connected is False
    assert adapter._ws_stop_requested is True
    assert fake_thread.joined is True
    assert fake_loop.stopped is True
    assert adapter._ws_client is None
    assert adapter._ws_thread is None
    assert adapter._ws_loop is None
    assert adapter._ws_ready.is_set() is False
    assert adapter._ws_start_error is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disconnect_raises_when_thread_does_not_stop(adapter: FeishuAdapter) -> None:
    """disconnect should fail loudly when websocket thread cannot be stopped."""

    class _FakeLoop:
        @staticmethod
        def is_running() -> bool:
            return False

    class _StuckThread:
        def __init__(self) -> None:
            self.joined = False

        @staticmethod
        def is_alive() -> bool:
            return True

        def join(self, timeout=None) -> None:
            self.joined = True

    stuck_thread = _StuckThread()
    adapter._ws_loop = _FakeLoop()
    adapter._ws_thread = stuck_thread

    with pytest.raises(RuntimeError, match="did not stop"):
        await adapter.disconnect()

    assert adapter._ws_thread is stuck_thread
    assert stuck_thread.joined is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_accepts_object_response_payload(adapter: FeishuAdapter) -> None:
    """send_message should parse object-shaped SDK responses."""

    class _ResponseData:
        def __init__(self) -> None:
            self.message_id = "om_123"

    class _Response:
        def __init__(self) -> None:
            self.code = 0
            self.msg = "ok"
            self.data = _ResponseData()

    class _MessageAPI:
        def __init__(self) -> None:
            self.create_kwargs = None

        @staticmethod
        def create(**kwargs):
            return _Response()

    class _Client:
        def __init__(self, **_kwargs) -> None:
            self.im = SimpleNamespace(message=_MessageAPI())

    adapter._connected = True

    adapter._build_rest_client = lambda: _Client()
    message_id = await adapter.send_text("oc_chat_1", "hello")

    assert message_id == "om_123"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_raises_on_non_zero_response_code(adapter: FeishuAdapter) -> None:
    """send_message should raise if Feishu API returns an error code."""

    class _Response:
        def __init__(self) -> None:
            self.code = 99991663
            self.msg = "forbidden"
            self.data = None

    class _MessageAPI:
        @staticmethod
        def create(**_kwargs):
            return _Response()

    class _Client:
        def __init__(self) -> None:
            self.im = SimpleNamespace(message=_MessageAPI())

    adapter._connected = True

    adapter._build_rest_client = lambda: _Client()
    with pytest.raises(RuntimeError, match="Feishu send failed"):
        await adapter.send_text("oc_chat_1", "hello")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_uses_reply_api_when_reply_to_provided(adapter: FeishuAdapter) -> None:
    """send_message should use reply API when reply_to is available."""

    class _Response:
        def __init__(self, message_id: str) -> None:
            self.code = 0
            self.msg = "ok"
            self.data = {"message_id": message_id}

    class _MessageAPI:
        def __init__(self) -> None:
            self.reply_called = False
            self.create_called = False
            self.reply_kwargs = None
            self.create_kwargs = None

        def reply(self, **kwargs):
            self.reply_called = True
            self.reply_kwargs = kwargs
            return _Response("om_reply_1")

        def create(self, **kwargs):
            self.create_called = True
            self.create_kwargs = kwargs
            return _Response("om_create_1")

    message_api = _MessageAPI()

    class _Client:
        def __init__(self) -> None:
            self.im = SimpleNamespace(message=message_api)

    adapter._connected = True

    adapter._build_rest_client = lambda: _Client()
    message_id = await adapter.send_text("oc_chat_1", "hello", reply_to="om_parent")

    assert message_id == "om_reply_1"
    assert message_api.reply_called is True
    assert message_api.create_called is False
    assert message_api.reply_kwargs == {
        "path": {"message_id": "om_parent"},
        "data": {"msg_type": "text", "content": '{"text": "hello"}'},
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_falls_back_to_create_when_reply_api_missing(
    adapter: FeishuAdapter,
) -> None:
    """send_message should fallback to create when SDK has no reply API."""

    class _Response:
        def __init__(self, message_id: str) -> None:
            self.code = 0
            self.msg = "ok"
            self.data = {"message_id": message_id}

    class _MessageAPI:
        def __init__(self) -> None:
            self.create_called = False
            self.create_kwargs = None

        def create(self, **kwargs):
            self.create_called = True
            self.create_kwargs = kwargs
            return _Response("om_create_2")

    message_api = _MessageAPI()

    class _Client:
        def __init__(self) -> None:
            self.im = SimpleNamespace(message=message_api)

    adapter._connected = True

    adapter._build_rest_client = lambda: _Client()
    message_id = await adapter.send_text("oc_chat_1", "hello", reply_to="om_parent")

    assert message_id == "om_create_2"
    assert message_api.create_called is True
    assert message_api.create_kwargs == {
        "params": {"receive_id_type": "chat_id"},
        "data": {"receive_id": "oc_chat_1", "msg_type": "text", "content": '{"text": "hello"}'},
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_falls_back_to_create_when_reply_returns_error(
    adapter: FeishuAdapter,
) -> None:
    """send_message should fallback to create when reply API returns non-zero code."""

    class _Response:
        def __init__(self, code: int, message_id: str | None = None) -> None:
            self.code = code
            self.msg = "ok" if code == 0 else "reply failed"
            self.data = {"message_id": message_id} if message_id else {}

    class _MessageAPI:
        def __init__(self) -> None:
            self.reply_called = False
            self.create_called = False
            self.reply_kwargs = None
            self.create_kwargs = None

        def reply(self, **kwargs):
            self.reply_called = True
            self.reply_kwargs = kwargs
            return _Response(999, None)

        def create(self, **kwargs):
            self.create_called = True
            self.create_kwargs = kwargs
            return _Response(0, "om_create_fallback")

    message_api = _MessageAPI()

    class _Client:
        def __init__(self) -> None:
            self.im = SimpleNamespace(message=message_api)

    adapter._connected = True

    adapter._build_rest_client = lambda: _Client()
    message_id = await adapter.send_text("oc_chat_1", "hello", reply_to="om_parent")

    assert message_id == "om_create_fallback"
    assert message_api.reply_called is True
    assert message_api.create_called is True
    assert message_api.reply_kwargs == {
        "path": {"message_id": "om_parent"},
        "data": {"msg_type": "text", "content": '{"text": "hello"}'},
    }
    assert message_api.create_kwargs == {
        "params": {"receive_id_type": "chat_id"},
        "data": {"receive_id": "oc_chat_1", "msg_type": "text", "content": '{"text": "hello"}'},
    }
