"""Bounded goal candidate sensing and scoring for workspace-agent autonomy.

Agent-First iron rule (AGENTS.md): semantic verdicts (e.g. "this is a new
goal to formalize" vs "this is chatter to reject") must come from an agent
tool-call, not from keyword regex or hand-tuned score thresholds.

This service is purely **evidence-gathering**:

* Existing goal roots / objectives (resolved by DB ID) are emitted with
  ``decision="adopt_existing_goal"`` — this is a structural lookup, not a
  semantic verdict.
* Inferred signals from blackboard posts and messages are always emitted
  with ``decision="defer"``. The downstream Leader agent is responsible
  for rendering the final verdict via an explicit planning tool-call
  (``WorkspaceTaskCommandService.create_task`` or equivalent). The
  materialisation service will skip any ``defer`` candidate automatically.

Freshness, urgency, and priority scores remain (they are deterministic
arithmetic over timestamps / enum metadata and do not render a verdict).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from src.application.schemas.workspace_agent_autonomy import (
    GoalCandidateRecordModel,
    SourceBreakdownItemModel,
)
from src.application.services.workspace_goal_sensing_contract import (
    ADOPT_EXISTING_GOAL,
    BLACKBOARD_SIGNAL,
    CONVERGED_SIGNAL,
    DEFER,
    EXISTING_OBJECTIVE,
    EXISTING_ROOT_TASK,
    FORMALIZE_NEW_GOAL,
    MESSAGE_SIGNAL,
)
from src.domain.model.workspace.blackboard_post import BlackboardPost
from src.domain.model.workspace.cyber_objective import CyberObjective
from src.domain.model.workspace.workspace_message import WorkspaceMessage
from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    TASK_ROLE,
)

# Neutral evidence weights for inferred candidates (no verdict semantics).
# The numbers influence ranking only; they never drive a decision.
_INFERRED_POST_EVIDENCE = 0.5
_INFERRED_MESSAGE_EVIDENCE = 0.4

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
    """Produce ranked goal candidates from existing goals and workspace signals.

    Inferred candidates are always deferred to an agent tool-call decision
    (see module docstring). The ranking order still surfaces the strongest
    evidence first so the agent can triage efficiently.
    """

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

        drafts: list[_DraftCandidate] = []
        drafts.extend(self._task_candidates(tasks, current_time))
        drafts.extend(self._objective_candidates(objectives, current_time))
        drafts.extend(self._post_candidates(posts, current_time))
        drafts.extend(self._message_candidates(messages, current_time))

        return self._collapse_candidates(drafts)

    def _task_candidates(self, tasks: list[WorkspaceTask], now: datetime) -> list[_DraftCandidate]:
        candidates: list[_DraftCandidate] = []
        for task in tasks:
            if not self._is_open_root_task(task):
                continue
            candidates.append(
                _DraftCandidate(
                    text=task.title,
                    source_type=EXISTING_ROOT_TASK,
                    source_ref=f"task:{task.id}",
                    score=1.0,
                    freshness=self._freshness_score(task.updated_at or task.created_at, now),
                    urgency=self._priority_score(task),
                    decision=cast(CandidateDecision, ADOPT_EXISTING_GOAL),
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
                    source_type=EXISTING_OBJECTIVE,
                    source_ref=f"objective:{objective.id}",
                    score=0.9,
                    freshness=self._freshness_score(
                        objective.updated_at or objective.created_at,
                        now,
                    ),
                    urgency=max(0.4, 1.0 - objective.progress),
                    decision=cast(CandidateDecision, ADOPT_EXISTING_GOAL),
                    candidate_kind="existing",
                )
            )
        return candidates

    def _post_candidates(
        self,
        posts: list[BlackboardPost],
        now: datetime,
    ) -> list[_DraftCandidate]:
        candidates: list[_DraftCandidate] = []
        for post in posts:
            text = self._post_candidate_text(post)
            candidates.append(
                _DraftCandidate(
                    text=text,
                    source_type=BLACKBOARD_SIGNAL,
                    source_ref=f"blackboard:{post.id}",
                    score=_INFERRED_POST_EVIDENCE,
                    freshness=self._freshness_score(post.updated_at or post.created_at, now),
                    urgency=0.8 if post.is_pinned else 0.6,
                    decision=cast(CandidateDecision, DEFER),
                    candidate_kind="inferred",
                )
            )
        return candidates

    def _message_candidates(
        self,
        messages: list[WorkspaceMessage],
        now: datetime,
    ) -> list[_DraftCandidate]:
        candidates: list[_DraftCandidate] = []
        for message in messages:
            candidates.append(
                _DraftCandidate(
                    text=message.content,
                    source_type=MESSAGE_SIGNAL,
                    source_ref=f"message:{message.id}",
                    score=_INFERRED_MESSAGE_EVIDENCE,
                    freshness=self._freshness_score(message.created_at, now),
                    urgency=0.6,
                    decision=cast(CandidateDecision, DEFER),
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
            # Converged_signal is a structural cue ("same normalized text appeared in >=2
            # distinct sources"): pure set-membership / count, no verdict semantics.
            distinct_sources = {item.source_type for item in group}
            evidence_strength = primary.score
            source_type: SignalSource = cast(SignalSource, primary.source_type)
            converged = (
                primary.candidate_kind == "inferred"
                and len(group) >= 2
                and len(distinct_sources) >= 2
            )
            if converged:
                evidence_strength = min(1.0, primary.score + 0.15)
                source_type = cast(SignalSource, CONVERGED_SIGNAL)

            # Agent-First: sensing never promotes inferred candidates to
            # formalize/reject here. The Leader agent decides via an explicit
            # tool-call. Inferred candidates always remain "defer".
            decision: CandidateDecision = primary.decision

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
                            bonus_applied=(0.15 if converged and item is primary else None),
                        )
                        for item in group
                    ],
                    freshness=max(item.freshness for item in group),
                    urgency=max(item.urgency for item in group),
                    user_intent_confidence=evidence_strength,
                    formalizable=decision == FORMALIZE_NEW_GOAL,
                    decision=decision,
                )
            )

        return sorted(
            candidates,
            key=lambda candidate: (
                candidate.decision != ADOPT_EXISTING_GOAL,
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
