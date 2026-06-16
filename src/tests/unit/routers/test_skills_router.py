from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, status

from src.domain.model.agent.skill import Skill, SkillScope
from src.domain.model.agent.skill.skill_version import SkillVersion
from src.domain.model.agent.skill_source import SkillSource
from src.infrastructure.adapters.primary.web.routers import skills as router

SAMPLE_SKILL_MD = """---
name: alpha-skill
description: Searches, installs, and exports agent skills.
allowed-tools: Bash(git:*) Read
metadata:
  version: "1.2.3"
  author: test-suite
---

# Alpha Skill

Use when managing Agent Skills packages.
"""

SAMPLE_SKILL_MD_WITH_SPEC = """---
name: alpha-skill
description: Searches, installs, and exports agent skills.
allowed-tools: Bash(git:*) Read
license: MIT
compatibility: Requires git and internet access
metadata:
  version: "1.2.3"
  author: test-suite
---

# Alpha Skill

Use when managing Agent Skills packages.
"""


@pytest.fixture(autouse=True)
def _allow_tenant_skill_write(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    guard = AsyncMock()
    monkeypatch.setattr(router, "_ensure_tenant_skill_write_access", guard)
    return guard


def _make_zip(files: dict[str, bytes | str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            archive.writestr(path, data)
    return buffer.getvalue()


class _SkillRepository:
    async def get_by_name(
        self,
        tenant_id: str,
        name: str,
        scope: SkillScope | None = None,
    ) -> Skill | None:
        _ = (tenant_id, name, scope)
        return None

    async def create(self, _skill: object) -> object:
        raise ValueError("Skill name 'Bad Name' must be lowercase with hyphens only")


class _Container:
    def skill_repository(self) -> _SkillRepository:
        return _SkillRepository()


class _MemorySkillRepository:
    def __init__(self) -> None:
        self.skills_by_id: dict[str, Skill] = {}
        self.skills_by_name: dict[str, list[Skill]] = {}

    async def create(self, skill: Skill) -> Skill:
        self.skills_by_id[skill.id] = skill
        skills = [candidate for candidate in self.skills_by_name.get(skill.name, []) if candidate.id != skill.id]
        skills.append(skill)
        self.skills_by_name[skill.name] = skills
        return skill

    async def get_by_id(self, skill_id: str) -> Skill | None:
        return self.skills_by_id.get(skill_id)

    async def get_by_name(
        self,
        tenant_id: str,
        name: str,
        scope: SkillScope | None = None,
    ) -> Skill | None:
        candidates = [
            skill
            for skill in self.skills_by_name.get(name, [])
            if skill.tenant_id == tenant_id and (scope is None or skill.scope == scope)
        ]
        if scope is not None:
            return candidates[0] if candidates else None
        tenant_scoped = [
            skill for skill in candidates if skill.scope == SkillScope.TENANT and skill.project_id is None
        ]
        return (tenant_scoped or candidates)[0] if candidates else None

    async def update(self, skill: Skill) -> Skill:
        self.skills_by_id[skill.id] = skill
        skills = [candidate for candidate in self.skills_by_name.get(skill.name, []) if candidate.id != skill.id]
        skills.append(skill)
        self.skills_by_name[skill.name] = skills
        return skill

    async def delete(self, skill_id: str) -> bool:
        skill = self.skills_by_id.pop(skill_id, None)
        if skill is not None:
            self.skills_by_name[skill.name] = [
                candidate for candidate in self.skills_by_name.get(skill.name, []) if candidate.id != skill_id
            ]
        return True

    async def list_by_tenant(self, *_args: object, **_kwargs: object) -> list[Skill]:
        return list(self.skills_by_id.values())

    async def list_by_project(
        self, project_id: str, *_args: object, tenant_id: str | None = None, **_kwargs: object
    ) -> list[Skill]:
        return [
            skill
            for skill in self.skills_by_id.values()
            if skill.project_id == project_id and (tenant_id is None or skill.tenant_id == tenant_id)
        ]

    async def count_by_tenant(self, *_args: object, **_kwargs: object) -> int:
        return len(self.skills_by_id)


class _MemoryContainer:
    def __init__(self, repo: _MemorySkillRepository) -> None:
        self._repo = repo

    def skill_repository(self) -> _MemorySkillRepository:
        return self._repo


class _MemoryVersionRepository:
    def __init__(self, db: SimpleNamespace) -> None:
        self._db = db

    async def create(self, version: SkillVersion) -> SkillVersion:
        self._db.versions.append(version)
        return version

    async def get_by_version(self, skill_id: str, version_number: int) -> SkillVersion | None:
        return next(
            (
                version
                for version in self._db.versions
                if version.skill_id == skill_id and version.version_number == version_number
            ),
            None,
        )

    async def list_by_skill(
        self, skill_id: str, limit: int = 50, offset: int = 0
    ) -> list[SkillVersion]:
        versions = [version for version in self._db.versions if version.skill_id == skill_id]
        return versions[offset : offset + limit]

    async def get_latest(self, skill_id: str) -> SkillVersion | None:
        versions = [version for version in self._db.versions if version.skill_id == skill_id]
        return max(versions, key=lambda version: version.version_number, default=None)

    async def get_max_version_number(self, skill_id: str) -> int:
        versions = [
            version.version_number for version in self._db.versions if version.skill_id == skill_id
        ]
        return max(versions, default=0)

    async def count_by_skill(self, skill_id: str) -> int:
        return len([version for version in self._db.versions if version.skill_id == skill_id])


class _MemorySqlSkillRepository:
    def __init__(self, db: SimpleNamespace) -> None:
        self._repo = db.skill_repo

    async def get_by_id(self, skill_id: str) -> Skill | None:
        return await self._repo.get_by_id(skill_id)

    async def get_by_name(
        self,
        tenant_id: str,
        name: str,
        scope: SkillScope | None = None,
    ) -> Skill | None:
        return await self._repo.get_by_name(tenant_id, name, scope)

    async def update(self, skill: Skill) -> Skill:
        return await self._repo.update(skill)

    async def list_by_project(
        self, project_id: str, *_args: object, tenant_id: str | None = None, **_kwargs: object
    ) -> list[Skill]:
        return await self._repo.list_by_project(project_id, tenant_id=tenant_id)


class _MemoryEvolutionRepository:
    def __init__(self, db: SimpleNamespace) -> None:
        self._db = db

    @staticmethod
    def _is_project_allowed(item: SimpleNamespace, project_ids: set[str] | None) -> bool:
        if project_ids is None:
            return True
        project_id = getattr(item, "project_id", None)
        return project_id is None or project_id in project_ids

    async def list_jobs(
        self,
        *,
        tenant_id: str,
        status: str | None = None,
        skill_name: str | None = None,
        project_id: str | None = None,
        filter_project_id: bool = False,
        project_ids: set[str] | None = None,
        limit: int = 50,
    ) -> list[SimpleNamespace]:
        jobs = [
            job
            for job in self._db.evolution_jobs
            if job.tenant_id == tenant_id
            and (status is None or job.status == status)
            and (skill_name is None or job.skill_name == skill_name)
            and self._is_project_allowed(job, project_ids)
            and (
                not filter_project_id
                or getattr(job, "project_id", None) == project_id
            )
        ]
        return jobs[:limit]

    async def get_job(self, job_id: str) -> SimpleNamespace | None:
        return next((job for job in self._db.evolution_jobs if job.id == job_id), None)

    async def update_job_status(
        self,
        job_id: str,
        *,
        status: str,
        skill_version_id: str | None = None,
    ) -> None:
        job = await self.get_job(job_id)
        if job is None:
            return
        job.status = status
        if skill_version_id is not None:
            job.skill_version_id = skill_version_id
        if status == "applied":
            job.applied_at = datetime.now(UTC)

    async def count_sessions_by_skill(
        self,
        *,
        tenant_id: str,
        skill_name: str,
        project_id: str | None = None,
        filter_project_id: bool = False,
    ) -> int:
        return sum(
            1
            for session in self._db.evolution_sessions
            if session.tenant_id == tenant_id and session.skill_name == skill_name
            and (
                not filter_project_id
                or getattr(session, "project_id", None) == project_id
            )
        )

    async def get_overview_stats(
        self,
        *,
        tenant_id: str,
        project_ids: set[str] | None = None,
    ) -> dict[str, object]:
        sessions = [
            session
            for session in self._db.evolution_sessions
            if session.tenant_id == tenant_id and self._is_project_allowed(session, project_ids)
        ]
        jobs = [
            job
            for job in self._db.evolution_jobs
            if job.tenant_id == tenant_id and self._is_project_allowed(job, project_ids)
        ]
        scores = [
            session.overall_score
            for session in sessions
            if session.skill_name != "__no_skill__"
            and getattr(session, "overall_score", None) is not None
        ]
        skill_sessions = [session for session in sessions if session.skill_name != "__no_skill__"]
        return {
            "total_sessions": len(sessions),
            "skill_sessions": len(skill_sessions),
            "no_skill_sessions": sum(1 for s in sessions if s.skill_name == "__no_skill__"),
            "unprocessed_sessions": sum(1 for s in skill_sessions if not s.processed),
            "processed_sessions": sum(1 for s in skill_sessions if s.processed),
            "scored_sessions": len(scores),
            "successful_sessions": sum(1 for s in sessions if s.success),
            "avg_score": sum(scores) / len(scores) if scores else None,
            "total_jobs": len(jobs),
            "pending_jobs": sum(1 for j in jobs if j.status == "pending_review"),
            "applied_jobs": sum(1 for j in jobs if j.status == "applied"),
            "skipped_jobs": sum(1 for j in jobs if j.status == "skipped"),
            "rejected_jobs": sum(1 for j in jobs if j.status == "rejected"),
        }

    async def get_skill_session_summaries(
        self,
        *,
        tenant_id: str,
        project_id: str | None = None,
        filter_project_id: bool = False,
        project_ids: set[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        sessions = [
            session
            for session in self._db.evolution_sessions
            if session.tenant_id == tenant_id
            and self._is_project_allowed(session, project_ids)
            and (
                not filter_project_id
                or getattr(session, "project_id", None) == project_id
            )
        ]
        jobs = [
            job
            for job in self._db.evolution_jobs
            if job.tenant_id == tenant_id
            and self._is_project_allowed(job, project_ids)
            and (
                not filter_project_id
                or getattr(job, "project_id", None) == project_id
            )
        ]
        summaries: list[dict[str, object]] = []
        skill_scopes = {
            (session.skill_name, getattr(session, "project_id", None))
            for session in sessions
            if session.skill_name != "__no_skill__"
        }
        for skill_name, scope_project_id in sorted(skill_scopes):
            skill_sessions = [
                session
                for session in sessions
                if session.skill_name == skill_name
                and getattr(session, "project_id", None) == scope_project_id
            ]
            skill_jobs = [
                job
                for job in jobs
                if job.skill_name == skill_name
                and getattr(job, "project_id", None) == scope_project_id
            ]
            scores = [
                session.overall_score
                for session in skill_sessions
                if getattr(session, "overall_score", None) is not None
            ]
            summaries.append(
                {
                    "skill_name": skill_name,
                    "project_id": scope_project_id,
                    "session_count": len(skill_sessions),
                    "success_count": sum(1 for session in skill_sessions if session.success),
                    "unprocessed_count": sum(
                        1 for session in skill_sessions if not session.processed
                    ),
                    "scored_count": len(scores),
                    "avg_score": sum(scores) / len(scores) if scores else None,
                    "latest_session_at": max(session.created_at for session in skill_sessions),
                    "job_count": len(skill_jobs),
                    "pending_job_count": sum(
                        1 for job in skill_jobs if job.status == "pending_review"
                    ),
                    "latest_job_at": (
                        max(job.created_at for job in skill_jobs) if skill_jobs else None
                    ),
                }
            )
        return sorted(
            summaries,
            key=lambda summary: (
                -int(summary["session_count"]),
                str(summary["skill_name"]),
            ),
        )[:limit]

    async def list_recent_sessions(
        self,
        *,
        tenant_id: str,
        skill_name: str | None = None,
        project_id: str | None = None,
        filter_project_id: bool = False,
        project_ids: set[str] | None = None,
        limit: int = 50,
    ) -> list[SimpleNamespace]:
        sessions = [
            session
            for session in self._db.evolution_sessions
            if session.tenant_id == tenant_id
            and (skill_name is None or session.skill_name == skill_name)
            and self._is_project_allowed(session, project_ids)
            and (
                not filter_project_id
                or getattr(session, "project_id", None) == project_id
            )
        ]
        return sorted(sessions, key=lambda session: session.created_at, reverse=True)[:limit]


@pytest.mark.unit
async def test_create_skill_sanitizes_domain_validation_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: _Container())

    with pytest.raises(HTTPException) as exc_info:
        await router.create_skill(
            request=SimpleNamespace(),
            data=router.SkillCreate(
                name="Bad Name",
                description="Test skill",
                tools=["read"],
            ),
            tenant_id="tenant-1",
            db=SimpleNamespace(commit=AsyncMock()),
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "Invalid skill request"
    assert "Bad Name" not in exc_info.value.detail


@pytest.mark.unit
def test_skill_response_exposes_source_fields() -> None:
    skill = Skill.create(
        tenant_id="tenant-1",
        name="filesystem-skill",
        description="Loaded from a local SKILL.md file",
        tools=["Read"],
    )
    skill.source = SkillSource.FILESYSTEM
    skill.file_path = "/repo/.memstack/skills/filesystem-skill/SKILL.md"

    response = router.skill_to_response(skill)

    assert response.source == "filesystem"
    assert response.file_path == "/repo/.memstack/skills/filesystem-skill/SKILL.md"


@pytest.mark.unit
async def test_create_skill_preserves_agentskills_spec_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _MemorySkillRepository()
    db = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: _MemoryContainer(repo))

    response = await router.create_skill(
        request=SimpleNamespace(),
        data=router.SkillCreate(
            name="spec-skill",
            description="Creates a skill with Agent Skills metadata",
            tools=["Read"],
            metadata={"author": "test-suite"},
            license="MIT",
            compatibility="Requires git and internet access",
            allowed_tools_raw="Bash(git:*) Read",
            spec_version="1.0",
        ),
        tenant_id="tenant-1",
        db=db,
    )

    assert response.license == "MIT"
    assert response.compatibility == "Requires git and internet access"
    assert response.allowed_tools_raw == "Bash(git:*) Read"
    assert response.spec_version == "1.0"
    assert response.metadata == {
        "author": "test-suite",
        "agentskills": {
            "license": "MIT",
            "compatibility": "Requires git and internet access",
            "allowed_tools": "Bash(git:*) Read",
            "spec_version": "1.0",
        },
    }


@pytest.mark.unit
async def test_create_project_skill_requires_project_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _MemorySkillRepository()
    db = SimpleNamespace(commit=AsyncMock())
    access_guard = AsyncMock(
        side_effect=HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    )
    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: _MemoryContainer(repo))
    monkeypatch.setattr(router, "_ensure_project_skill_access", access_guard)

    with pytest.raises(HTTPException) as exc_info:
        await router.create_skill(
            request=SimpleNamespace(),
            data=router.SkillCreate(
                name="project-skill",
                description="Project scoped skill",
                tools=["Read"],
                scope="project",
                project_id="foreign-project",
            ),
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
            db=db,
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    access_guard.assert_awaited_once()
    assert access_guard.await_args.kwargs["required_roles"] == router._PROJECT_SKILL_WRITE_ROLES
    assert repo.skills_by_id == {}
    db.commit.assert_not_awaited()


@pytest.mark.unit
async def test_create_tenant_skill_requires_tenant_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _MemorySkillRepository()
    db = SimpleNamespace(commit=AsyncMock())
    write_guard = AsyncMock(
        side_effect=HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    )
    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: _MemoryContainer(repo))
    monkeypatch.setattr(router, "_ensure_tenant_skill_write_access", write_guard)

    with pytest.raises(HTTPException) as exc_info:
        await router.create_skill(
            request=SimpleNamespace(),
            data=router.SkillCreate(
                name="tenant-skill",
                description="Tenant scoped skill",
                tools=["Read"],
            ),
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
            db=db,
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert repo.skills_by_id == {}
    db.commit.assert_not_awaited()


@pytest.mark.unit
async def test_list_project_skills_requires_project_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _MemorySkillRepository()
    db = SimpleNamespace()
    access_guard = AsyncMock(
        side_effect=HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    )
    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: _MemoryContainer(repo))
    monkeypatch.setattr(router, "_ensure_project_skill_access", access_guard)

    with pytest.raises(HTTPException) as exc_info:
        await router.list_skills(
            request=SimpleNamespace(),
            search_query=None,
            q=None,
            status_filter=None,
            scope_filter=None,
            project_id="foreign-project",
            limit=100,
            offset=0,
            skip=None,
            tenant_id="tenant-1",
            current_user=SimpleNamespace(id="user-1"),
            db=db,
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    access_guard.assert_awaited_once()


@pytest.mark.unit
@pytest.mark.parametrize(
    "route_name",
    [
        "get",
        "update",
        "delete",
        "status",
        "content_get",
        "content_update",
        "export",
        "versions",
        "version",
        "evolution",
        "evolution_run",
        "rollback",
    ],
)
async def test_project_skill_raw_id_routes_require_project_access(
    route_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _MemorySkillRepository()
    skill = Skill.create(
        tenant_id="tenant-1",
        project_id="foreign-project",
        name="project-skill",
        description="Project scoped skill",
        tools=["Read"],
        scope=SkillScope.PROJECT,
        full_content=SAMPLE_SKILL_MD,
    )
    await repo.create(skill)
    db = SimpleNamespace(
        commit=AsyncMock(),
        skill_repo=repo,
        versions=[],
        evolution_jobs=[],
        evolution_sessions=[],
    )
    current_user = SimpleNamespace(id="user-1")
    access_guard = AsyncMock(
        side_effect=HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    )
    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: _MemoryContainer(repo))
    monkeypatch.setattr(router, "_ensure_project_skill_access", access_guard)
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_repository.SqlSkillRepository",
        _MemorySqlSkillRepository,
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository."
        "SqlSkillVersionRepository",
        _MemoryVersionRepository,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.skill_evolution.repository.SkillEvolutionRepository",
        _MemoryEvolutionRepository,
    )

    route_calls = {
        "get": lambda: router.get_skill(
            request=SimpleNamespace(),
            skill_id=skill.id,
            tenant_id="tenant-1",
            current_user=current_user,
            db=db,
        ),
        "update": lambda: router.update_skill(
            request=SimpleNamespace(),
            skill_id=skill.id,
            data=router.SkillUpdate(description="Updated"),
            tenant_id="tenant-1",
            current_user=current_user,
            db=db,
        ),
        "delete": lambda: router.delete_skill(
            request=SimpleNamespace(),
            skill_id=skill.id,
            tenant_id="tenant-1",
            current_user=current_user,
            db=db,
        ),
        "status": lambda: router.update_skill_status(
            request=SimpleNamespace(),
            skill_id=skill.id,
            status_value="disabled",
            tenant_id="tenant-1",
            current_user=current_user,
            db=db,
        ),
        "content_get": lambda: router.get_skill_content(
            request=SimpleNamespace(),
            skill_id=skill.id,
            tenant_id="tenant-1",
            current_user=current_user,
            db=db,
        ),
        "content_update": lambda: router.update_skill_content(
            request=SimpleNamespace(),
            skill_id=skill.id,
            data=router.SkillContentUpdate(full_content=SAMPLE_SKILL_MD_WITH_SPEC),
            tenant_id="tenant-1",
            current_user=current_user,
            db=db,
        ),
        "export": lambda: router.export_skill_package(
            request=SimpleNamespace(),
            skill_id=skill.id,
            tenant_id="tenant-1",
            current_user=current_user,
            db=db,
        ),
        "versions": lambda: router.list_skill_versions(
            skill_id=skill.id,
            limit=50,
            offset=0,
            tenant={"id": "tenant-1"},
            current_user=current_user,
            db=db,
        ),
        "version": lambda: router.get_skill_version(
            skill_id=skill.id,
            version_number=1,
            tenant={"id": "tenant-1"},
            current_user=current_user,
            db=db,
        ),
        "evolution": lambda: router.get_skill_evolution(
            skill_id=skill.id,
            limit=20,
            tenant={"id": "tenant-1"},
            current_user=current_user,
            db=db,
        ),
        "evolution_run": lambda: router.run_skill_evolution(
            request=SimpleNamespace(),
            skill_id=skill.id,
            tenant={"id": "tenant-1"},
            current_user=current_user,
            db=db,
        ),
        "rollback": lambda: router.rollback_skill(
            skill_id=skill.id,
            request_body=router.SkillRollbackRequest(version_number=1),
            tenant={"id": "tenant-1"},
            current_user=current_user,
            db=db,
        ),
    }

    with pytest.raises(HTTPException) as exc_info:
        await route_calls[route_name]()

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    assert exc_info.value.detail == "Access denied"
    access_guard.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.unit
async def test_create_skill_rejects_mismatched_skill_md_frontmatter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _MemorySkillRepository()
    db = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: _MemoryContainer(repo))

    with pytest.raises(HTTPException) as exc_info:
        await router.create_skill(
            request=SimpleNamespace(),
            data=router.SkillCreate(
                name="wrong-name",
                description="Searches, installs, and exports agent skills.",
                tools=["Bash", "Read"],
                full_content=SAMPLE_SKILL_MD_WITH_SPEC,
            ),
            tenant_id="tenant-1",
            db=db,
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "Skill name must match SKILL.md frontmatter"


@pytest.mark.unit
async def test_create_skill_from_skill_md_uses_frontmatter_as_canonical_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _MemorySkillRepository()
    db = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: _MemoryContainer(repo))

    response = await router.create_skill(
        request=SimpleNamespace(),
        data=router.SkillCreate(
            name="alpha-skill",
            description="Searches, installs, and exports agent skills.",
            tools=["Bash", "Read"],
            full_content=SAMPLE_SKILL_MD_WITH_SPEC,
        ),
        tenant_id="tenant-1",
        db=db,
    )

    stored = await repo.get_by_id(response.id)
    assert stored is not None
    assert stored.full_content == SAMPLE_SKILL_MD_WITH_SPEC
    assert stored.license == "MIT"
    assert stored.compatibility == "Requires git and internet access"
    assert stored.allowed_tools_raw == "Bash(git:*) Read"
    assert response.version_label == "1.2.3"
    db.commit.assert_awaited_once()


@pytest.mark.unit
async def test_update_skill_clears_optional_agentskills_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _MemorySkillRepository()
    skill = Skill.create(
        tenant_id="tenant-1",
        name="alpha-skill",
        description="Searches, installs, and exports agent skills.",
        tools=["Bash", "Read"],
        full_content=SAMPLE_SKILL_MD_WITH_SPEC,
        metadata={
            "author": "test-suite",
            "agentskills": {
                "license": "MIT",
                "compatibility": "Requires git and internet access",
                "allowed_tools": "Bash(git:*) Read",
                "spec_version": "1.0",
            },
        },
        license="MIT",
        compatibility="Requires git and internet access",
        allowed_tools_raw="Bash(git:*) Read",
    )
    await repo.create(skill)
    db = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: _MemoryContainer(repo))

    response = await router.update_skill(
        request=SimpleNamespace(),
        skill_id=skill.id,
        data=router.SkillUpdate(
            license=None,
            compatibility=None,
            allowed_tools_raw=None,
            spec_version=None,
        ),
        tenant_id="tenant-1",
        db=db,
    )

    stored = await repo.get_by_id(skill.id)
    assert stored is not None
    assert response.license is None
    assert response.compatibility is None
    assert response.allowed_tools_raw is None
    assert response.spec_version == "1.0"
    assert stored.license is None
    assert stored.compatibility is None
    assert stored.allowed_tools_raw is None
    assert stored.metadata == {"author": "test-suite"}
    db.commit.assert_awaited_once()


@pytest.mark.unit
def test_skill_package_parser_reads_agentskills_metadata() -> None:
    parsed, metadata, tools = router._parse_skill_package(SAMPLE_SKILL_MD)

    assert parsed.name == "alpha-skill"
    assert parsed.description == "Searches, installs, and exports agent skills."
    assert tools == ["Bash", "Read"]
    assert metadata["author"] == "test-suite"
    assert metadata["agentskills"]["allowed_tools"] == "Bash(git:*) Read"
    assert router._extract_version_label_from_parsed(parsed) == "1.2.3"


@pytest.mark.unit
def test_skill_md_builder_emits_agentskills_frontmatter_fields() -> None:
    skill_md = router._build_skill_md_from_payload(
        {
            "name": "frontmatter-skill",
            "description": "Exports optional Agent Skills fields",
            "tools": ["Read"],
            "metadata": {
                "agentskills": {
                    "license": "Apache-2.0",
                    "compatibility": "Requires Python 3.12+",
                    "allowed_tools": "Bash(uv:*) Read",
                }
            },
        },
        version_label="1.2.3",
    )

    parsed, metadata, tools = router._parse_skill_package(skill_md)

    assert parsed.license == "Apache-2.0"
    assert parsed.compatibility == "Requires Python 3.12+"
    assert parsed.allowed_tools_raw == "Bash(uv:*) Read"
    assert metadata["version"] == "1.2.3"
    assert tools == ["Bash", "Read"]


@pytest.mark.unit
def test_skill_zip_parser_reads_skill_md_and_resources() -> None:
    content = _make_zip(
        {
            "alpha-skill/SKILL.md": SAMPLE_SKILL_MD,
            "alpha-skill/references/README.md": "details",
            "alpha-skill/assets/logo.bin": b"\x89PNG",
        }
    )

    skill_md_content, resource_files = router._parse_skill_zip_package(content)

    assert skill_md_content == SAMPLE_SKILL_MD
    assert resource_files["references/README.md"] == "details"
    assert resource_files["assets/logo.bin"].startswith("base64:")


@pytest.mark.unit
def test_skill_zip_parser_rejects_ambiguous_packages() -> None:
    content = _make_zip(
        {
            "one/SKILL.md": SAMPLE_SKILL_MD,
            "two/SKILL.md": SAMPLE_SKILL_MD,
        }
    )

    with pytest.raises(HTTPException) as exc_info:
        router._parse_skill_zip_package(content)

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.unit
def test_skill_search_matches_name_description_version_and_metadata() -> None:
    skill = Skill.create(
        tenant_id="tenant-1",
        name="alpha-skill",
        description="Manages Agent Skills packages",
        tools=["Read"],
        metadata={"author": "platform"},
    )
    skill.version_label = "1.2.3"
    skill.source = SkillSource.FILESYSTEM
    skill.file_path = ".codex/skills/alpha-skill/SKILL.md"

    assert router._skill_matches_search(skill, "platform")
    assert router._skill_matches_search(skill, "1.2")
    assert router._skill_matches_search(skill, "packages")
    assert router._skill_matches_search(skill, "filesystem")
    assert router._skill_matches_search(skill, "alpha-skill/SKILL.md")
    assert not router._skill_matches_search(skill, "billing")


@pytest.mark.unit
async def test_import_skill_package_creates_skill_and_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _MemorySkillRepository()
    db = SimpleNamespace(commit=AsyncMock(), versions=[])
    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: _MemoryContainer(repo))
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository."
        "SqlSkillVersionRepository",
        _MemoryVersionRepository,
    )

    response = await router.import_skill_package(
        request=SimpleNamespace(),
        data=router.SkillImportRequest(
            skill_md_content=SAMPLE_SKILL_MD,
            resource_files={"references/README.md": "details"},
        ),
        tenant_id="tenant-1",
        db=db,
    )

    assert response.action == "import"
    assert response.skill.name == "alpha-skill"
    assert response.skill.current_version == 1
    assert response.version_label == "1.2.3"
    assert db.versions[0].resource_files == {"references/README.md": "details"}
    db.commit.assert_awaited_once()


@pytest.mark.unit
async def test_update_skill_content_validates_and_creates_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _MemorySkillRepository()
    skill = Skill.create(
        tenant_id="tenant-1",
        name="alpha-skill",
        description="Old description",
        tools=["Read"],
        full_content=None,
    )
    await repo.create(skill)
    db = SimpleNamespace(commit=AsyncMock(), versions=[])
    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: _MemoryContainer(repo))
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository."
        "SqlSkillVersionRepository",
        _MemoryVersionRepository,
    )

    response = await router.update_skill_content(
        request=SimpleNamespace(),
        skill_id=skill.id,
        data=router.SkillContentUpdate(full_content=SAMPLE_SKILL_MD_WITH_SPEC),
        tenant_id="tenant-1",
        db=db,
    )

    updated = await repo.get_by_id(skill.id)
    assert updated is not None
    assert response.description == "Searches, installs, and exports agent skills."
    assert updated.tools == ["Bash", "Read"]
    assert updated.full_content == SAMPLE_SKILL_MD_WITH_SPEC
    assert updated.license == "MIT"
    assert updated.allowed_tools_raw == "Bash(git:*) Read"
    assert updated.current_version == 1
    assert db.versions[0].skill_md_content == SAMPLE_SKILL_MD_WITH_SPEC
    db.commit.assert_awaited_once()


@pytest.mark.unit
async def test_import_skill_zip_package_creates_skill_and_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _MemorySkillRepository()
    db = SimpleNamespace(commit=AsyncMock(), versions=[])
    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: _MemoryContainer(repo))
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository."
        "SqlSkillVersionRepository",
        _MemoryVersionRepository,
    )
    archive = SimpleNamespace(
        filename="alpha-skill.zip",
        read=AsyncMock(
            return_value=_make_zip(
                {
                    "alpha-skill/SKILL.md": SAMPLE_SKILL_MD,
                    "alpha-skill/references/README.md": "details",
                }
            )
        ),
    )

    response = await router.import_skill_zip_package(
        request=SimpleNamespace(),
        archive=archive,
        scope="tenant",
        project_id=None,
        overwrite=False,
        change_summary=None,
        tenant_id="tenant-1",
        db=db,
    )

    assert response.action == "import"
    assert response.skill.name == "alpha-skill"
    assert db.versions[0].resource_files == {"references/README.md": "details"}
    db.commit.assert_awaited_once()


@pytest.mark.unit
async def test_get_skill_reads_filesystem_skill_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.services.skill_service import SkillService

    repo = _MemorySkillRepository()
    db = SimpleNamespace()
    filesystem_skill = Skill.create(
        tenant_id="tenant-1",
        name="filesystem-skill",
        description="Loaded from SKILL.md",
        tools=["Read"],
    )
    filesystem_skill.source = SkillSource.FILESYSTEM
    filesystem_skill.file_path = "/repo/skills/filesystem-skill/SKILL.md"

    class _FilesystemSkillService:
        async def list_available_skills(self, *_args: object, **_kwargs: object) -> list[Skill]:
            return [filesystem_skill]

    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: _MemoryContainer(repo))
    monkeypatch.setattr(
        SkillService,
        "create",
        staticmethod(lambda **_kwargs: _FilesystemSkillService()),
    )

    response = await router.get_skill(
        request=SimpleNamespace(),
        skill_id="filesystem-skill",
        tenant_id="tenant-1",
        db=db,
    )

    assert response.name == "filesystem-skill"
    assert response.source == "filesystem"
    assert response.file_path == "/repo/skills/filesystem-skill/SKILL.md"


@pytest.mark.unit
async def test_export_skill_package_uses_latest_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _MemorySkillRepository()
    skill = Skill.create(
        tenant_id="tenant-1",
        name="alpha-skill",
        description="Manages Agent Skills packages",
        tools=["Read"],
        full_content=SAMPLE_SKILL_MD,
    )
    await repo.create(skill)
    db = SimpleNamespace(
        versions=[
            SkillVersion(
                id="version-1",
                skill_id=skill.id,
                version_number=1,
                version_label="1.2.3",
                skill_md_content=SAMPLE_SKILL_MD,
                resource_files={"assets/template.txt": "template"},
            )
        ]
    )
    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: _MemoryContainer(repo))
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository."
        "SqlSkillVersionRepository",
        _MemoryVersionRepository,
    )

    response = await router.export_skill_package(
        request=SimpleNamespace(),
        skill_id=skill.id,
        tenant_id="tenant-1",
        db=db,
    )

    assert response.skill.name == "alpha-skill"
    assert response.version_number == 1
    assert response.resource_files == {"assets/template.txt": "template"}
    assert response.skill_md_content == SAMPLE_SKILL_MD


@pytest.mark.unit
async def test_export_filesystem_skill_includes_directory_resource_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repo = _MemorySkillRepository()
    skill_dir = tmp_path / "filesystem-skill"
    skill_dir.mkdir()
    skill_md_path = skill_dir / "SKILL.md"
    skill_md_path.write_text(SAMPLE_SKILL_MD, encoding="utf-8")
    (skill_dir / "env.sh").write_text("export SKILL_ENV=1\n", encoding="utf-8")
    references_dir = skill_dir / "references"
    references_dir.mkdir()
    (references_dir / "README.md").write_text("details", encoding="utf-8")
    (skill_dir / "asset.bin").write_bytes(b"\xff\x00")

    skill = Skill.create(
        tenant_id="tenant-1",
        name="filesystem-skill",
        description="Loaded from SKILL.md",
        tools=["Read"],
        full_content=SAMPLE_SKILL_MD,
    )
    skill.source = SkillSource.FILESYSTEM
    skill.file_path = str(skill_md_path)
    await repo.create(skill)
    db = SimpleNamespace(versions=[])
    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: _MemoryContainer(repo))
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository."
        "SqlSkillVersionRepository",
        _MemoryVersionRepository,
    )

    response = await router.export_skill_package(
        request=SimpleNamespace(),
        skill_id=skill.id,
        tenant_id="tenant-1",
        db=db,
    )

    assert response.skill_md_content == SAMPLE_SKILL_MD
    assert response.resource_files["env.sh"] == "export SKILL_ENV=1\n"
    assert response.resource_files["references/README.md"] == "details"
    assert response.resource_files["asset.bin"].startswith("base64:")
    assert "SKILL.md" not in response.resource_files


@pytest.mark.unit
async def test_get_skill_version_sanitizes_missing_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _MemorySkillRepository()
    skill = Skill.create(
        tenant_id="tenant-1",
        name="skill-secret",
        description="Test skill",
        tools=["Read"],
    )
    await repo.create(skill)

    class _VersionRepository:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_version(self, _skill_id: str, _version_number: int) -> object | None:
            return None

    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_repository.SqlSkillRepository",
        _MemorySqlSkillRepository,
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository."
        "SqlSkillVersionRepository",
        _VersionRepository,
    )

    with pytest.raises(HTTPException) as exc_info:
        await router.get_skill_version(
            skill_id=skill.id,
            version_number=42,
            db=SimpleNamespace(skill_repo=repo),
            tenant={"id": "tenant-1"},
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Skill version not found"
    assert "secret" not in exc_info.value.detail
    assert "42" not in exc_info.value.detail


@pytest.mark.unit
async def test_get_skill_evolution_returns_route_and_trigger_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _MemorySkillRepository()
    skill = Skill.create(
        tenant_id="tenant-1",
        name="alpha-skill",
        description="Manages Agent Skills packages",
        tools=["Read"],
        full_content=SAMPLE_SKILL_MD,
    )
    await repo.create(skill)
    created_at = datetime.now(UTC)
    db = SimpleNamespace(
        skill_repo=repo,
        versions=[
            SkillVersion(
                id="version-1",
                skill_id=skill.id,
                version_number=1,
                version_label="1.2.3",
                skill_md_content=SAMPLE_SKILL_MD,
                change_summary="Initial import",
                created_by="api",
                created_at=created_at,
            )
        ],
        evolution_jobs=[
            SimpleNamespace(
                id="job-1",
                tenant_id="tenant-1",
                skill_name="alpha-skill",
                action="improve_skill",
                status="pending_review",
                rationale="Observed repeated missing setup step",
                candidate_content="# Improved alpha",
                session_ids=["s1", "s2"],
                skill_version_id=None,
                created_at=created_at,
                applied_at=None,
            )
        ],
        evolution_sessions=[
            SimpleNamespace(tenant_id="tenant-1", skill_name="alpha-skill"),
            SimpleNamespace(tenant_id="tenant-1", skill_name="alpha-skill"),
        ],
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_repository.SqlSkillRepository",
        _MemorySqlSkillRepository,
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository."
        "SqlSkillVersionRepository",
        _MemoryVersionRepository,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.skill_evolution.repository.SkillEvolutionRepository",
        _MemoryEvolutionRepository,
    )

    response = await router.get_skill_evolution(
        skill_id=skill.id,
        limit=20,
        db=db,
        tenant={"id": "tenant-1"},
    )

    assert response.skill_name == "alpha-skill"
    assert response.captured_session_count == 2
    assert response.trigger.capture_hook == "after_turn_complete"
    assert response.trigger.manual_trigger.endswith(f"/skills/{skill.id}/evolution/run")
    assert [entry.kind for entry in response.route] == ["version", "evolution_job"]
    assert response.jobs[0].rationale == "Observed repeated missing setup step"
    assert response.jobs[0].candidate_preview == "# Improved alpha"
    assert response.jobs[0].blocked_by_review is True


@pytest.mark.unit
async def test_get_skill_evolution_overview_returns_global_capture_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_at = datetime.now(UTC)
    db = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(
                scalar_one_or_none=lambda: None,
                scalars=lambda: SimpleNamespace(all=lambda: ["project-1"]),
            )
        ),
        evolution_jobs=[
            SimpleNamespace(
                id="job-1",
                tenant_id="tenant-1",
                project_id="project-1",
                skill_name="alpha-skill",
                action="improve_skill",
                status="pending_review",
                rationale="Missing setup step",
                candidate_content="# Improved alpha",
                session_ids=["s1"],
                skill_version_id=None,
                created_at=created_at,
                applied_at=None,
            ),
            SimpleNamespace(
                id="hidden-job",
                tenant_id="tenant-1",
                project_id="project-2",
                skill_name="hidden-skill",
                action="improve_skill",
                status="pending_review",
                rationale="Hidden project",
                candidate_content="# Hidden",
                session_ids=["hidden-session"],
                skill_version_id=None,
                created_at=created_at,
                applied_at=None,
            )
        ],
        evolution_sessions=[
            SimpleNamespace(
                id="s1",
                tenant_id="tenant-1",
                project_id="project-1",
                skill_name="alpha-skill",
                conversation_id="conv-1",
                user_query="Use alpha",
                summary="Strong run",
                judge_scores={"overall": 0.9},
                overall_score=0.9,
                success=True,
                execution_time_ms=1200,
                tool_call_count=2,
                processed=True,
                created_at=created_at,
            ),
            SimpleNamespace(
                id="s2",
                tenant_id="tenant-1",
                project_id=None,
                skill_name="__no_skill__",
                conversation_id="conv-2",
                user_query="No skill",
                summary=None,
                judge_scores=None,
                overall_score=None,
                success=True,
                execution_time_ms=300,
                tool_call_count=0,
                processed=False,
                created_at=created_at,
            ),
            SimpleNamespace(
                id="hidden-session",
                tenant_id="tenant-1",
                project_id="project-2",
                skill_name="hidden-skill",
                conversation_id="conv-hidden",
                user_query="Use hidden",
                summary="Hidden run",
                judge_scores={"overall": 1.0},
                overall_score=1.0,
                success=True,
                execution_time_ms=10,
                tool_call_count=1,
                processed=True,
                created_at=created_at,
            ),
        ],
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.skill_evolution.repository.SkillEvolutionRepository",
        _MemoryEvolutionRepository,
    )

    response = await router.get_skill_evolution_overview(
        skill_limit=20,
        session_limit=20,
        job_limit=20,
        db=db,
        tenant={"id": "tenant-1"},
        current_user=SimpleNamespace(id="user-1"),
    )

    assert response.stats.total_sessions == 2
    assert response.stats.skill_sessions == 1
    assert response.stats.no_skill_sessions == 1
    assert response.stats.pending_jobs == 1
    assert response.stats.rejected_jobs == 0
    assert response.monitor.blocked_by_review_count == 1
    assert response.monitor.backlog_count == 0
    assert response.monitor.unscored_count == 0
    assert response.monitor.needs_attention is True
    assert [stage.id for stage in response.stages] == [
        "capture",
        "summarize",
        "judge",
        "review",
        "apply",
    ]
    assert response.stages[3].status == "blocked"
    assert [skill.skill_name for skill in response.skills] == ["alpha-skill"]
    assert response.skills[0].skill_name == "alpha-skill"
    assert response.skills[0].session_count == 1
    assert response.recent_sessions[0].id in {"s1", "s2"}
    assert response.recent_jobs[0].id == "job-1"
    assert all(job.id != "hidden-job" for job in response.recent_jobs)
    assert all(session.id != "hidden-session" for session in response.recent_sessions)
    assert response.recent_jobs[0].candidate_preview == "# Improved alpha"
    assert response.trigger.manual_trigger == "/api/v1/skills/{skill_id}/evolution/run"


@pytest.mark.unit
async def test_apply_skill_evolution_job_creates_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _MemorySkillRepository()
    skill = Skill.create(
        tenant_id="tenant-1",
        name="alpha-skill",
        description="Manages Agent Skills packages",
        tools=["Read"],
        full_content=SAMPLE_SKILL_MD,
    )
    await repo.create(skill)
    created_at = datetime.now(UTC)
    db = SimpleNamespace(
        skill_repo=repo,
        versions=[],
        evolution_jobs=[
            SimpleNamespace(
                id="job-apply",
                tenant_id="tenant-1",
                skill_name="alpha-skill",
                action="improve_skill",
                status="pending_review",
                rationale="Add verification guidance",
                candidate_content="# Improved Alpha Skill",
                session_ids=["s1", "s2"],
                skill_version_id=None,
                created_at=created_at,
                applied_at=None,
            )
        ],
        commit=AsyncMock(),
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_repository.SqlSkillRepository",
        _MemorySqlSkillRepository,
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository."
        "SqlSkillVersionRepository",
        _MemoryVersionRepository,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.skill_evolution.repository.SkillEvolutionRepository",
        _MemoryEvolutionRepository,
    )

    response = await router.apply_skill_evolution_job(
        job_id="job-apply",
        db=db,
        tenant={"id": "tenant-1"},
    )

    assert response.status == "applied"
    assert response.skill_version_id == db.versions[0].id
    assert db.versions[0].created_by == "evolution"
    assert skill.full_content == "# Improved Alpha Skill"
    assert skill.current_version == 1
    db.commit.assert_awaited_once()


@pytest.mark.unit
async def test_reject_skill_evolution_job_does_not_create_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_at = datetime.now(UTC)
    db = SimpleNamespace(
        evolution_jobs=[
            SimpleNamespace(
                id="job-reject",
                tenant_id="tenant-1",
                skill_name="alpha-skill",
                action="improve_skill",
                status="pending_review",
                rationale="Rejected candidate",
                candidate_content="# Rejected",
                session_ids=["s1"],
                skill_version_id=None,
                created_at=created_at,
                applied_at=None,
            )
        ],
        versions=[],
        commit=AsyncMock(),
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.skill_evolution.repository.SkillEvolutionRepository",
        _MemoryEvolutionRepository,
    )

    response = await router.reject_skill_evolution_job(
        job_id="job-reject",
        db=db,
        tenant={"id": "tenant-1"},
    )

    assert response.status == "rejected"
    assert response.skill_version_id is None
    assert db.versions == []
    db.commit.assert_awaited_once()


@pytest.mark.unit
async def test_apply_skill_evolution_job_rejects_cross_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = SimpleNamespace(
        evolution_jobs=[
            SimpleNamespace(
                id="job-other",
                tenant_id="tenant-other",
                skill_name="alpha-skill",
                action="improve_skill",
                status="pending_review",
                rationale=None,
                candidate_content="# Other",
                session_ids=[],
                skill_version_id=None,
                created_at=datetime.now(UTC),
                applied_at=None,
            )
        ],
        commit=AsyncMock(),
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.skill_evolution.repository.SkillEvolutionRepository",
        _MemoryEvolutionRepository,
    )

    with pytest.raises(HTTPException) as exc_info:
        await router.apply_skill_evolution_job(
            job_id="job-other",
            db=db,
            tenant={"id": "tenant-1"},
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    db.commit.assert_not_awaited()


@pytest.mark.unit
async def test_apply_tenant_skill_evolution_job_requires_tenant_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = SimpleNamespace(
        evolution_jobs=[
            SimpleNamespace(
                id="job-tenant",
                tenant_id="tenant-1",
                project_id=None,
                skill_name="alpha-skill",
                action="improve_skill",
                status="pending_review",
                rationale=None,
                candidate_content="# Tenant update",
                session_ids=[],
                skill_version_id=None,
                created_at=datetime.now(UTC),
                applied_at=None,
            )
        ],
        commit=AsyncMock(),
    )
    write_guard = AsyncMock(
        side_effect=HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.skill_evolution.repository.SkillEvolutionRepository",
        _MemoryEvolutionRepository,
    )
    monkeypatch.setattr(router, "_ensure_tenant_skill_write_access", write_guard)

    with pytest.raises(HTTPException) as exc_info:
        await router.apply_skill_evolution_job(
            job_id="job-tenant",
            db=db,
            tenant={"id": "tenant-1"},
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    db.commit.assert_not_awaited()


@pytest.mark.unit
async def test_apply_skill_evolution_job_rejects_project_without_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = SimpleNamespace(
        skill_repo=_MemorySkillRepository(),
        evolution_jobs=[
            SimpleNamespace(
                id="job-project",
                tenant_id="tenant-1",
                project_id="project-1",
                skill_name="alpha-skill",
                action="improve_skill",
                status="pending_review",
                rationale=None,
                candidate_content="# Project update",
                session_ids=[],
                skill_version_id=None,
                created_at=datetime.now(UTC),
                applied_at=None,
            )
        ],
        commit=AsyncMock(),
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_repository.SqlSkillRepository",
        _MemorySqlSkillRepository,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.skill_evolution.repository.SkillEvolutionRepository",
        _MemoryEvolutionRepository,
    )
    monkeypatch.setattr(
        router,
        "_ensure_project_skill_access",
        AsyncMock(
            side_effect=HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        await router.apply_skill_evolution_job(
            job_id="job-project",
            db=db,
            tenant={"id": "tenant-1"},
            current_user=SimpleNamespace(id="user-2"),
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    db.commit.assert_not_awaited()


@pytest.mark.unit
async def test_apply_skill_evolution_job_targets_project_skill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _MemorySkillRepository()
    tenant_skill = Skill.create(
        tenant_id="tenant-1",
        name="alpha-skill",
        description="Tenant skill",
        tools=["Read"],
        full_content="# Tenant Skill",
    )
    project_skill = Skill.create(
        tenant_id="tenant-1",
        project_id="project-1",
        name="alpha-skill",
        description="Project skill",
        tools=["Read"],
        full_content="# Project Skill",
        scope=SkillScope.PROJECT,
    )
    await repo.create(tenant_skill)
    await repo.create(project_skill)
    db = SimpleNamespace(
        skill_repo=repo,
        versions=[],
        evolution_jobs=[
            SimpleNamespace(
                id="job-project-apply",
                tenant_id="tenant-1",
                project_id="project-1",
                skill_name="alpha-skill",
                action="improve_skill",
                status="pending_review",
                rationale="Improve project instructions",
                candidate_content="# Improved Project Skill",
                session_ids=["s-project"],
                skill_version_id=None,
                created_at=datetime.now(UTC),
                applied_at=None,
            )
        ],
        commit=AsyncMock(),
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_repository.SqlSkillRepository",
        _MemorySqlSkillRepository,
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository."
        "SqlSkillVersionRepository",
        _MemoryVersionRepository,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.skill_evolution.repository.SkillEvolutionRepository",
        _MemoryEvolutionRepository,
    )
    ensure_access = AsyncMock()
    monkeypatch.setattr(router, "_ensure_project_skill_access", ensure_access)

    response = await router.apply_skill_evolution_job(
        job_id="job-project-apply",
        db=db,
        tenant={"id": "tenant-1"},
        current_user=SimpleNamespace(id="user-1"),
    )

    assert response.project_id == "project-1"
    assert response.status == "applied"
    assert tenant_skill.full_content == "# Tenant Skill"
    assert project_skill.full_content == "# Improved Project Skill"
    assert db.versions[0].skill_id == project_skill.id
    ensure_access.assert_awaited_once()
    assert ensure_access.await_args.kwargs["required_roles"] == router._PROJECT_SKILL_WRITE_ROLES
    db.commit.assert_awaited_once()


@pytest.mark.unit
async def test_update_skill_evolution_config_requires_tenant_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = SimpleNamespace(commit=AsyncMock())
    write_guard = AsyncMock(
        side_effect=HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    )
    monkeypatch.setattr(router, "_ensure_tenant_skill_write_access", write_guard)

    with pytest.raises(HTTPException) as exc_info:
        await router.update_skill_evolution_config(
            payload=router.SkillEvolutionConfigUpdateRequest(enabled=True),
            db=db,
            tenant={"id": "tenant-1"},
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    db.commit.assert_not_awaited()


@pytest.mark.unit
async def test_run_skill_evolution_queues_single_skill_cycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _MemorySkillRepository()
    skill = Skill.create(
        tenant_id="tenant-1",
        name="alpha-skill",
        description="Manages Agent Skills packages",
        tools=["Read"],
    )
    await repo.create(skill)
    db = SimpleNamespace(skill_repo=repo)
    plugin = SimpleNamespace(
        schedule_evolution=MagicMock(return_value={"scheduled": True, "status": "queued"})
    )
    container = SimpleNamespace(skill_evolution_plugin=lambda: plugin)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(container=SimpleNamespace(with_db=lambda _db: container))
        )
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_repository.SqlSkillRepository",
        _MemorySqlSkillRepository,
    )

    response = await router.run_skill_evolution(
        request=request,
        skill_id=skill.id,
        db=db,
        tenant={"id": "tenant-1"},
    )

    assert response.result == {"scheduled": True, "status": "queued"}
    plugin.schedule_evolution.assert_called_once_with(
        tenant_id="tenant-1",
        project_id=None,
        skill_name="alpha-skill",
    )


@pytest.mark.unit
async def test_run_tenant_skill_evolution_queues_tenant_cycle() -> None:
    plugin = SimpleNamespace(
        schedule_evolution=MagicMock(return_value={"scheduled": True, "status": "queued"})
    )
    container = SimpleNamespace(skill_evolution_plugin=lambda: plugin)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(container=SimpleNamespace(with_db=lambda _db: container))
        )
    )

    response = await router.run_tenant_skill_evolution(
        request=request,
        db=SimpleNamespace(),
        tenant={"id": "tenant-1"},
    )

    assert response.tenant_id == "tenant-1"
    assert response.result == {"scheduled": True, "status": "queued"}
    plugin.schedule_evolution.assert_called_once_with(
        tenant_id="tenant-1",
        project_id=None,
        skill_name=None,
    )


@pytest.mark.unit
async def test_run_tenant_skill_evolution_requires_tenant_admin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = SimpleNamespace(
        schedule_evolution=MagicMock(return_value={"scheduled": True, "status": "queued"})
    )
    container = SimpleNamespace(skill_evolution_plugin=lambda: plugin)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(container=SimpleNamespace(with_db=lambda _db: container))
        )
    )
    write_guard = AsyncMock(
        side_effect=HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    )
    monkeypatch.setattr(router, "_ensure_tenant_skill_write_access", write_guard)

    with pytest.raises(HTTPException) as exc_info:
        await router.run_tenant_skill_evolution(
            request=request,
            db=SimpleNamespace(),
            tenant={"id": "tenant-1"},
            current_user=SimpleNamespace(id="user-1"),
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
    plugin.schedule_evolution.assert_not_called()


@pytest.mark.unit
async def test_run_tenant_skill_evolution_rejects_missing_plugin() -> None:
    container = SimpleNamespace(skill_evolution_plugin=lambda: None)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(container=SimpleNamespace(with_db=lambda _db: container))
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        await router.run_tenant_skill_evolution(
            request=request,
            db=SimpleNamespace(),
            tenant={"id": "tenant-1"},
        )

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
