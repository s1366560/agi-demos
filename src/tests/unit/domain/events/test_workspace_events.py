import pytest

from src.domain.events.agent_events import (
    AgentEventType,
    BlackboardPostCreatedEvent,
    BlackboardPostDeletedEvent,
    BlackboardPostUpdatedEvent,
    BlackboardReplyCreatedEvent,
    BlackboardReplyDeletedEvent,
    TopologyUpdatedEvent,
    WorkspaceAgentBoundEvent,
    WorkspaceAgentUnboundEvent,
    WorkspaceDeletedEvent,
    WorkspaceMemberJoinedEvent,
    WorkspaceMemberLeftEvent,
    WorkspaceMessageCreatedEvent,
    WorkspaceTaskAssignedEvent,
    WorkspaceTaskCreatedEvent,
    WorkspaceTaskDeletedEvent,
    WorkspaceTaskStatusChangedEvent,
    WorkspaceTaskUpdatedEvent,
    WorkspaceUpdatedEvent,
)


@pytest.mark.unit
class TestWorkspaceMemberEvents:
    def test_member_joined_event(self) -> None:
        event = WorkspaceMemberJoinedEvent(
            workspace_id="ws_1",
            member_id="user_1",
            member_role="editor",
            metadata={"source": "invite"},
        )
        assert event.event_type == AgentEventType.WORKSPACE_MEMBER_JOINED
        assert event.workspace_id == "ws_1"
        assert event.member_id == "user_1"
        assert event.member_role == "editor"
        assert event.metadata == {"source": "invite"}

    def test_member_joined_event_to_dict(self) -> None:
        event = WorkspaceMemberJoinedEvent(
            workspace_id="ws_1",
            member_id="user_1",
        )
        d = event.to_event_dict()
        assert d["type"] == "workspace_member_joined"
        assert d["data"]["workspace_id"] == "ws_1"
        assert d["data"]["member_id"] == "user_1"
        assert "event_type" not in d["data"]
        assert "timestamp" in d

    def test_member_joined_defaults(self) -> None:
        event = WorkspaceMemberJoinedEvent(
            workspace_id="ws_1",
            member_id="user_1",
        )
        assert event.member_role is None
        assert event.metadata == {}

    def test_member_left_event(self) -> None:
        event = WorkspaceMemberLeftEvent(
            workspace_id="ws_1",
            member_id="user_2",
        )
        assert event.event_type == AgentEventType.WORKSPACE_MEMBER_LEFT
        d = event.to_event_dict()
        assert d["type"] == "workspace_member_left"
        assert d["data"]["member_id"] == "user_2"


@pytest.mark.unit
class TestWorkspaceLifecycleEvents:
    def test_workspace_updated_event(self) -> None:
        event = WorkspaceUpdatedEvent(
            workspace_id="ws_1",
            changes={"name": "New Name"},
        )
        assert event.event_type == AgentEventType.WORKSPACE_UPDATED
        d = event.to_event_dict()
        assert d["type"] == "workspace_updated"
        assert d["data"]["changes"] == {"name": "New Name"}

    def test_workspace_deleted_event(self) -> None:
        event = WorkspaceDeletedEvent(workspace_id="ws_1")
        assert event.event_type == AgentEventType.WORKSPACE_DELETED
        d = event.to_event_dict()
        assert d["type"] == "workspace_deleted"
        assert d["data"]["workspace_id"] == "ws_1"


@pytest.mark.unit
class TestWorkspaceAgentEvents:
    def test_agent_bound_event(self) -> None:
        event = WorkspaceAgentBoundEvent(
            workspace_id="ws_1",
            agent_id="agent_1",
            workspace_agent_id="wa_1",
            metadata={"role": "coder"},
        )
        assert event.event_type == AgentEventType.WORKSPACE_AGENT_BOUND
        d = event.to_event_dict()
        assert d["type"] == "workspace_agent_bound"
        assert d["data"]["agent_id"] == "agent_1"
        assert d["data"]["workspace_agent_id"] == "wa_1"

    def test_agent_bound_defaults(self) -> None:
        event = WorkspaceAgentBoundEvent(
            workspace_id="ws_1",
            agent_id="agent_1",
        )
        assert event.workspace_agent_id is None
        assert event.metadata == {}

    def test_agent_unbound_event(self) -> None:
        event = WorkspaceAgentUnboundEvent(
            workspace_id="ws_1",
            agent_id="agent_1",
            workspace_agent_id="wa_1",
        )
        assert event.event_type == AgentEventType.WORKSPACE_AGENT_UNBOUND
        d = event.to_event_dict()
        assert d["type"] == "workspace_agent_unbound"


@pytest.mark.unit
class TestBlackboardEvents:
    def test_post_created_event(self) -> None:
        event = BlackboardPostCreatedEvent(
            workspace_id="ws_1",
            post_id="post_1",
            author_id="user_1",
            title="Design Review",
            metadata={"priority": "high"},
        )
        assert event.event_type == AgentEventType.BLACKBOARD_POST_CREATED
        d = event.to_event_dict()
        assert d["type"] == "blackboard_post_created"
        assert d["data"]["post_id"] == "post_1"
        assert d["data"]["title"] == "Design Review"

    def test_post_created_defaults(self) -> None:
        event = BlackboardPostCreatedEvent(
            workspace_id="ws_1",
            post_id="post_1",
        )
        assert event.author_id is None
        assert event.title is None
        assert event.metadata == {}

    def test_post_updated_event(self) -> None:
        event = BlackboardPostUpdatedEvent(
            workspace_id="ws_1",
            post_id="post_1",
            changes={"title": "Updated Title"},
        )
        assert event.event_type == AgentEventType.BLACKBOARD_POST_UPDATED
        d = event.to_event_dict()
        assert d["type"] == "blackboard_post_updated"
        assert d["data"]["changes"] == {"title": "Updated Title"}

    def test_post_deleted_event(self) -> None:
        event = BlackboardPostDeletedEvent(
            workspace_id="ws_1",
            post_id="post_1",
        )
        assert event.event_type == AgentEventType.BLACKBOARD_POST_DELETED
        d = event.to_event_dict()
        assert d["type"] == "blackboard_post_deleted"

    def test_reply_created_event(self) -> None:
        event = BlackboardReplyCreatedEvent(
            workspace_id="ws_1",
            post_id="post_1",
            reply_id="reply_1",
            author_id="user_1",
        )
        assert event.event_type == AgentEventType.BLACKBOARD_REPLY_CREATED
        d = event.to_event_dict()
        assert d["type"] == "blackboard_reply_created"
        assert d["data"]["reply_id"] == "reply_1"

    def test_reply_deleted_event(self) -> None:
        event = BlackboardReplyDeletedEvent(
            workspace_id="ws_1",
            post_id="post_1",
            reply_id="reply_1",
        )
        assert event.event_type == AgentEventType.BLACKBOARD_REPLY_DELETED
        d = event.to_event_dict()
        assert d["type"] == "blackboard_reply_deleted"


@pytest.mark.unit
class TestWorkspaceTaskEvents:
    def test_task_created_event(self) -> None:
        event = WorkspaceTaskCreatedEvent(
            workspace_id="ws_1",
            task_id="task_1",
            title="Fix bug",
            assignee_id="user_1",
            metadata={"priority": "p0"},
        )
        assert event.event_type == AgentEventType.WORKSPACE_TASK_CREATED
        d = event.to_event_dict()
        assert d["type"] == "workspace_task_created"
        assert d["data"]["title"] == "Fix bug"

    def test_task_updated_event(self) -> None:
        event = WorkspaceTaskUpdatedEvent(
            workspace_id="ws_1",
            task_id="task_1",
            changes={"description": "Updated"},
        )
        assert event.event_type == AgentEventType.WORKSPACE_TASK_UPDATED
        d = event.to_event_dict()
        assert d["type"] == "workspace_task_updated"

    def test_task_deleted_event(self) -> None:
        event = WorkspaceTaskDeletedEvent(
            workspace_id="ws_1",
            task_id="task_1",
        )
        assert event.event_type == AgentEventType.WORKSPACE_TASK_DELETED
        d = event.to_event_dict()
        assert d["type"] == "workspace_task_deleted"

    def test_task_status_changed_event(self) -> None:
        event = WorkspaceTaskStatusChangedEvent(
            workspace_id="ws_1",
            task_id="task_1",
            old_status="open",
            new_status="in_progress",
            changed_by="user_1",
        )
        assert event.event_type == AgentEventType.WORKSPACE_TASK_STATUS_CHANGED
        d = event.to_event_dict()
        assert d["type"] == "workspace_task_status_changed"
        assert d["data"]["old_status"] == "open"
        assert d["data"]["new_status"] == "in_progress"
        assert d["data"]["changed_by"] == "user_1"

    def test_task_status_changed_defaults(self) -> None:
        event = WorkspaceTaskStatusChangedEvent(
            workspace_id="ws_1",
            task_id="task_1",
            new_status="done",
        )
        assert event.old_status is None
        assert event.changed_by is None

    def test_task_assigned_event(self) -> None:
        event = WorkspaceTaskAssignedEvent(
            workspace_id="ws_1",
            task_id="task_1",
            assignee_id="agent_1",
            assigned_by="user_1",
        )
        assert event.event_type == AgentEventType.WORKSPACE_TASK_ASSIGNED
        d = event.to_event_dict()
        assert d["type"] == "workspace_task_assigned"
        assert d["data"]["assignee_id"] == "agent_1"
        assert d["data"]["assigned_by"] == "user_1"


@pytest.mark.unit
class TestTopologyAndMessageEvents:
    def test_topology_updated_event(self) -> None:
        event = TopologyUpdatedEvent(
            workspace_id="ws_1",
            action="add_node",
            node_id="node_1",
            metadata={"q": 0, "r": 1},
        )
        assert event.event_type == AgentEventType.TOPOLOGY_UPDATED
        d = event.to_event_dict()
        assert d["type"] == "topology_updated"
        assert d["data"]["action"] == "add_node"
        assert d["data"]["node_id"] == "node_1"

    def test_topology_updated_defaults(self) -> None:
        event = TopologyUpdatedEvent(workspace_id="ws_1")
        assert event.action == ""
        assert event.node_id is None
        assert event.edge_id is None
        assert event.metadata == {}

    def test_message_created_event(self) -> None:
        event = WorkspaceMessageCreatedEvent(
            workspace_id="ws_1",
            message_id="msg_1",
            sender_id="user_1",
            sender_type="human",
            content="Hello @CodeReviewer",
            mentions=["CodeReviewer"],
        )
        assert event.event_type == AgentEventType.WORKSPACE_MESSAGE_CREATED
        d = event.to_event_dict()
        assert d["type"] == "workspace_message_created"
        assert d["data"]["content"] == "Hello @CodeReviewer"
        assert d["data"]["mentions"] == ["CodeReviewer"]
        assert d["data"]["sender_type"] == "human"

    def test_message_created_defaults(self) -> None:
        event = WorkspaceMessageCreatedEvent(
            workspace_id="ws_1",
            message_id="msg_1",
            sender_id="user_1",
        )
        assert event.sender_type == "human"
        assert event.content == ""
        assert event.mentions == []


@pytest.mark.unit
class TestWorkspaceEventSerialization:
    def test_all_events_have_timestamp(self) -> None:
        events = [
            WorkspaceMemberJoinedEvent(workspace_id="ws", member_id="m"),
            WorkspaceMemberLeftEvent(workspace_id="ws", member_id="m"),
            WorkspaceUpdatedEvent(workspace_id="ws"),
            WorkspaceDeletedEvent(workspace_id="ws"),
            WorkspaceAgentBoundEvent(workspace_id="ws", agent_id="a"),
            WorkspaceAgentUnboundEvent(workspace_id="ws", agent_id="a"),
            BlackboardPostCreatedEvent(workspace_id="ws", post_id="p"),
            BlackboardPostUpdatedEvent(workspace_id="ws", post_id="p"),
            BlackboardPostDeletedEvent(workspace_id="ws", post_id="p"),
            BlackboardReplyCreatedEvent(workspace_id="ws", post_id="p", reply_id="r"),
            BlackboardReplyDeletedEvent(workspace_id="ws", post_id="p", reply_id="r"),
            WorkspaceTaskCreatedEvent(workspace_id="ws", task_id="t"),
            WorkspaceTaskUpdatedEvent(workspace_id="ws", task_id="t"),
            WorkspaceTaskDeletedEvent(workspace_id="ws", task_id="t"),
            WorkspaceTaskStatusChangedEvent(workspace_id="ws", task_id="t", new_status="done"),
            WorkspaceTaskAssignedEvent(workspace_id="ws", task_id="t", assignee_id="a"),
            TopologyUpdatedEvent(workspace_id="ws"),
            WorkspaceMessageCreatedEvent(workspace_id="ws", message_id="m", sender_id="s"),
        ]
        for event in events:
            d = event.to_event_dict()
            assert "timestamp" in d, f"{type(event).__name__} missing timestamp"
            assert "type" in d, f"{type(event).__name__} missing type"
            assert "data" in d, f"{type(event).__name__} missing data"
            assert "event_type" not in d["data"], (
                f"{type(event).__name__} leaked event_type into data"
            )
            assert "timestamp" not in d["data"], (
                f"{type(event).__name__} leaked timestamp into data"
            )

    def test_all_events_are_frozen(self) -> None:
        event = WorkspaceMemberJoinedEvent(workspace_id="ws", member_id="m")
        with pytest.raises(Exception):
            event.workspace_id = "changed"
