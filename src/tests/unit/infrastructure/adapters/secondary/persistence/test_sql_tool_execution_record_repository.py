"""
Tests for V2 SqlToolExecutionRecordRepository using BaseRepository.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import ToolExecutionRecord
from src.infrastructure.adapters.secondary.persistence.sql_tool_execution_record_repository import (
    SqlToolExecutionRecordRepository,
)


@pytest.fixture
async def v2_tool_record_repo(v2_db_session: AsyncSession) -> SqlToolExecutionRecordRepository:
    """Create a V2 tool execution record repository for testing."""
    return SqlToolExecutionRecordRepository(v2_db_session)


class TestSqlToolExecutionRecordRepositoryCreate:
    """Tests for creating tool execution records."""

    @pytest.mark.asyncio
    async def test_save_new_record(self, v2_tool_record_repo: SqlToolExecutionRecordRepository):
        """Test saving a new tool execution record."""
        record = ToolExecutionRecord(
            id="record-test-1",
            conversation_id="conv-1",
            message_id="msg-1",
            call_id="call-1",
            tool_name="test_tool",
            tool_input={"query": "test"},
            tool_output=None,
            status="pending",
            error=None,
            step_number=1,
            sequence_number=1,
            started_at=datetime.now(timezone.utc),
            completed_at=None,
            duration_ms=None,
        )

        await v2_tool_record_repo.save(record)

        result = await v2_tool_record_repo.find_by_id("record-test-1")
        assert result is not None
        assert result.tool_name == "test_tool"
        assert result.status == "pending"

    @pytest.mark.asyncio
    async def test_save_updates_existing(self, v2_tool_record_repo: SqlToolExecutionRecordRepository):
        """Test saving updates an existing record."""
        record = ToolExecutionRecord(
            id="record-update-1",
            conversation_id="conv-1",
            message_id="msg-1",
            call_id="call-update-1",
            tool_name="test_tool",
            tool_input={"query": "test"},
            tool_output=None,
            status="pending",
            error=None,
            step_number=1,
            sequence_number=1,
            started_at=datetime.now(timezone.utc),
            completed_at=None,
            duration_ms=None,
        )
        await v2_tool_record_repo.save(record)

        record.status = "completed"
        record.tool_output = "output"
        record.completed_at = datetime.now(timezone.utc)
        record.duration_ms = 100

        await v2_tool_record_repo.save(record)

        result = await v2_tool_record_repo.find_by_id("record-update-1")
        assert result.status == "completed"
        assert result.tool_output == "output"
        assert result.duration_ms == 100


class TestSqlToolExecutionRecordRepositoryFind:
    """Tests for finding records."""

    @pytest.mark.asyncio
    async def test_find_by_id_existing(self, v2_tool_record_repo: SqlToolExecutionRecordRepository):
        """Test finding a record by ID."""
        record = ToolExecutionRecord(
            id="record-find-1",
            conversation_id="conv-1",
            message_id="msg-1",
            call_id="call-find-1",
            tool_name="search",
            tool_input={},
            tool_output="result",
            status="completed",
            error=None,
            step_number=1,
            sequence_number=1,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            duration_ms=50,
        )
        await v2_tool_record_repo.save(record)

        result = await v2_tool_record_repo.find_by_id("record-find-1")
        assert result is not None
        assert result.tool_name == "search"

    @pytest.mark.asyncio
    async def test_find_by_id_not_found(self, v2_tool_record_repo: SqlToolExecutionRecordRepository):
        """Test finding a non-existent record returns None."""
        result = await v2_tool_record_repo.find_by_id("non-existent")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_by_call_id(self, v2_tool_record_repo: SqlToolExecutionRecordRepository):
        """Test finding a record by call ID."""
        record = ToolExecutionRecord(
            id="record-call-1",
            conversation_id="conv-1",
            message_id="msg-1",
            call_id="unique-call-id",
            tool_name="calculate",
            tool_input={},
            tool_output="42",
            status="completed",
            error=None,
            step_number=1,
            sequence_number=1,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            duration_ms=10,
        )
        await v2_tool_record_repo.save(record)

        result = await v2_tool_record_repo.find_by_call_id("unique-call-id")
        assert result is not None
        assert result.tool_name == "calculate"

    @pytest.mark.asyncio
    async def test_list_by_message(self, v2_tool_record_repo: SqlToolExecutionRecordRepository):
        """Test listing records by message ID."""
        for i in range(3):
            record = ToolExecutionRecord(
                id=f"record-msg-{i}",
                conversation_id="conv-1",
                message_id="msg-list-1",
                call_id=f"call-{i}",
                tool_name=f"tool-{i}",
                tool_input={},
                tool_output=f"output-{i}",
                status="completed",
                error=None,
                step_number=1,
                sequence_number=i,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                duration_ms=10,
            )
            await v2_tool_record_repo.save(record)

        results = await v2_tool_record_repo.list_by_message("msg-list-1")
        assert len(results) == 3
        # Should be ordered by sequence_number
        assert results[0].sequence_number == 0
        assert results[1].sequence_number == 1
        assert results[2].sequence_number == 2

    @pytest.mark.asyncio
    async def test_list_by_conversation(self, v2_tool_record_repo: SqlToolExecutionRecordRepository):
        """Test listing records by conversation ID."""
        for i in range(3):
            record = ToolExecutionRecord(
                id=f"record-conv-{i}",
                conversation_id="conv-list-1",
                message_id=f"msg-{i}",
                call_id=f"call-{i}",
                tool_name=f"tool-{i}",
                tool_input={},
                tool_output=f"output-{i}",
                status="completed",
                error=None,
                step_number=1,
                sequence_number=1,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                duration_ms=10,
            )
            await v2_tool_record_repo.save(record)

        results = await v2_tool_record_repo.list_by_conversation("conv-list-1")
        assert len(results) == 3


class TestSqlToolExecutionRecordRepositoryUpdate:
    """Tests for updating records."""

    @pytest.mark.asyncio
    async def test_update_status(self, v2_tool_record_repo: SqlToolExecutionRecordRepository):
        """Test updating record status."""
        record = ToolExecutionRecord(
            id="record-status-1",
            conversation_id="conv-1",
            message_id="msg-1",
            call_id="call-status-1",
            tool_name="test",
            tool_input={},
            tool_output=None,
            status="pending",
            error=None,
            step_number=1,
            sequence_number=1,
            started_at=datetime.now(timezone.utc),
            completed_at=None,
            duration_ms=None,
        )
        await v2_tool_record_repo.save(record)

        await v2_tool_record_repo.update_status(
            call_id="call-status-1",
            status="completed",
            output="done",
            duration_ms=100,
        )

        result = await v2_tool_record_repo.find_by_call_id("call-status-1")
        assert result.status == "completed"
        assert result.tool_output == "done"
        assert result.duration_ms == 100
        assert result.completed_at is not None


class TestSqlToolExecutionRecordRepositoryDelete:
    """Tests for deleting records."""

    @pytest.mark.asyncio
    async def test_delete_by_conversation(self, v2_tool_record_repo: SqlToolExecutionRecordRepository):
        """Test deleting records by conversation ID."""
        for i in range(3):
            record = ToolExecutionRecord(
                id=f"record-del-{i}",
                conversation_id="conv-del-1",
                message_id=f"msg-{i}",
                call_id=f"call-del-{i}",
                tool_name="test",
                tool_input={},
                tool_output="output",
                status="completed",
                error=None,
                step_number=1,
                sequence_number=1,
                started_at=datetime.now(timezone.utc),
                completed_at=datetime.now(timezone.utc),
                duration_ms=10,
            )
            await v2_tool_record_repo.save(record)

        await v2_tool_record_repo.delete_by_conversation("conv-del-1")

        results = await v2_tool_record_repo.list_by_conversation("conv-del-1")
        assert len(results) == 0
