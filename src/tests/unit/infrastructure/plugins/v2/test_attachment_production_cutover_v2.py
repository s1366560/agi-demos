"""Production cutover coverage for generation-owned attachment access."""

from __future__ import annotations

import json
from dataclasses import replace
from inspect import signature
from pathlib import Path
from typing import Any, cast

import pytest

from src.domain.model.agent.attachment import Attachment, AttachmentPurpose, AttachmentStatus
from src.infrastructure.adapters.primary.web.attachment_application_authority_v2 import (
    AttachmentApplicationAuthorityV2,
)
from src.infrastructure.adapters.primary.web.routers import attachments_upload
from src.infrastructure.plugins.v2.artifact_content_gc_runtime import OBJECT_STORAGE_SERVICE_V2
from src.infrastructure.plugins.v2.attachment_services import (
    ATTACHMENT_APPLICATION_MODULE_V2,
    ATTACHMENT_PROVIDER_INJECT_V2,
    ATTACHMENT_PROVIDER_MODULE_V2,
    ATTACHMENT_PROVIDER_SERVICE_V2,
    ATTACHMENT_STORAGE_INJECT_V2,
    AttachmentAccessDeniedV2,
    AttachmentApplicationServiceV2,
    AttachmentNotFoundV2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, RuntimeV2Error

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_ROUTER_PATH = _ROOT / "src/infrastructure/adapters/primary/web/routers/attachments_upload.py"


def _attachment(
    attachment_id: str,
    *,
    project_id: str,
    tenant_id: str,
) -> Attachment:
    return Attachment(
        id=attachment_id,
        conversation_id="conversation-1",
        project_id=project_id,
        tenant_id=tenant_id,
        filename=f"{attachment_id}.txt",
        mime_type="text/plain",
        size_bytes=12,
        object_key=f"attachments/{attachment_id}.txt",
        purpose=AttachmentPurpose.BOTH,
        status=AttachmentStatus.UPLOADED,
    )


class _FakeAttachmentService:
    def __init__(self, attachments: tuple[Attachment, ...]) -> None:
        self._attachments = {attachment.id: attachment for attachment in attachments}

    async def get(self, attachment_id: str) -> Attachment | None:
        return self._attachments.get(attachment_id)

    async def get_by_conversation(
        self,
        conversation_id: str,
        status: AttachmentStatus | None = None,
    ) -> list[Attachment]:
        return [
            attachment
            for attachment in self._attachments.values()
            if attachment.conversation_id == conversation_id
            and (status is None or attachment.status is status)
        ]


class _FakeAccess:
    def __init__(self, project_tenants: dict[str, str]) -> None:
        self.project_tenants = project_tenants
        self.calls: list[tuple[frozenset[str], str, bool]] = []

    async def accessible_project_tenants(
        self,
        *,
        project_ids: frozenset[str],
        user_id: str,
        is_superuser: bool,
    ) -> dict[str, str]:
        self.calls.append((project_ids, user_id, is_superuser))
        return {
            project_id: tenant_id
            for project_id, tenant_id in self.project_tenants.items()
            if project_id in project_ids
        }


def test_attachment_provider_and_consumer_are_explicit_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entries = {entry.module_ref: entry for entry in document.entries}
    ordered_modules = tuple(entry.module_ref for entry in document.entries)

    assert entries[ATTACHMENT_PROVIDER_MODULE_V2].inject == {}
    assert entries[ATTACHMENT_APPLICATION_MODULE_V2].inject == {
        ATTACHMENT_PROVIDER_INJECT_V2: ATTACHMENT_PROVIDER_SERVICE_V2,
        ATTACHMENT_STORAGE_INJECT_V2: OBJECT_STORAGE_SERVICE_V2,
    }
    assert ordered_modules.index(ATTACHMENT_PROVIDER_MODULE_V2) < ordered_modules.index(
        ATTACHMENT_APPLICATION_MODULE_V2
    )


def test_attachment_manifest_declares_provider_and_consumer_contracts() -> None:
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    modules = {module.module_ref: module for module in manifest.modules}

    assert [
        provided.service
        for provided in modules[ATTACHMENT_PROVIDER_MODULE_V2].contract.services.provides
    ] == [ATTACHMENT_PROVIDER_SERVICE_V2]
    assert modules[ATTACHMENT_PROVIDER_MODULE_V2].contract.services.requires == ()
    assert {
        required.alias: required.service
        for required in modules[ATTACHMENT_APPLICATION_MODULE_V2].contract.services.requires
    } == {
        ATTACHMENT_PROVIDER_INJECT_V2: ATTACHMENT_PROVIDER_SERVICE_V2,
        ATTACHMENT_STORAGE_INJECT_V2: OBJECT_STORAGE_SERVICE_V2,
    }


async def test_missing_attachment_provider_fails_closed_without_sql_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == ATTACHMENT_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        disabled,
        {manifest.plugin_id: manifest},
        generation=154,
    )

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-attachment-services" in str(error.value)


async def test_application_service_uses_provider_access_for_authorization() -> None:
    visible = _attachment("visible", project_id="project-1", tenant_id="tenant-1")
    wrong_tenant = _attachment(
        "wrong-tenant",
        project_id="project-1",
        tenant_id="tenant-other",
    )
    hidden = _attachment("hidden", project_id="project-2", tenant_id="tenant-2")
    access = _FakeAccess({"project-1": "tenant-1"})
    application = AttachmentApplicationServiceV2(
        service=cast(Any, _FakeAttachmentService((visible, wrong_tenant, hidden))),
        access=cast(Any, access),
        user_id="user-1",
        is_superuser=False,
    )

    assert await application.require_project_tenant("project-1") == "tenant-1"
    assert await application.get_authorized("visible") is visible
    listed = await application.list_visible(
        conversation_id="conversation-1",
        status=None,
    )

    assert listed == [visible]
    assert access.calls == [
        (frozenset({"project-1"}), "user-1", False),
        (frozenset({"project-1"}), "user-1", False),
        (frozenset({"project-1", "project-2"}), "user-1", False),
    ]


async def test_application_service_distinguishes_not_found_and_tenant_denial() -> None:
    wrong_tenant = _attachment(
        "wrong-tenant",
        project_id="project-1",
        tenant_id="tenant-other",
    )
    application = AttachmentApplicationServiceV2(
        service=cast(Any, _FakeAttachmentService((wrong_tenant,))),
        access=cast(Any, _FakeAccess({"project-1": "tenant-1"})),
        user_id="user-1",
        is_superuser=False,
    )

    with pytest.raises(AttachmentNotFoundV2):
        await application.get_authorized("missing")
    with pytest.raises(AttachmentAccessDeniedV2):
        await application.get_authorized("wrong-tenant")


def test_attachment_router_has_no_static_db_or_access_authority() -> None:
    source = _ROUTER_PATH.read_text(encoding="utf-8")
    forbidden = {
        "sqlalchemy",
        "AsyncSession",
        "get_db",
        "get_current_user",
        "_verify_project_access",
        "_get_accessible_attachment_project_tenants",
        "_get_authorized_attachment",
    }

    assert all(name not in source for name in forbidden)
    for handler_name in (
        "initiate_multipart_upload",
        "upload_part",
        "complete_multipart_upload",
        "abort_multipart_upload",
        "upload_simple",
        "list_attachments",
        "get_attachment",
        "download_attachment",
        "delete_attachment",
    ):
        parameters = signature(getattr(attachments_upload, handler_name)).parameters
        assert "attachment_application" in parameters
        assert "current_user" not in parameters
        assert "db" not in parameters
        assert "attachment_service" not in parameters


def test_attachment_authority_owns_identity_db_and_application_services() -> None:
    fields = AttachmentApplicationAuthorityV2.__dataclass_fields__

    assert set(fields) == {"operation", "db", "current_user", "services"}
    assert "service" not in fields
