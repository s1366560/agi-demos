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

        def register_p2_im_message_message_read_v1(self, _handler):
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

        def register_p2_im_message_message_read_v1(self, _handler):
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

# -- Helpers for mocking lark_oapi v2 SDK response objects -----------------


class _FakeResponseData:
    """Mimics the SDK response data object with a message_id attribute."""

    def __init__(self, message_id: str | None = None) -> None:
        self.message_id = message_id


class _FakeResponse:
    """Mimics CreateMessageResponse / ReplyMessageResponse."""

    def __init__(
        self,
        code: int = 0,
        msg: str = "ok",
        message_id: str | None = None,
    ) -> None:
        self.code = code
        self.msg = msg
        self.data = _FakeResponseData(message_id) if message_id else None

    def success(self) -> bool:
        return self.code == 0


class _FakeMessageAPI:
    """Mimics client.im.v1.message with create(), reply(), patch(), update(), delete()."""

    def __init__(
        self,
        create_response: _FakeResponse | None = None,
        reply_response: _FakeResponse | None = None,
        patch_response: _FakeResponse | None = None,
        update_response: _FakeResponse | None = None,
        delete_response: _FakeResponse | None = None,
        *,
        has_reply: bool = True,
    ) -> None:
        self.create_called = False
        self.reply_called = False
        self.patch_called = False
        self.update_called = False
        self.delete_called = False
        self.create_request = None
        self.reply_request = None
        self.patch_request = None
        self.update_request = None
        self.delete_request = None
        self._create_response = create_response or _FakeResponse(message_id="om_default")
        self._reply_response = reply_response
        self._patch_response = patch_response or _FakeResponse()
        self._update_response = update_response or _FakeResponse()
        self._delete_response = delete_response or _FakeResponse()
        self._has_reply = has_reply

    def create(self, request, option=None):
        self.create_called = True
        self.create_request = request
        return self._create_response

    def reply(self, request, option=None):
        if not self._has_reply:
            raise AttributeError("no reply")
        self.reply_called = True
        self.reply_request = request
        return self._reply_response or _FakeResponse(message_id="om_reply_default")

    def patch(self, request, option=None):
        self.patch_called = True
        self.patch_request = request
        return self._patch_response

    def update(self, request, option=None):
        self.update_called = True
        self.update_request = request
        return self._update_response

    def delete(self, request, option=None):
        self.delete_called = True
        self.delete_request = request
        return self._delete_response


def _build_fake_client(message_api: _FakeMessageAPI) -> SimpleNamespace:
    """Build a fake client matching client.im.v1.message structure."""
    return SimpleNamespace(im=SimpleNamespace(v1=SimpleNamespace(message=message_api)))


# -- send_message tests using v2 SDK builder pattern -----------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_accepts_object_response_payload(adapter: FeishuAdapter) -> None:
    """send_message should parse SDK response objects (response.data.message_id)."""
    msg_api = _FakeMessageAPI(create_response=_FakeResponse(message_id="om_123"))
    adapter._connected = True
    adapter._build_rest_client = lambda: _build_fake_client(msg_api)

    message_id = await adapter.send_text("oc_chat_1", "hello")

    assert message_id == "om_123"
    assert msg_api.create_called is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_raises_on_non_zero_response_code(adapter: FeishuAdapter) -> None:
    """send_message should raise if Feishu API returns an error code."""
    msg_api = _FakeMessageAPI(
        create_response=_FakeResponse(code=99991663, msg="forbidden")
    )
    adapter._connected = True
    adapter._build_rest_client = lambda: _build_fake_client(msg_api)

    with pytest.raises(RuntimeError, match="Feishu send failed"):
        await adapter.send_text("oc_chat_1", "hello")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_uses_reply_api_when_reply_to_provided(adapter: FeishuAdapter) -> None:
    """send_message should use reply API when reply_to is available."""
    msg_api = _FakeMessageAPI(
        reply_response=_FakeResponse(message_id="om_reply_1"),
        create_response=_FakeResponse(message_id="om_create_1"),
    )
    adapter._connected = True
    adapter._build_rest_client = lambda: _build_fake_client(msg_api)

    message_id = await adapter.send_text("oc_chat_1", "hello", reply_to="om_parent")

    assert message_id == "om_reply_1"
    assert msg_api.reply_called is True
    assert msg_api.create_called is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_falls_back_to_create_when_reply_api_missing(
    adapter: FeishuAdapter,
) -> None:
    """send_message should fallback to create when reply raises an error."""
    msg_api = _FakeMessageAPI(
        create_response=_FakeResponse(message_id="om_create_2"),
        has_reply=False,
    )
    adapter._connected = True
    adapter._build_rest_client = lambda: _build_fake_client(msg_api)

    message_id = await adapter.send_text("oc_chat_1", "hello", reply_to="om_parent")

    assert message_id == "om_create_2"
    assert msg_api.create_called is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_falls_back_to_create_when_reply_returns_error(
    adapter: FeishuAdapter,
) -> None:
    """send_message should fallback to create when reply API returns non-zero code."""
    msg_api = _FakeMessageAPI(
        reply_response=_FakeResponse(code=999, msg="reply failed"),
        create_response=_FakeResponse(message_id="om_create_fallback"),
    )
    adapter._connected = True
    adapter._build_rest_client = lambda: _build_fake_client(msg_api)

    message_id = await adapter.send_text("oc_chat_1", "hello", reply_to="om_parent")

    assert message_id == "om_create_fallback"
    assert msg_api.reply_called is True
    assert msg_api.create_called is True


# -- patch_card tests -------------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_patch_card_success(adapter: FeishuAdapter) -> None:
    """patch_card should call patch API and return True on success."""
    msg_api = _FakeMessageAPI(patch_response=_FakeResponse())
    adapter._connected = True
    adapter._build_rest_client = lambda: _build_fake_client(msg_api)

    result = await adapter.patch_card("om_card_1", '{"elements": []}')

    assert result is True
    assert msg_api.patch_called is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_patch_card_returns_false_on_failure(adapter: FeishuAdapter) -> None:
    """patch_card should return False when Feishu API returns error."""
    msg_api = _FakeMessageAPI(
        patch_response=_FakeResponse(code=999, msg="patch failed")
    )
    adapter._connected = True
    adapter._build_rest_client = lambda: _build_fake_client(msg_api)

    result = await adapter.patch_card("om_card_1", '{"elements": []}')

    assert result is False
    assert msg_api.patch_called is True


# -- edit_message tests (v2 SDK) -------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_edit_message_success(adapter: FeishuAdapter) -> None:
    """edit_message should use UpdateMessageRequest via v2 SDK."""
    msg_api = _FakeMessageAPI(update_response=_FakeResponse())
    adapter._connected = True
    adapter._build_rest_client = lambda: _build_fake_client(msg_api)

    from src.domain.model.channels.message import MessageContent, MessageType

    result = await adapter.edit_message(
        "om_1", MessageContent(type=MessageType.TEXT, text="updated")
    )

    assert result is True
    assert msg_api.update_called is True


# -- delete_message tests (v2 SDK) -----------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_message_success(adapter: FeishuAdapter) -> None:
    """delete_message should use DeleteMessageRequest via v2 SDK."""
    msg_api = _FakeMessageAPI(delete_response=_FakeResponse())
    adapter._connected = True
    adapter._build_rest_client = lambda: _build_fake_client(msg_api)

    result = await adapter.delete_message("om_1")

    assert result is True
    assert msg_api.delete_called is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_message_returns_false_on_failure(adapter: FeishuAdapter) -> None:
    """delete_message should return False when API returns error."""
    msg_api = _FakeMessageAPI(
        delete_response=_FakeResponse(code=999, msg="not found")
    )
    adapter._connected = True
    adapter._build_rest_client = lambda: _build_fake_client(msg_api)

    result = await adapter.delete_message("om_1")

    assert result is False


# -- send_streaming_card tests ---------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_streaming_card_returns_message_id(adapter: FeishuAdapter) -> None:
    """send_streaming_card should send a card and return its message_id."""
    msg_api = _FakeMessageAPI(create_response=_FakeResponse(message_id="om_stream_1"))
    adapter._connected = True
    adapter._build_rest_client = lambda: _build_fake_client(msg_api)

    msg_id = await adapter.send_streaming_card("oc_chat_1")

    assert msg_id == "om_stream_1"
    assert msg_api.create_called is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_streaming_card_returns_none_on_error(adapter: FeishuAdapter) -> None:
    """send_streaming_card should return None when send fails."""
    msg_api = _FakeMessageAPI(
        create_response=_FakeResponse(code=999, msg="fail")
    )
    adapter._connected = True
    adapter._build_rest_client = lambda: _build_fake_client(msg_api)

    msg_id = await adapter.send_streaming_card("oc_chat_1")

    assert msg_id is None


# -- _build_streaming_card tests -------------------------------------------


@pytest.mark.unit
def test_build_streaming_card_without_loading(adapter: FeishuAdapter) -> None:
    """_build_streaming_card should produce a card JSON without loading indicator."""
    import json

    card_json = adapter._build_streaming_card("Hello world")
    card = json.loads(card_json)

    assert card["elements"][0]["content"] == "Hello world"


@pytest.mark.unit
def test_build_streaming_card_with_loading(adapter: FeishuAdapter) -> None:
    """_build_streaming_card should append loading indicator when loading=True."""
    import json

    card_json = adapter._build_streaming_card("Partial text", loading=True)
    card = json.loads(card_json)

    assert "Generating..." in card["elements"][0]["content"]
    assert "Partial text" in card["elements"][0]["content"]
