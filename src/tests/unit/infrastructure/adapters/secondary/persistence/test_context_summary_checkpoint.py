from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from src.domain.model.agent.conversation.context_summary import ContextSummary
from src.infrastructure.adapters.secondary.persistence.sql_context_summary_adapter import (
    SqlContextSummaryAdapter,
)


@pytest.mark.unit
@pytest.mark.parametrize("cutoff, should_write", [(10, False), (9, False), (11, True)])
async def test_save_locks_row_and_preserves_newest_checkpoint(cutoff, should_write):
    session = AsyncMock()
    read = MagicMock()
    read.scalar_one_or_none.return_value = {
        "context_summary": {"summary_text": "saved", "messages_covered_up_to": 10},
        "other": "keep",
    }
    session.execute.return_value = read
    await SqlContextSummaryAdapter(session).save_summary(
        "conversation", ContextSummary("incoming", 1, cutoff, 1)
    )
    select = session.execute.await_args_list[0].args[0]
    assert "FOR UPDATE" in str(select.compile(dialect=postgresql.dialect()))
    assert session.execute.await_count == (2 if should_write else 1)
    if should_write:
        statement = session.execute.await_args_list[1].args[0]
        assert statement.compile().params["meta"]["other"] == "keep"
