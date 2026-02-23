"""Tests for RichCardBuilder."""

import pytest

from src.infrastructure.adapters.secondary.channels.feishu.rich_cards import (
    RichCardBuilder,
)


@pytest.fixture
def builder() -> RichCardBuilder:
    return RichCardBuilder()


@pytest.mark.unit
class TestTaskProgressCard:
    def test_empty_tasks_returns_none(self, builder: RichCardBuilder) -> None:
        assert builder.build_task_progress_card([]) is None

    def test_all_done_green_header(self, builder: RichCardBuilder) -> None:
        tasks = [
            {"title": "Setup DB", "status": "completed"},
            {"title": "Write tests", "status": "done"},
        ]
        card = builder.build_task_progress_card(tasks)
        assert card is not None
        assert card["schema"] == "2.0"
        assert card["config"] == {"wide_screen_mode": True}
        assert card["header"]["template"] == "green"
        assert "2/2" in card["body"]["elements"][0]["content"]

    def test_in_progress_blue_header(self, builder: RichCardBuilder) -> None:
        tasks = [
            {"title": "Setup DB", "status": "completed"},
            {"title": "Deploy", "status": "in_progress"},
        ]
        card = builder.build_task_progress_card(tasks)
        assert card["schema"] == "2.0"
        assert card["header"]["template"] == "blue"
        assert "1 in progress" in card["body"]["elements"][0]["content"]

    def test_failed_red_header(self, builder: RichCardBuilder) -> None:
        tasks = [
            {"title": "Setup DB", "status": "completed"},
            {"title": "Deploy", "status": "failed"},
        ]
        card = builder.build_task_progress_card(tasks)
        assert card["schema"] == "2.0"
        assert card["header"]["template"] == "red"
        assert "1 failed" in card["body"]["elements"][0]["content"]

    def test_all_pending_grey_header(self, builder: RichCardBuilder) -> None:
        tasks = [{"title": "Task 1", "status": "pending"}]
        card = builder.build_task_progress_card(tasks)
        assert card["schema"] == "2.0"
        assert card["header"]["template"] == "grey"

    def test_status_icons(self, builder: RichCardBuilder) -> None:
        tasks = [
            {"title": "Done task", "status": "completed"},
            {"title": "Running task", "status": "in_progress"},
            {"title": "Failed task", "status": "failed"},
            {"title": "Pending task", "status": "pending"},
        ]
        card = builder.build_task_progress_card(tasks)
        task_text = card["body"]["elements"][2]["content"]
        assert "Done task" in task_text
        assert "Running task" in task_text
        assert "Failed task" in task_text
        assert "Pending task" in task_text

    def test_truncates_at_15(self, builder: RichCardBuilder) -> None:
        tasks = [{"title": f"Task {i}", "status": "pending"} for i in range(20)]
        card = builder.build_task_progress_card(tasks)
        task_text = card["body"]["elements"][2]["content"]
        assert "... and 5 more" in task_text

    def test_custom_title(self, builder: RichCardBuilder) -> None:
        card = builder.build_task_progress_card(
            [{"title": "X", "status": "pending"}],
            title="Deploy Progress",
        )
        assert card["schema"] == "2.0"
        assert card["header"]["title"]["content"] == "Deploy Progress"


@pytest.mark.unit
class TestArtifactCard:
    def test_basic_artifact(self, builder: RichCardBuilder) -> None:
        card = builder.build_artifact_card("report.pdf")
        assert card["schema"] == "2.0"
        assert card["header"]["template"] == "green"
        assert card["header"]["title"]["content"] == "Artifact Ready"
        assert "**report.pdf**" in card["body"]["elements"][0]["content"]
        assert len(card["body"]["elements"]) == 1  # No download button

    def test_artifact_with_url(self, builder: RichCardBuilder) -> None:
        card = builder.build_artifact_card("report.pdf", url="https://example.com/download")
        assert card["schema"] == "2.0"
        assert len(card["body"]["elements"]) == 2
        button = card["body"]["elements"][1]["actions"][0]
        assert button["text"]["content"] == "Download"
        assert button["url"] == "https://example.com/download"

    def test_artifact_with_metadata(self, builder: RichCardBuilder) -> None:
        card = builder.build_artifact_card(
            "data.csv",
            file_type="CSV",
            size="2.3 MB",
            description="Monthly sales report",
        )
        assert card["schema"] == "2.0"
        content = card["body"]["elements"][0]["content"]
        assert "Type: CSV" in content
        assert "Size: 2.3 MB" in content
        assert "Monthly sales report" in content


@pytest.mark.unit
class TestErrorCard:
    def test_basic_error(self, builder: RichCardBuilder) -> None:
        card = builder.build_error_card("Connection timeout")
        assert card["schema"] == "2.0"
        assert card["header"]["template"] == "red"
        assert card["header"]["title"]["content"] == "Error"
        assert "**Error**: Connection timeout" in card["body"]["elements"][0]["content"]
        assert len(card["body"]["elements"]) == 1  # No retry button

    def test_error_with_code(self, builder: RichCardBuilder) -> None:
        card = builder.build_error_card("Rate limited", error_code="429")
        assert card["schema"] == "2.0"
        content = card["body"]["elements"][0]["content"]
        assert "Code: `429`" in content

    def test_error_with_retry(self, builder: RichCardBuilder) -> None:
        card = builder.build_error_card(
            "Timeout",
            conversation_id="conv-1",
            retryable=True,
        )
        assert card["schema"] == "2.0"
        assert len(card["body"]["elements"]) == 2
        button = card["body"]["elements"][1]["actions"][0]
        assert button["text"]["content"] == "Retry"
        assert button["value"]["action"] == "retry"
        assert button["value"]["conversation_id"] == "conv-1"

    def test_error_retryable_no_conversation_id(self, builder: RichCardBuilder) -> None:
        card = builder.build_error_card("Timeout", retryable=True)
        assert card["schema"] == "2.0"
        assert len(card["body"]["elements"]) == 1  # No retry without conversation_id
