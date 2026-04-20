"""Worker report payload parsing + fingerprint helpers + service factory.

All pure (parsing, hashing) except ``_build_attempt_service`` which takes an
``AsyncSession`` and constructs the persistence service.
"""

from __future__ import annotations

import hashlib
import json

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.workspace_task_session_attempt_service import (
    WorkspaceTaskSessionAttemptService,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_session_attempt_repository import (
    SqlWorkspaceTaskSessionAttemptRepository,
)


def _parse_worker_report_payload(
    *,
    report_type: str,
    summary: str,
    artifacts: list[str],
) -> tuple[str, list[str], list[str]]:
    normalized_summary = summary.strip() or f"worker_report:{report_type}"
    merged_artifacts = list(dict.fromkeys(artifacts))
    verifications: list[str] = []

    try:
        payload = json.loads(summary)
    except Exception:
        payload = None

    if isinstance(payload, dict):
        payload_summary = payload.get("summary")
        if isinstance(payload_summary, str) and payload_summary.strip():
            normalized_summary = payload_summary.strip()
        payload_artifacts = payload.get("artifacts")
        if isinstance(payload_artifacts, list):
            merged_artifacts = list(
                dict.fromkeys(
                    [*merged_artifacts, *[str(item) for item in payload_artifacts if item]]
                )
            )
        payload_verifications = payload.get("verifications")
        if isinstance(payload_verifications, list):
            verifications.extend(str(item) for item in payload_verifications if item)
        verdict = payload.get("verdict") or payload.get("outcome")
        if isinstance(verdict, str) and verdict.strip():
            verifications.append(f"worker_verdict:{verdict.strip()}")
        verification_grade = payload.get("verification_grade")
        if isinstance(verification_grade, str) and verification_grade.strip():
            verifications.append(f"verification_grade:{verification_grade.strip()}")

    if report_type == "completed" and not verifications:
        verifications.append("worker_report:completed")

    return normalized_summary, merged_artifacts, list(dict.fromkeys(verifications))


def _build_worker_report_fingerprint(
    *,
    report_type: str,
    summary: str,
    artifacts: list[str],
    verifications: list[str],
    report_id: str | None,
) -> str:
    payload = {
        "report_id": report_id or "",
        "report_type": report_type,
        "summary": summary,
        "artifacts": list(artifacts),
        "verifications": list(verifications),
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _build_attempt_service(db: AsyncSession) -> WorkspaceTaskSessionAttemptService:
    return WorkspaceTaskSessionAttemptService(
        attempt_repo=SqlWorkspaceTaskSessionAttemptRepository(db),
    )


__all__ = [
    "_build_attempt_service",
    "_build_worker_report_fingerprint",
    "_parse_worker_report_payload",
]
