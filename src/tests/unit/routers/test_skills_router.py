from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

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


def _make_zip(files: dict[str, bytes | str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for path, content in files.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            archive.writestr(path, data)
    return buffer.getvalue()


class _SkillRepository:
    async def create(self, _skill: object) -> object:
        raise ValueError("Skill name 'Bad Name' must be lowercase with hyphens only")


class _Container:
    def skill_repository(self) -> _SkillRepository:
        return _SkillRepository()


class _MemorySkillRepository:
    def __init__(self) -> None:
        self.skills_by_id: dict[str, Skill] = {}
        self.skills_by_name: dict[str, Skill] = {}

    async def create(self, skill: Skill) -> Skill:
        self.skills_by_id[skill.id] = skill
        self.skills_by_name[skill.name] = skill
        return skill

    async def get_by_id(self, skill_id: str) -> Skill | None:
        return self.skills_by_id.get(skill_id)

    async def get_by_name(
        self,
        tenant_id: str,
        name: str,
        scope: SkillScope | None = None,
    ) -> Skill | None:
        skill = self.skills_by_name.get(name)
        if not skill or skill.tenant_id != tenant_id:
            return None
        if scope and skill.scope != scope:
            return None
        return skill

    async def update(self, skill: Skill) -> Skill:
        self.skills_by_id[skill.id] = skill
        self.skills_by_name[skill.name] = skill
        return skill

    async def delete(self, skill_id: str) -> bool:
        self.skills_by_id.pop(skill_id, None)
        return True

    async def list_by_tenant(self, *_args: object, **_kwargs: object) -> list[Skill]:
        return list(self.skills_by_id.values())

    async def list_by_project(self, project_id: str, *_args: object, **_kwargs: object) -> list[Skill]:
        return [skill for skill in self.skills_by_id.values() if skill.project_id == project_id]

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
        versions = [version.version_number for version in self._db.versions if version.skill_id == skill_id]
        return max(versions, default=0)

    async def count_by_skill(self, skill_id: str) -> int:
        return len([version for version in self._db.versions if version.skill_id == skill_id])


class _MemorySqlSkillRepository:
    def __init__(self, db: SimpleNamespace) -> None:
        self._repo = db.skill_repo

    async def get_by_id(self, skill_id: str) -> Skill | None:
        return await self._repo.get_by_id(skill_id)


class _MemoryEvolutionRepository:
    def __init__(self, db: SimpleNamespace) -> None:
        self._db = db

    async def list_jobs(
        self,
        *,
        tenant_id: str,
        status: str | None = None,
        skill_name: str | None = None,
        limit: int = 50,
    ) -> list[SimpleNamespace]:
        jobs = [
            job
            for job in self._db.evolution_jobs
            if job.tenant_id == tenant_id
            and (status is None or job.status == status)
            and (skill_name is None or job.skill_name == skill_name)
        ]
        return jobs[:limit]

    async def count_sessions_by_skill(self, *, tenant_id: str, skill_name: str) -> int:
        return sum(
            1
            for session in self._db.evolution_sessions
            if session.tenant_id == tenant_id and session.skill_name == skill_name
        )

    async def get_overview_stats(self, *, tenant_id: str) -> dict[str, object]:
        sessions = [
            session
            for session in self._db.evolution_sessions
            if session.tenant_id == tenant_id
        ]
        jobs = [
            job for job in self._db.evolution_jobs if job.tenant_id == tenant_id
        ]
        scores = [
            session.overall_score
            for session in sessions
            if getattr(session, "overall_score", None) is not None
        ]
        return {
            "total_sessions": len(sessions),
            "skill_sessions": sum(1 for s in sessions if s.skill_name != "__no_skill__"),
            "no_skill_sessions": sum(1 for s in sessions if s.skill_name == "__no_skill__"),
            "unprocessed_sessions": sum(1 for s in sessions if not s.processed),
            "processed_sessions": sum(1 for s in sessions if s.processed),
            "scored_sessions": len(scores),
            "successful_sessions": sum(1 for s in sessions if s.success),
            "avg_score": sum(scores) / len(scores) if scores else None,
            "total_jobs": len(jobs),
            "pending_jobs": sum(1 for j in jobs if j.status == "pending_review"),
            "applied_jobs": sum(1 for j in jobs if j.status == "applied"),
            "skipped_jobs": sum(1 for j in jobs if j.status == "skipped"),
        }

    async def get_skill_session_summaries(
        self,
        *,
        tenant_id: str,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        sessions = [
            session
            for session in self._db.evolution_sessions
            if session.tenant_id == tenant_id
        ]
        jobs = [
            job for job in self._db.evolution_jobs if job.tenant_id == tenant_id
        ]
        summaries: list[dict[str, object]] = []
        for skill_name in sorted({session.skill_name for session in sessions}):
            skill_sessions = [session for session in sessions if session.skill_name == skill_name]
            skill_jobs = [job for job in jobs if job.skill_name == skill_name]
            scores = [
                session.overall_score
                for session in skill_sessions
                if getattr(session, "overall_score", None) is not None
            ]
            summaries.append(
                {
                    "skill_name": skill_name,
                    "session_count": len(skill_sessions),
                    "success_count": sum(1 for session in skill_sessions if session.success),
                    "unprocessed_count": sum(
                        1 for session in skill_sessions if not session.processed
                    ),
                    "scored_count": len(scores),
                    "avg_score": sum(scores) / len(scores) if scores else None,
                    "latest_session_at": max(
                        session.created_at for session in skill_sessions
                    ),
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
                summary["skill_name"] == "__no_skill__",
                -int(summary["session_count"]),
                str(summary["skill_name"]),
            ),
        )[:limit]

    async def list_recent_sessions(
        self,
        *,
        tenant_id: str,
        skill_name: str | None = None,
        limit: int = 50,
    ) -> list[SimpleNamespace]:
        sessions = [
            session
            for session in self._db.evolution_sessions
            if session.tenant_id == tenant_id
            and (skill_name is None or session.skill_name == skill_name)
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

    assert router._skill_matches_search(skill, "platform")
    assert router._skill_matches_search(skill, "1.2")
    assert router._skill_matches_search(skill, "packages")
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
async def test_get_skill_version_sanitizes_missing_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _VersionRepository:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_version(self, _skill_id: str, _version_number: int) -> object | None:
            return None

    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository."
        "SqlSkillVersionRepository",
        _VersionRepository,
    )

    with pytest.raises(HTTPException) as exc_info:
        await router.get_skill_version(
            skill_id="skill-secret",
            version_number=42,
            db=SimpleNamespace(),
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
        "src.infrastructure.adapters.secondary.persistence.sql_skill_repository."
        "SqlSkillRepository",
        _MemorySqlSkillRepository,
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_version_repository."
        "SqlSkillVersionRepository",
        _MemoryVersionRepository,
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.skill_evolution.repository."
        "SkillEvolutionRepository",
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


@pytest.mark.unit
async def test_get_skill_evolution_overview_returns_global_capture_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_at = datetime.now(UTC)
    db = SimpleNamespace(
        evolution_jobs=[
            SimpleNamespace(
                id="job-1",
                tenant_id="tenant-1",
                skill_name="alpha-skill",
                action="improve_skill",
                status="pending_review",
                rationale="Missing setup step",
                session_ids=["s1"],
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
        ],
    )
    monkeypatch.setattr(
        "src.infrastructure.agent.plugins.skill_evolution.repository."
        "SkillEvolutionRepository",
        _MemoryEvolutionRepository,
    )

    response = await router.get_skill_evolution_overview(
        skill_limit=20,
        session_limit=20,
        job_limit=20,
        db=db,
        tenant={"id": "tenant-1"},
    )

    assert response.stats.total_sessions == 2
    assert response.stats.skill_sessions == 1
    assert response.stats.no_skill_sessions == 1
    assert response.stats.pending_jobs == 1
    assert response.skills[0].skill_name == "alpha-skill"
    assert response.skills[0].session_count == 1
    assert response.recent_sessions[0].id in {"s1", "s2"}
    assert response.recent_jobs[0].id == "job-1"
    assert response.trigger.manual_trigger == "/api/v1/skills/{skill_id}/evolution/run"


@pytest.mark.unit
async def test_run_skill_evolution_triggers_single_skill_cycle(
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
    plugin = SimpleNamespace(trigger_evolution=AsyncMock(return_value={"jobs": 1}))
    container = SimpleNamespace(skill_evolution_plugin=lambda: plugin)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                container=SimpleNamespace(with_db=lambda _db: container)
            )
        )
    )
    monkeypatch.setattr(
        "src.infrastructure.adapters.secondary.persistence.sql_skill_repository."
        "SqlSkillRepository",
        _MemorySqlSkillRepository,
    )

    response = await router.run_skill_evolution(
        request=request,
        skill_id=skill.id,
        db=db,
        tenant={"id": "tenant-1"},
    )

    assert response.result == {"jobs": 1}
    plugin.trigger_evolution.assert_awaited_once_with(
        tenant_id="tenant-1",
        project_id=None,
        skill_name="alpha-skill",
    )
