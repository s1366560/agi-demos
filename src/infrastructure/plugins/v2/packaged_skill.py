"""Attested Skill resources registered by protocol-v2 Profile entries."""

from __future__ import annotations

import hashlib
from pathlib import Path

from src.domain.model.agent.skill import Skill, SkillScope, SkillStatus
from src.domain.model.agent.skill.skill_source import SkillSource
from src.infrastructure.skill.markdown_parser import MarkdownParser
from src.infrastructure.skill.validator import AllowedTool

from .runtime import RuntimeV2Error

_SKILLS_ROOT = Path(__file__).resolve().parent / "skills"


def packaged_skill_digest_v2(skill_name: str) -> str:
    """Return a framed digest covering SKILL.md and every packaged resource."""
    skill_dir = _skill_directory_v2(skill_name)
    files = tuple(sorted(path for path in skill_dir.rglob("*") if path.is_file()))
    if not files or not (skill_dir / "SKILL.md").is_file():
        raise RuntimeV2Error(
            "packaged_skill_missing",
            f"V2 Skill package {skill_name} is unavailable",
        )
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(skill_dir).as_posix().encode("utf-8")
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise RuntimeV2Error(
                "packaged_skill_unreadable",
                f"V2 Skill package {skill_name} contains an unreadable resource",
            ) from exc
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return f"sha256:{digest.hexdigest()}"


def build_packaged_skill_v2(
    *,
    skill_name: str,
    expected_digest: str,
    tenant_id: str,
    project_id: str | None = None,
) -> Skill:
    """Build one tenant-scoped Skill after attesting its complete resource package."""
    normalized_tenant_id = tenant_id.strip()
    if not normalized_tenant_id:
        raise ValueError("V2 packaged Skill requires tenant_id")
    normalized_project_id = project_id.strip() if project_id else None
    actual_digest = packaged_skill_digest_v2(skill_name)
    if actual_digest != expected_digest:
        raise RuntimeV2Error(
            "packaged_skill_digest_mismatch",
            f"V2 Skill package {skill_name} differs from its attested contribution",
        )

    skill_dir = _skill_directory_v2(skill_name)
    skill_path = skill_dir / "SKILL.md"
    markdown = MarkdownParser().parse_file(str(skill_path))
    if markdown.name != skill_name:
        raise RuntimeV2Error(
            "packaged_skill_name_mismatch",
            f"V2 Skill package {skill_name} declares a different name",
        )
    tools = markdown.tools or markdown.allowed_tools
    if not tools:
        raise RuntimeV2Error(
            "packaged_skill_tools_missing",
            f"V2 Skill package {skill_name} declares no tools",
        )
    resources = {
        path.relative_to(skill_dir).as_posix(): path.read_text(encoding="utf-8")
        for path in sorted(skill_dir.rglob("*"))
        if path.is_file() and path != skill_path
    }
    metadata = {
        "protocol_version": 2,
        "package_digest": actual_digest,
        "source_type": "v2-profile",
        **(markdown.metadata or {}),
    }
    return Skill(
        id=f"plugin-v2:{skill_name}:{normalized_tenant_id}",
        tenant_id=normalized_tenant_id,
        project_id=normalized_project_id,
        name=markdown.name,
        description=markdown.description,
        tools=list(tools),
        status=SkillStatus.ACTIVE,
        metadata=metadata,
        source=SkillSource.PLUGIN,
        file_path=str(skill_path),
        full_content=markdown.content,
        resource_files=resources,
        agent_modes=markdown.agent,
        scope=SkillScope.TENANT,
        is_system_skill=False,
        license=markdown.license,
        compatibility=markdown.compatibility,
        allowed_tools_raw=markdown.allowed_tools_raw,
        allowed_tools_parsed=(
            AllowedTool.parse_many(markdown.allowed_tools_raw)
            if markdown.allowed_tools_raw
            else []
        ),
        version_label=markdown.version,
    )


def _skill_directory_v2(skill_name: str) -> Path:
    normalized = skill_name.strip()
    if not normalized or normalized in {".", ".."} or "/" in normalized or "\\" in normalized:
        raise ValueError("V2 packaged Skill name must be a single path segment")
    directory = (_SKILLS_ROOT / normalized).resolve()
    if not directory.is_relative_to(_SKILLS_ROOT.resolve()):
        raise ValueError("V2 packaged Skill path escapes the resource root")
    return directory


__all__ = ["build_packaged_skill_v2", "packaged_skill_digest_v2"]
