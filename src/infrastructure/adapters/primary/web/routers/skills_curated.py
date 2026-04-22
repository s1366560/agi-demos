"""
P2-4: Curated skill library & submission review.

Routes
------
- ``GET  /api/v1/skills/curated/`` — list active curated skills (all tenants)
- ``POST /api/v1/skills/curated/{id}/fork`` — fork into caller's tenant/project
- ``POST /api/v1/skills/{id}/submit``       — submit a private skill for review
- ``GET  /api/v1/skills/submissions/mine``  — caller's own submissions
- ``GET  /api/v1/admin/skill-submissions/`` — admin queue
- ``POST /api/v1/admin/skill-submissions/{id}/approve``
- ``POST /api/v1/admin/skill-submissions/{id}/reject``

Admin endpoints gate on ``current_user.is_superuser``.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.skill_revision import next_semver, revision_hash_of
from src.infrastructure.adapters.primary.web.dependencies import (
    get_current_user,
    get_current_user_tenant,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.adapters.secondary.persistence.models import (
    CuratedSkill,
    Skill as SkillModel,
    SkillSubmission,
    User as UserModel,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Skills/Curated"])


# --- Schemas ---------------------------------------------------------------


class CuratedSkillResponse(BaseModel):
    id: str
    semver: str
    revision_hash: str
    source_skill_id: str | None
    source_tenant_id: str | None
    approved_by: str | None
    approved_at: datetime | None
    status: str
    payload: dict[str, Any]
    created_at: datetime


class CuratedForkRequest(BaseModel):
    include_triggers: bool = Field(default=True)
    include_executor: bool = Field(default=True, description="Include tools + prompt_template")
    include_metadata: bool = Field(default=True)
    project_id: str | None = None


class SkillSubmitRequest(BaseModel):
    proposed_semver: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    submission_note: str | None = Field(default=None, max_length=2000)


class SubmissionEditRequest(BaseModel):
    """P2-4 Track D: edit a pending submission (submitter only)."""

    proposed_semver: str | None = Field(default=None, pattern=r"^\d+\.\d+\.\d+$")
    submission_note: str | None = Field(default=None, max_length=2000)
    # If the underlying skill has changed, submitter can re-snapshot by
    # passing refresh_snapshot=True; otherwise the stored snapshot is kept.
    refresh_snapshot: bool = Field(default=False)


class SubmissionResponse(BaseModel):
    id: str
    submitter_tenant_id: str
    submitter_user_id: str | None
    source_skill_id: str | None
    proposed_semver: str
    submission_note: str | None
    status: str
    reviewer_id: str | None
    review_note: str | None
    reviewed_at: datetime | None
    created_at: datetime
    skill_snapshot: dict[str, Any]


class ReviewRequest(BaseModel):
    review_note: str | None = Field(default=None, max_length=2000)
    # Optional semver bump hint — when provided, server computes the next
    # semver from the previous active curated row for the same
    # source_skill_id; when absent, submission.proposed_semver is trusted.
    bump: str | None = Field(default=None, pattern=r"^(major|minor|patch)$")


# --- Helpers ---------------------------------------------------------------


def _curated_to_response(row: CuratedSkill) -> CuratedSkillResponse:
    return CuratedSkillResponse(
        id=row.id,
        semver=row.semver,
        revision_hash=row.revision_hash,
        source_skill_id=row.source_skill_id,
        source_tenant_id=row.source_tenant_id,
        approved_by=row.approved_by,
        approved_at=row.approved_at,
        status=row.status,
        payload=row.payload,
        created_at=row.created_at,
    )


def _submission_to_response(row: SkillSubmission) -> SubmissionResponse:
    return SubmissionResponse(
        id=row.id,
        submitter_tenant_id=row.submitter_tenant_id,
        submitter_user_id=row.submitter_user_id,
        source_skill_id=row.source_skill_id,
        proposed_semver=row.proposed_semver,
        submission_note=row.submission_note,
        status=row.status,
        reviewer_id=row.reviewer_id,
        review_note=row.review_note,
        reviewed_at=row.reviewed_at,
        created_at=row.created_at,
        skill_snapshot=row.skill_snapshot,
    )


def _skill_to_snapshot(skill: SkillModel, proposed_semver: str) -> dict[str, Any]:
    return {
        "name": skill.name,
        "description": skill.description,
        "trigger_type": skill.trigger_type,
        "trigger_patterns": skill.trigger_patterns,
        "tools": skill.tools,
        "prompt_template": skill.prompt_template,
        "full_content": skill.full_content,
        "metadata": skill.metadata_json or {},
        "scope": skill.scope,
        "semver": proposed_semver,
    }


def _require_superuser(user: UserModel) -> None:
    if not bool(getattr(user, "is_superuser", False)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only superusers can review skill submissions",
        )


# --- Curated library (read + fork) ----------------------------------------


@router.get("/api/v1/skills/curated/", response_model=list[CuratedSkillResponse])
async def list_curated_skills(
    include_deprecated: bool = False,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user_tenant),
) -> list[CuratedSkillResponse]:
    stmt = select(CuratedSkill).order_by(CuratedSkill.created_at.desc())
    if not include_deprecated:
        stmt = stmt.where(CuratedSkill.status == "active")
    rows = (await db.execute(stmt)).scalars().all()
    return [_curated_to_response(r) for r in rows]


@router.post(
    "/api/v1/skills/curated/{curated_id}/fork",
    status_code=status.HTTP_201_CREATED,
)
async def fork_curated_skill(
    curated_id: str,
    data: CuratedForkRequest,
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    curated = await db.get(CuratedSkill, curated_id)
    if curated is None or curated.status != "active":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Curated skill not found",
        )

    payload = dict(curated.payload)
    name = str(payload.get("name") or "forked_skill")
    description = str(payload.get("description") or "")
    trigger_type = str(payload.get("trigger_type") or "keyword")
    trigger_patterns = payload.get("trigger_patterns") if data.include_triggers else []
    tools = payload.get("tools") if data.include_executor else []
    prompt_template = payload.get("prompt_template") if data.include_executor else None
    full_content = payload.get("full_content") if data.include_executor else None
    metadata_json = payload.get("metadata") if data.include_metadata else None

    now = datetime.now(UTC)
    new_skill = SkillModel(
        id=f"skill_{uuid.uuid4().hex}",
        tenant_id=tenant_id,
        project_id=data.project_id,
        name=name,
        description=description,
        trigger_type=trigger_type,
        trigger_patterns=trigger_patterns or [],
        tools=tools or [],
        prompt_template=prompt_template,
        full_content=full_content,
        metadata_json=metadata_json,
        scope="project" if data.project_id else "tenant",
        is_system_skill=False,
        status="active",
        parent_curated_id=curated.id,
        semver=curated.semver,
        revision_hash=curated.revision_hash,
        created_at=now,
    )
    db.add(new_skill)
    await db.commit()
    logger.info(
        "Forked curated skill %s -> %s (tenant=%s)",
        curated.id,
        new_skill.id,
        tenant_id,
    )
    return {"skill_id": new_skill.id, "parent_curated_id": curated.id}


# --- Submission flow (tenant side) ----------------------------------------


@router.post(
    "/api/v1/skills/{skill_id}/submit",
    response_model=SubmissionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_skill_for_review(
    skill_id: str,
    data: SkillSubmitRequest,
    current_user: UserModel = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> SubmissionResponse:
    skill = await db.get(SkillModel, skill_id)
    if skill is None or skill.tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Skill not found in this tenant",
        )

    snapshot = _skill_to_snapshot(skill, data.proposed_semver)
    submission = SkillSubmission(
        id=f"sub_{uuid.uuid4().hex}",
        submitter_tenant_id=tenant_id,
        submitter_user_id=current_user.id,
        source_skill_id=skill.id,
        skill_snapshot=snapshot,
        proposed_semver=data.proposed_semver,
        submission_note=data.submission_note,
        status="pending",
        created_at=datetime.now(UTC),
    )
    db.add(submission)
    await db.commit()
    logger.info("Skill %s submitted for review by tenant %s", skill.id, tenant_id)
    return _submission_to_response(submission)


@router.get(
    "/api/v1/skills/submissions/mine",
    response_model=list[SubmissionResponse],
)
async def list_my_submissions(
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[SubmissionResponse]:
    stmt = (
        select(SkillSubmission)
        .where(SkillSubmission.submitter_tenant_id == tenant_id)
        .order_by(SkillSubmission.created_at.desc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [_submission_to_response(r) for r in rows]


# --- Submission edit / withdraw (P2-4 Track D) ----------------------------


@router.patch(
    "/api/v1/skills/submissions/{submission_id}",
    response_model=SubmissionResponse,
)
async def edit_pending_submission(
    submission_id: str,
    data: SubmissionEditRequest,
    current_user: UserModel = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> SubmissionResponse:
    """Edit a pending submission. Submitter only, pending only."""
    submission = await db.get(SkillSubmission, submission_id)
    if submission is None or submission.submitter_tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
        )
    if submission.submitter_user_id not in (None, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the original submitter may edit this submission",
        )
    if submission.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot edit submission in {submission.status} state",
        )

    if data.proposed_semver is not None:
        submission.proposed_semver = data.proposed_semver
    if data.submission_note is not None:
        submission.submission_note = data.submission_note

    if data.refresh_snapshot:
        # Re-snapshot from the current source skill (if it still exists).
        if submission.source_skill_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot refresh snapshot: submission has no source_skill_id",
            )
        skill = await db.get(SkillModel, submission.source_skill_id)
        if skill is None or skill.tenant_id != tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source skill no longer exists in this tenant",
            )
        submission.skill_snapshot = _skill_to_snapshot(
            skill, submission.proposed_semver
        )

    await db.commit()
    logger.info(
        "Submission %s edited by %s (refresh=%s)",
        submission.id,
        current_user.id,
        data.refresh_snapshot,
    )
    return _submission_to_response(submission)


@router.post(
    "/api/v1/skills/submissions/{submission_id}/withdraw",
    response_model=SubmissionResponse,
)
async def withdraw_pending_submission(
    submission_id: str,
    current_user: UserModel = Depends(get_current_user),
    tenant_id: str = Depends(get_current_user_tenant),
    db: AsyncSession = Depends(get_db),
) -> SubmissionResponse:
    """Withdraw a pending submission. Submitter only, pending only."""
    submission = await db.get(SkillSubmission, submission_id)
    if submission is None or submission.submitter_tenant_id != tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
        )
    if submission.submitter_user_id not in (None, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the original submitter may withdraw this submission",
        )
    if submission.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot withdraw submission in {submission.status} state",
        )
    submission.status = "withdrawn"
    submission.reviewed_at = datetime.now(UTC)
    await db.commit()
    logger.info("Submission %s withdrawn by %s", submission.id, current_user.id)
    return _submission_to_response(submission)


@router.get(
    "/api/v1/admin/skill-submissions/",
    response_model=list[SubmissionResponse],
)
async def admin_list_submissions(
    status_filter: str = "pending",
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SubmissionResponse]:
    _require_superuser(current_user)
    stmt = (
        select(SkillSubmission)
        .where(SkillSubmission.status == status_filter)
        .order_by(SkillSubmission.created_at.asc())
    )
    rows = (await db.execute(stmt)).scalars().all()
    return [_submission_to_response(r) for r in rows]


@router.post(
    "/api/v1/admin/skill-submissions/{submission_id}/approve",
    response_model=CuratedSkillResponse,
)
async def admin_approve_submission(
    submission_id: str,
    data: ReviewRequest,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CuratedSkillResponse:
    _require_superuser(current_user)
    submission = await db.get(SkillSubmission, submission_id)
    if submission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
        )
    if submission.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Submission already {submission.status}",
        )

    # P2-4 Track D: semver bump + history. If bump provided, derive next
    # semver from the most recent ACTIVE curated row for the same
    # source_skill_id; otherwise trust the submitter's proposed_semver.
    prior_active = None
    if submission.source_skill_id is not None:
        prior_active = (
            await db.execute(
                select(CuratedSkill)
                .where(CuratedSkill.source_skill_id == submission.source_skill_id)
                .where(CuratedSkill.status == "active")
                .order_by(CuratedSkill.created_at.desc())
            )
        ).scalars().first()

    if data.bump is not None:
        prior_semver = prior_active.semver if prior_active is not None else None
        effective_semver = next_semver(prior_semver, data.bump)  # type: ignore[arg-type]
    else:
        effective_semver = submission.proposed_semver

    payload = dict(submission.skill_snapshot)
    payload["semver"] = effective_semver
    rhash = revision_hash_of(payload)

    # Content-level dedup: unique constraint on revision_hash persists across
    # all curated rows (including deprecated). If a row (any status) exists
    # with identical content, reject with 409 — publishing the same payload
    # twice under different semvers is a no-op by construction.
    existing = (
        await db.execute(
            select(CuratedSkill).where(CuratedSkill.revision_hash == rhash)
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"A curated skill with this content already exists "
                f"(id={existing.id}, semver={existing.semver}, status={existing.status})"
            ),
        )

    now = datetime.now(UTC)
    # Deprecate the prior active row so history is preserved but only the
    # latest is user-visible by default.
    if prior_active is not None:
        prior_active.status = "deprecated"

    curated = CuratedSkill(
        id=f"curated_{uuid.uuid4().hex}",
        semver=effective_semver,
        revision_hash=rhash,
        source_skill_id=submission.source_skill_id,
        source_tenant_id=submission.submitter_tenant_id,
        approved_by=current_user.id,
        approved_at=now,
        payload=payload,
        status="active",
        created_at=now,
    )
    db.add(curated)
    submission.status = "approved"
    submission.reviewer_id = current_user.id
    submission.review_note = data.review_note
    submission.reviewed_at = now
    # Persist the effective semver so the submission record reflects what
    # was actually shipped.
    submission.proposed_semver = effective_semver
    await db.commit()
    logger.info(
        "Submission %s approved as curated %s (semver=%s, bump=%s) by %s%s",
        submission.id,
        curated.id,
        effective_semver,
        data.bump or "<none>",
        current_user.id,
        f" (deprecated prior {prior_active.id})" if prior_active else "",
    )
    return _curated_to_response(curated)


@router.post(
    "/api/v1/admin/skill-submissions/{submission_id}/reject",
    response_model=SubmissionResponse,
)
async def admin_reject_submission(
    submission_id: str,
    data: ReviewRequest,
    current_user: UserModel = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubmissionResponse:
    _require_superuser(current_user)
    submission = await db.get(SkillSubmission, submission_id)
    if submission is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found"
        )
    if submission.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Submission already {submission.status}",
        )
    submission.status = "rejected"
    submission.reviewer_id = current_user.id
    submission.review_note = data.review_note
    submission.reviewed_at = datetime.now(UTC)
    await db.commit()
    logger.info("Submission %s rejected by %s", submission.id, current_user.id)
    return _submission_to_response(submission)
