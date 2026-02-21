"""Rich Feishu Card builders for agent events.

Provides structured Feishu Card 2.0 JSON for:
- Task progress summary (task list with status icons)
- Artifact ready notification (download link / preview)
- Error notification with optional retry
"""
from typing import Any, Dict, List, Optional


class RichCardBuilder:
    """Builds Feishu interactive cards for common agent events."""

    # Status icon mapping
    _STATUS_ICONS = {
        "completed": "✅",
        "done": "✅",
        "in_progress": "🔄",
        "running": "🔄",
        "failed": "❌",
        "error": "❌",
        "blocked": "⏸️",
        "pending": "⬜",
        "cancelled": "🚫",
    }

    def build_task_progress_card(
        self,
        tasks: List[Dict[str, Any]],
        *,
        title: str = "Task Progress",
        conversation_id: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Build a task list summary card.

        Args:
            tasks: List of task dicts with ``title``, ``status``, and
                optionally ``description``.
            title: Card header title.
            conversation_id: Optional conversation ID for context.

        Returns:
            Feishu Card 2.0 JSON dict, or None if no tasks.
        """
        if not tasks:
            return None

        display_tasks = tasks[:15]

        # Count by status
        total = len(tasks)
        done = sum(
            1 for t in tasks if t.get("status") in ("completed", "done")
        )
        in_progress = sum(
            1 for t in tasks if t.get("status") in ("in_progress", "running")
        )
        failed = sum(
            1 for t in tasks if t.get("status") in ("failed", "error")
        )

        # Build summary line
        summary = f"**{done}/{total}** completed"
        if in_progress:
            summary += f" | {in_progress} in progress"
        if failed:
            summary += f" | {failed} failed"

        # Build task lines
        lines: List[str] = []
        for task in display_tasks:
            status = task.get("status", "pending")
            icon = self._STATUS_ICONS.get(status, "⬜")
            task_title = task.get("title", "Untitled")
            lines.append(f"{icon} {task_title}")

        if len(tasks) > 15:
            lines.append(f"... and {len(tasks) - 15} more")

        task_list_text = "\n".join(lines)

        # Determine header color by overall status
        if failed > 0:
            template = "red"
        elif done == total:
            template = "green"
        elif in_progress > 0:
            template = "blue"
        else:
            template = "grey"

        return {
            "header": {
                "template": template,
                "title": {"tag": "plain_text", "content": title},
            },
            "elements": [
                {"tag": "markdown", "content": summary},
                {"tag": "hr"},
                {"tag": "markdown", "content": task_list_text},
            ],
        }

    def build_artifact_card(
        self,
        name: str,
        *,
        url: str = "",
        file_type: str = "",
        size: str = "",
        description: str = "",
    ) -> Dict[str, Any]:
        """Build an artifact ready notification card.

        Args:
            name: Artifact file name.
            url: Download URL (if available).
            file_type: File type or extension.
            size: Human-readable file size.
            description: Optional description.

        Returns:
            Feishu Card 2.0 JSON dict.
        """
        meta_parts: List[str] = []
        if file_type:
            meta_parts.append(f"Type: {file_type}")
        if size:
            meta_parts.append(f"Size: {size}")

        content = f"**{name}**"
        if description:
            content += f"\n{description}"
        if meta_parts:
            content += f"\n{' | '.join(meta_parts)}"

        elements: List[Dict[str, Any]] = [
            {"tag": "markdown", "content": content},
        ]

        if url:
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "Download"},
                            "type": "primary",
                            "url": url,
                        },
                    ],
                }
            )

        return {
            "header": {
                "template": "green",
                "title": {"tag": "plain_text", "content": "Artifact Ready"},
            },
            "elements": elements,
        }

    def build_error_card(
        self,
        message: str,
        *,
        error_code: str = "",
        conversation_id: str = "",
        retryable: bool = False,
    ) -> Dict[str, Any]:
        """Build an error notification card.

        Args:
            message: Error message.
            error_code: Optional error code.
            conversation_id: Optional conversation ID for retry.
            retryable: Whether to show a retry button.

        Returns:
            Feishu Card 2.0 JSON dict.
        """
        content = f"**Error**: {message}"
        if error_code:
            content += f"\nCode: `{error_code}`"

        elements: List[Dict[str, Any]] = [
            {"tag": "markdown", "content": content},
        ]

        if retryable and conversation_id:
            elements.append(
                {
                    "tag": "action",
                    "actions": [
                        {
                            "tag": "button",
                            "text": {"tag": "plain_text", "content": "Retry"},
                            "type": "primary",
                            "value": {
                                "action": "retry",
                                "conversation_id": conversation_id,
                            },
                        },
                    ],
                }
            )

        return {
            "header": {
                "template": "red",
                "title": {"tag": "plain_text", "content": "Error"},
            },
            "elements": elements,
        }
