"""Bounded goal candidate sensing and scoring for workspace-agent autonomy."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from src.application.schemas.workspace_agent_autonomy import (
    GoalCandidateRecordModel,
    SourceBreakdownItemModel,
)
from src.domain.model.workspace.blackboard_post import BlackboardPost
from src.domain.model.workspace.cyber_objective import CyberObjective
from src.domain.model.workspace.workspace_message import WorkspaceMessage
from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    TASK_ROLE,
)

_ACTION_PATTERN = re.compile(
    r"\b(need|must|please|todo|action|implement|fix|create|prepare|ship|deploy|write|add)\b",
    re.IGNORECASE,
)
_CASUAL_PATTERN = re.compile(
    r"\b(maybe|someday|later|think about|could|might)\b",
    re.IGNORECASE,
)

CandidateDecision = Literal[
    "adopt_existing_goal",
    "formalize_new_goal",
    "defer",
    "reject_as_non_goal",
]
CandidateKind = Literal["existing", "inferred"]
SignalSource = Literal[
    "existing_root_task",
    "existing_objective",
    "blackboard_signal",
    "message_signal",
    "converged_signal",
]


@dataclass(frozen=True)
class _DraftCandidate:
    text: str
    source_type: str
    source_ref: str
    score: float
    freshness: float
    urgency: float
    decision: CandidateDecision
    candidate_kind: CandidateKind


class WorkspaceGoalSensingService:
    """Produce ranked goal candidates from existing goals and workspace signals."""

    def sense_candidates(
        self,
        *,
        tasks: list[WorkspaceTask],
        objectives: list[CyberObjective],
        posts: list[BlackboardPost],
        messages: list[WorkspaceMessage],
        now: datetime | None = None,
    ) -> list[GoalCandidateRecordModel]:
        current_time = now or datetime.now(UTC)
        existing_root_titles = {
            self._normalize_text(task.title) for task in tasks if self._is_open_root_task(task)
        }

        drafts: list[_DraftCandidate] = []
        drafts.extend(self._task_candidates(tasks, current_time))
        drafts.extend(self._objective_candidates(objectives, current_time))
        drafts.extend(self._post_candidates(posts, current_time, existing_root_titles))
        drafts.extend(self._message_candidates(messages, current_time, existing_root_titles))

        return self._collapse_candidates(drafts)

    def _task_candidates(self, tasks: list[WorkspaceTask], now: datetime) -> list[_DraftCandidate]:
        candidates: list[_DraftCandidate] = []
        for task in tasks:
            if not self._is_open_root_task(task):
                continue
            candidates.append(
                _DraftCandidate(
                    text=task.title,
                    source_type="existing_root_task",
                    source_ref=f"task:{task.id}",
                    score=1.0,
                    freshness=self._freshness_score(task.updated_at or task.created_at, now),
                    urgency=self._priority_score(task),
                    decision="adopt_existing_goal",
                    candidate_kind="existing",
                )
            )
        return candidates

    def _objective_candidates(
        self, objectives: list[CyberObjective], now: datetime
    ) -> list[_DraftCandidate]:
        candidates: list[_DraftCandidate] = []
        for objective in objectives:
            if objective.progress >= 1.0:
                continue
            candidates.append(
                _DraftCandidate(
                    text=objective.title,
                    source_type="existing_objective",
                    source_ref=f"objective:{objective.id}",
                    score=0.9,
                    freshness=self._freshness_score(
                        objective.updated_at or objective.created_at,
                        now,
                    ),
                    urgency=max(0.4, 1.0 - objective.progress),
                    decision="adopt_existing_goal",
                    candidate_kind="existing",
                )
            )
        return candidates

    def _post_candidates(
        self,
        posts: list[BlackboardPost],
        now: datetime,
        existing_root_titles: set[str],
    ) -> list[_DraftCandidate]:
        candidates: list[_DraftCandidate] = []
        for post in posts:
            text = self._post_candidate_text(post)
            normalized = self._normalize_text(text)
            score = 0.8 if self._has_explicit_action(text) else 0.4
            decision = self._inferred_decision(score, normalized, existing_root_titles)
            candidates.append(
                _DraftCandidate(
                    text=text,
                    source_type="blackboard_signal",
                    source_ref=f"blackboard:{post.id}",
                    score=score,
                    freshness=self._freshness_score(post.updated_at or post.created_at, now),
                    urgency=0.8 if post.is_pinned else 0.6,
                    decision=decision,
                    candidate_kind="inferred",
                )
            )
        return candidates

    def _message_candidates(
        self,
        messages: list[WorkspaceMessage],
        now: datetime,
        existing_root_titles: set[str],
    ) -> list[_DraftCandidate]:
        candidates: list[_DraftCandidate] = []
        for message in messages:
            normalized = self._normalize_text(message.content)
            score = 0.7 if self._has_explicit_action(message.content) else 0.35
            decision = self._inferred_decision(score, normalized, existing_root_titles)
            candidates.append(
                _DraftCandidate(
                    text=message.content,
                    source_type="message_signal",
                    source_ref=f"message:{message.id}",
                    score=score,
                    freshness=self._freshness_score(message.created_at, now),
                    urgency=0.6,
                    decision=decision,
                    candidate_kind="inferred",
                )
            )
        return candidates

    def _collapse_candidates(self, drafts: list[_DraftCandidate]) -> list[GoalCandidateRecordModel]:
        grouped: dict[str, list[_DraftCandidate]] = defaultdict(list)
        for draft in drafts:
            grouped[self._normalize_text(draft.text)].append(draft)

        candidates: list[GoalCandidateRecordModel] = []
        for index, group in enumerate(grouped.values(), start=1):
            primary = max(group, key=lambda item: item.score)
            distinct_sources = {item.source_type for item in group if item.score >= 0.7}
            evidence_strength = primary.score
            source_type: SignalSource = cast(SignalSource, primary.source_type)
            if (
                primary.candidate_kind == "inferred"
                and len(group) >= 2
                and len(distinct_sources) >= 2
            ):
                evidence_strength = min(1.0, primary.score + 0.15)
                source_type = "converged_signal"

            decision: CandidateDecision = primary.decision
            if primary.candidate_kind == "inferred":
                if decision == "defer":
                    pass
                elif evidence_strength >= 0.75 and (
                    primary.score >= 0.8 or len(distinct_sources) >= 2
                ):
                    decision = "formalize_new_goal"
                else:
                    decision = "reject_as_non_goal"

            candidates.append(
                GoalCandidateRecordModel(
                    candidate_id=f"goal-candidate-{index}",
                    candidate_text=primary.text,
                    candidate_kind=primary.candidate_kind,
                    source_refs=[item.source_ref for item in group],
                    evidence_strength=evidence_strength,
                    source_breakdown=[
                        SourceBreakdownItemModel(
                            source_type=cast(
                                SignalSource,
                                source_type
                                if item is primary and source_type == "converged_signal"
                                else item.source_type,
                            ),
                            score=item.score,
                            ref=item.source_ref,
                            bonus_applied=(
                                0.15
                                if primary.candidate_kind == "inferred"
                                and len(group) >= 2
                                and len(distinct_sources) >= 2
                                and item is primary
                                else None
                            ),
                        )
                        for item in group
                    ],
                    freshness=max(item.freshness for item in group),
                    urgency=max(item.urgency for item in group),
                    user_intent_confidence=evidence_strength,
                    formalizable=decision == "formalize_new_goal",
                    decision=decision,
                )
            )

        return sorted(
            candidates,
            key=lambda candidate: (
                candidate.decision != "adopt_existing_goal",
                candidate.decision != "formalize_new_goal",
                -candidate.evidence_strength,
                -candidate.urgency,
                -candidate.freshness,
            ),
        )

    @staticmethod
    def _is_open_root_task(task: WorkspaceTask) -> bool:
        return (
            task.metadata.get(TASK_ROLE) == "goal_root"
            and task.archived_at is None
            and task.status != WorkspaceTaskStatus.DONE
        )

    @staticmethod
    def _post_candidate_text(post: BlackboardPost) -> str:
        return post.content.strip() or post.title.strip()

    @staticmethod
    def _normalize_text(text: str) -> str:
        return " ".join(text.lower().split())

    @staticmethod
    def _priority_score(task: WorkspaceTask) -> float:
        return {
            "P1": 1.0,
            "P2": 0.85,
            "P3": 0.7,
            "P4": 0.55,
            "": 0.5,
        }.get(task.priority.value, 0.5)

    @staticmethod
    def _freshness_score(value: datetime, now: datetime) -> float:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        age_hours = max(0.0, (now - value).total_seconds() / 3600)
        if age_hours <= 1:
            return 1.0
        if age_hours <= 24:
            return 0.8
        if age_hours <= 72:
            return 0.6
        return 0.4

    @staticmethod
    def _has_explicit_action(text: str) -> bool:
        return bool(_ACTION_PATTERN.search(text)) and not _CASUAL_PATTERN.search(text)

    def _inferred_decision(
        self,
        score: float,
        normalized_text: str,
        existing_root_titles: set[str],
    ) -> CandidateDecision:
        if any(
            normalized_text == title or normalized_text in title or title in normalized_text
            for title in existing_root_titles
        ):
            return "defer"
        if score >= 0.75:
            return "formalize_new_goal"
        return "reject_as_non_goal"
