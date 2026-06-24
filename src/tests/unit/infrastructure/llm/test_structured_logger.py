import logging

import pytest

from src.infrastructure.llm.structured_logger import StructuredLLMLogger


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def captured_logger() -> tuple[StructuredLLMLogger, _ListHandler]:
    base_logger = logging.getLogger("test.structured_llm_logger")
    base_logger.handlers.clear()
    base_logger.propagate = False
    base_logger.setLevel(logging.DEBUG)
    handler = _ListHandler()
    base_logger.addHandler(handler)
    return StructuredLLMLogger(base_logger), handler


def test_log_call_error_without_start_redacts_exception_text(
    captured_logger: tuple[StructuredLLMLogger, _ListHandler],
) -> None:
    llm_logger, handler = captured_logger
    secret = "structured-logger-missing-start-secret-13579"

    llm_logger.log_call_error(
        request_id="missing-start",
        error=RuntimeError(f"provider echoed prompt {secret}"),
    )

    assert len(handler.records) == 1
    record = handler.records[0]
    assert secret not in record.getMessage()
    assert "error_type=RuntimeError" in record.getMessage()


def test_log_call_error_redacts_message_and_extra(
    captured_logger: tuple[StructuredLLMLogger, _ListHandler],
) -> None:
    llm_logger, handler = captured_logger
    secret = "structured-logger-active-secret-24680"
    request_id = llm_logger.log_call_start(
        provider="openai",
        model="gpt-test",
        request_id="active-call",
    )

    llm_logger.log_call_error(
        request_id=request_id,
        error=RuntimeError(f"provider echoed prompt {secret}"),
    )

    error_record = handler.records[-1]
    assert secret not in error_record.getMessage()
    assert "RuntimeError" in error_record.getMessage()
    assert error_record.error_message is None
    assert error_record.error_type == "RuntimeError"
