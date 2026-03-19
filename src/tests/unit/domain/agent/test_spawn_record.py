"""Unit tests for SpawnMode and SpawnRecord domain entities."""

import dataclasses
import uuid

import pytest

from src.domain.model.agent.spawn_mode import SpawnMode
from src.domain.model.agent.spawn_record import SpawnRecord


@pytest.mark.unit
class TestSpawnMode:
    def test_spawn_mode_run_value(self):
        assert SpawnMode.RUN.value == "run"

    def test_spawn_mode_session_value(self):
        assert SpawnMode.SESSION.value == "session"

    def test_spawn_mode_str(self):
        assert str(SpawnMode.RUN) == "run"


@pytest.mark.unit
class TestSpawnRecord:
    def test_create_record_defaults(self):
        record = SpawnRecord(
            parent_agent_id="parent-1",
            child_agent_id="child-1",
            child_session_id="sess-1",
            project_id="proj-1",
        )
        parsed = uuid.UUID(record.id)
        assert parsed.version == 4
        assert record.mode == SpawnMode.RUN
        assert record.task_summary == ""
        assert record.status == "running"

    def test_create_record_custom_values(self):
        record = SpawnRecord(
            parent_agent_id="parent-1",
            child_agent_id="child-1",
            child_session_id="sess-1",
            project_id="proj-1",
            mode=SpawnMode.SESSION,
            task_summary="do thing",
            status="completed",
        )
        assert record.mode == SpawnMode.SESSION
        assert record.task_summary == "do thing"
        assert record.status == "completed"

    def test_frozen_immutability(self):
        record = SpawnRecord(
            parent_agent_id="parent-1",
            child_agent_id="child-1",
            child_session_id="sess-1",
            project_id="proj-1",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.status = "completed"  # type: ignore[misc]

    def test_to_dict_keys(self):
        record = SpawnRecord(
            parent_agent_id="parent-1",
            child_agent_id="child-1",
            child_session_id="sess-1",
            project_id="proj-1",
        )
        d = record.to_dict()
        expected_keys = {
            "id",
            "parent_agent_id",
            "child_agent_id",
            "child_session_id",
            "project_id",
            "mode",
            "task_summary",
            "status",
            "created_at",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_mode_as_string(self):
        record = SpawnRecord(
            parent_agent_id="parent-1",
            child_agent_id="child-1",
            child_session_id="sess-1",
            project_id="proj-1",
        )
        d = record.to_dict()
        assert d["mode"] == "run"
        assert isinstance(d["mode"], str)

    def test_from_dict_round_trip(self):
        record = SpawnRecord(
            parent_agent_id="parent-1",
            child_agent_id="child-1",
            child_session_id="sess-1",
            project_id="proj-1",
            mode=SpawnMode.SESSION,
            task_summary="test task",
            status="completed",
        )
        d = record.to_dict()
        restored = SpawnRecord.from_dict(d)
        assert restored.id == record.id
        assert restored.parent_agent_id == record.parent_agent_id
        assert restored.child_agent_id == record.child_agent_id
        assert restored.child_session_id == record.child_session_id
        assert restored.project_id == record.project_id
        assert restored.mode == record.mode
        assert restored.task_summary == record.task_summary
        assert restored.status == record.status

    def test_from_dict_defaults(self):
        data = {
            "parent_agent_id": "p1",
            "child_agent_id": "c1",
            "child_session_id": "s1",
            "project_id": "proj-1",
        }
        record = SpawnRecord.from_dict(data)
        assert record.mode == SpawnMode.RUN
        assert record.task_summary == ""
        assert record.status == "running"
