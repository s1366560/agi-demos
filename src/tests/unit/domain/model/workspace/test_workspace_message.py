"""Unit tests for WorkspaceMessage domain model."""

import pytest

from src.domain.model.workspace.workspace_message import (
    MessageSenderType,
    WorkspaceMessage,
)


@pytest.mark.unit
class TestMessageSenderType:
    """Tests for MessageSenderType enum."""

    def test_human_value(self) -> None:
        assert MessageSenderType.HUMAN.value == "human"

    def test_agent_value(self) -> None:
        assert MessageSenderType.AGENT.value == "agent"

    def test_is_str_enum(self) -> None:
        assert isinstance(MessageSenderType.HUMAN, str)
        assert MessageSenderType.AGENT == "agent"


@pytest.mark.unit
class TestWorkspaceMessage:
    """Tests for WorkspaceMessage entity."""

    def _make_message(self, **overrides: object) -> WorkspaceMessage:
        defaults: dict[str, object] = {
            "workspace_id": "ws-1",
            "sender_id": "user-1",
            "sender_type": MessageSenderType.HUMAN,
            "content": "Hello workspace",
        }
        defaults.update(overrides)
        return WorkspaceMessage(**defaults)  # type: ignore[arg-type]

    def test_create_minimal(self) -> None:
        msg = self._make_message()
        assert msg.workspace_id == "ws-1"
        assert msg.sender_id == "user-1"
        assert msg.sender_type == MessageSenderType.HUMAN
        assert msg.content == "Hello workspace"
        assert msg.mentions == []
        assert msg.parent_message_id is None
        assert msg.metadata == {}
        assert msg.id

    def test_create_with_all_fields(self) -> None:
        msg = self._make_message(
            mentions=["agent-1", "agent-2"],
            parent_message_id="msg-parent",
            metadata={"key": "value"},
        )
        assert msg.mentions == ["agent-1", "agent-2"]
        assert msg.parent_message_id == "msg-parent"
        assert msg.metadata == {"key": "value"}

    def test_agent_sender_type(self) -> None:
        msg = self._make_message(sender_type=MessageSenderType.AGENT)
        assert msg.sender_type == MessageSenderType.AGENT

    def test_created_at_auto_set(self) -> None:
        msg = self._make_message()
        assert msg.created_at is not None

    def test_unique_ids(self) -> None:
        msg1 = self._make_message()
        msg2 = self._make_message()
        assert msg1.id != msg2.id

    def test_empty_workspace_id_raises(self) -> None:
        with pytest.raises(ValueError, match="workspace_id cannot be empty"):
            self._make_message(workspace_id="")

    def test_empty_sender_id_raises(self) -> None:
        with pytest.raises(ValueError, match="sender_id cannot be empty"):
            self._make_message(sender_id="")

    def test_empty_content_raises(self) -> None:
        with pytest.raises(ValueError, match="content cannot be empty"):
            self._make_message(content="")

    def test_whitespace_only_content_raises(self) -> None:
        with pytest.raises(ValueError, match="content cannot be empty"):
            self._make_message(content="   ")

    def test_explicit_id(self) -> None:
        msg = self._make_message(id="custom-id")
        assert msg.id == "custom-id"

    def test_importable_from_workspace_package(self) -> None:
        from src.domain.model.workspace import (
            MessageSenderType as MessageSenderTypeAlias,
            WorkspaceMessage as WorkspaceMessageAlias,
        )

        assert MessageSenderTypeAlias is MessageSenderType
        assert WorkspaceMessageAlias is WorkspaceMessage

    def test_repo_importable_from_workspace_ports(self) -> None:
        from src.domain.ports.repositories.workspace import (
            WorkspaceMessageRepository,
        )

        assert WorkspaceMessageRepository is not None
