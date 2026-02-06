"""Plan entity for Plan Mode planning documents.

This module defines the Plan aggregate root for the Plan Mode feature.
A Plan is a Markdown document created during the planning phase that
captures the exploration results, design decisions, and implementation steps.

Note: This is different from WorkPlan which is used for tracking multi-step
task execution. Plan is the document created and edited in Plan Mode.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict

from src.domain.shared_kernel import DomainException, Entity


class PlanDocumentStatus(str, Enum):
    """Status of a Plan document in Plan Mode.

    DRAFT: The plan is being created/edited in Plan Mode
    REVIEWING: The plan is complete and awaiting user approval
    APPROVED: The user approved the plan, ready to switch to Build Mode
    ARCHIVED: The plan has been archived (after implementation or cancelled)
    """

    DRAFT = "draft"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    ARCHIVED = "archived"


class InvalidPlanStateError(DomainException):
    """Raised when an invalid state transition is attempted."""

    def __init__(self, current_status: PlanDocumentStatus, action: str):
        super().__init__(f"Cannot {action} a plan with status '{current_status.value}'")
        self.current_status = current_status
        self.action = action


class PlanNotFoundError(DomainException):
    """Raised when a plan is not found."""

    def __init__(self, plan_id: str):
        super().__init__(f"Plan with id '{plan_id}' not found")
        self.plan_id = plan_id


class AlreadyInPlanModeError(DomainException):
    """Raised when trying to enter Plan Mode while already in it."""

    def __init__(self, conversation_id: str):
        super().__init__(f"Conversation '{conversation_id}' is already in Plan Mode")
        self.conversation_id = conversation_id


class NotInPlanModeError(DomainException):
    """Raised when trying to exit Plan Mode while not in it."""

    def __init__(self, conversation_id: str):
        super().__init__(f"Conversation '{conversation_id}' is not in Plan Mode")
        self.conversation_id = conversation_id


@dataclass(kw_only=True)
class Plan(Entity):
    """
    A Plan document created during Plan Mode.

    Plan is an aggregate root that represents the planning document
    created when an agent enters Plan Mode. It captures:
    - Exploration findings from code reading
    - Design decisions and rationale
    - Implementation steps and file modifications
    - Verification strategies

    The Plan follows a lifecycle: DRAFT -> REVIEWING -> APPROVED -> ARCHIVED
    """

    conversation_id: str
    title: str
    content: str  # Markdown format
    status: PlanDocumentStatus = PlanDocumentStatus.DRAFT
    version: int = 1  # Optimistic locking version control
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def update_content(self, new_content: str) -> None:
        """
        Update the plan content and increment version.

        Args:
            new_content: New Markdown content for the plan
        """
        if self.status == PlanDocumentStatus.APPROVED:
            raise InvalidPlanStateError(self.status, "update content of")

        self.content = new_content
        self.version += 1
        self.updated_at = datetime.now(timezone.utc)

    def append_content(self, additional_content: str) -> None:
        """
        Append content to the plan.

        Args:
            additional_content: Content to append
        """
        self.update_content(self.content + "\n\n" + additional_content)

    def mark_reviewing(self) -> None:
        """Mark the plan as ready for review."""
        if self.status != PlanDocumentStatus.DRAFT:
            raise InvalidPlanStateError(self.status, "mark for review")

        self.status = PlanDocumentStatus.REVIEWING
        self.updated_at = datetime.now(timezone.utc)

    def approve(self) -> None:
        """
        Approve the plan, allowing transition to Build Mode.

        Only plans in DRAFT or REVIEWING status can be approved.
        """
        if self.status == PlanDocumentStatus.APPROVED:
            return  # Already approved, idempotent

        if self.status == PlanDocumentStatus.ARCHIVED:
            raise InvalidPlanStateError(self.status, "approve")

        self.status = PlanDocumentStatus.APPROVED
        self.updated_at = datetime.now(timezone.utc)

    def archive(self) -> None:
        """Archive the plan after implementation or cancellation."""
        self.status = PlanDocumentStatus.ARCHIVED
        self.updated_at = datetime.now(timezone.utc)

    def add_metadata(self, key: str, value: Any) -> None:
        """
        Add metadata to the plan (e.g., exploration records, file references).

        Args:
            key: Metadata key
            value: Metadata value
        """
        self.metadata[key] = value
        self.updated_at = datetime.now(timezone.utc)

    def add_explored_file(self, file_path: str) -> None:
        """
        Record a file that was explored during planning.

        Args:
            file_path: Path to the explored file
        """
        if "explored_files" not in self.metadata:
            self.metadata["explored_files"] = []
        if file_path not in self.metadata["explored_files"]:
            self.metadata["explored_files"].append(file_path)
            self.updated_at = datetime.now(timezone.utc)

    def add_critical_file(self, file_path: str, modification_type: str = "modify") -> None:
        """
        Record a critical file that needs modification.

        Args:
            file_path: Path to the file
            modification_type: Type of modification (create/modify/delete)
        """
        if "critical_files" not in self.metadata:
            self.metadata["critical_files"] = []
        file_entry = {"path": file_path, "type": modification_type}
        if file_entry not in self.metadata["critical_files"]:
            self.metadata["critical_files"].append(file_entry)
            self.updated_at = datetime.now(timezone.utc)

    @property
    def is_editable(self) -> bool:
        """Check if the plan can be edited."""
        return self.status in (PlanDocumentStatus.DRAFT, PlanDocumentStatus.REVIEWING)

    @property
    def is_approvable(self) -> bool:
        """Check if the plan can be approved."""
        return self.status in (PlanDocumentStatus.DRAFT, PlanDocumentStatus.REVIEWING)

    @classmethod
    def create_default(cls, conversation_id: str, title: str) -> "Plan":
        """
        Create a new plan with default template content.

        Args:
            conversation_id: ID of the parent conversation
            title: Title for the plan

        Returns:
            New Plan instance with template content
        """
        default_content = f"""# {title}

## 概述
[总结用户需求和目标...]

## 代码探索
[记录探索发现...]

## 架构设计
[设计方案和技术决策...]

## 实施步骤
1. [步骤 1]
2. [步骤 2]
3. [步骤 3]

## 关键文件
[列出需要创建或修改的文件...]

## 验证方案
[如何测试和验证实现...]
"""
        return cls(
            conversation_id=conversation_id,
            title=title,
            content=default_content,
            status=PlanDocumentStatus.DRAFT,
        )
