"""Exact immutable ProfileSource storage, with no external fetch or authorization."""

from copy import deepcopy

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ProfileSourceV2, ScopeV2
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.platform_plugin_profile_source_model_v2 import (
    PlatformPluginV2ProfileSourceModel,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_scope_ledger_v2 import (
    ScopeLedgerBindingV2,
)
from src.infrastructure.plugins.v2.protocol import (
    parse_profile_source_v2,
    profile_source_v2_to_payload,
)
from src.infrastructure.plugins.v2.scope import validate_scope_v2


class PlatformPluginProfileSourceV2Error(ValueError):
    """Stable source CAS or integrity failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def _validated_source(scope: ScopeV2, source: ProfileSourceV2) -> ProfileSourceV2:
    parsed = parse_profile_source_v2(deepcopy(profile_source_v2_to_payload(source)))
    ranks = {"profile": 0, "tenant": 1, "project": 2, "session": 3}
    previous = -1
    for layer in parsed.layers:
        rank = ranks.get(layer.kind.value)
        expected = "root" if layer.kind.value == "profile" else layer.kind.value
        ancestor = validate_scope_v2(layer.scope)
        if rank is None or rank < previous or ancestor.kind.value != expected:
            raise PlatformPluginProfileSourceV2Error(
                "profile_source_layer_invalid", "invalid layer"
            )
        previous = rank
        for field in ("tenant_id", "project_id", "session_id"):
            value = getattr(ancestor, field)
            if value is not None and value != getattr(scope, field):
                raise PlatformPluginProfileSourceV2Error(
                    "profile_source_scope_mismatch", "source layer is not an owner ancestor"
                )
        for entry in (*layer.entries, *layer.replacements):
            if validate_scope_v2(entry.scope) != ancestor:
                raise PlatformPluginProfileSourceV2Error(
                    "profile_source_scope_mismatch", "entry scope differs from layer"
                )
    return parsed


class PlatformPluginProfileSourceRepositoryV2:
    """CAS per scope/source; stored provenance is data, never a trust decision."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self._session = session

    def _decode(
        self, binding: ScopeLedgerBindingV2, row: PlatformPluginV2ProfileSourceModel
    ) -> ProfileSourceV2:
        binding.require_row(row)
        source = _validated_source(binding.scope, parse_profile_source_v2(deepcopy(row.payload)))
        if (source.source_id, source.profile_id, source.revision, source.digest) != (
            row.source_id,
            row.profile_id,
            row.revision,
            row.digest,
        ):
            raise PlatformPluginProfileSourceV2Error(
                "profile_source_identity_mismatch", "stored source identity differs from payload"
            )
        return source

    async def record_source(
        self, *, scope: ScopeV2, source: ProfileSourceV2, expected_revision: int | None
    ) -> ProfileSourceV2:
        binding = ScopeLedgerBindingV2(scope, PlatformPluginProfileSourceV2Error)
        parsed = _validated_source(binding.scope, source)
        if expected_revision is not None and (
            type(expected_revision) is not int or expected_revision < 1
        ):
            raise PlatformPluginProfileSourceV2Error("profile_source_head_conflict", "invalid CAS")
        _ = await binding.lock(self._session)
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV2ProfileSourceModel)
                .where(
                    PlatformPluginV2ProfileSourceModel.scope_key == binding.key,
                    PlatformPluginV2ProfileSourceModel.source_id == parsed.source_id,
                )
                .order_by(PlatformPluginV2ProfileSourceModel.revision.desc())
                .limit(1)
            )
        )
        current = result.scalar_one_or_none()
        if current is not None:
            _ = self._decode(binding, current)
            if current.payload == profile_source_v2_to_payload(parsed):
                return parsed
        revision = None if current is None else current.revision
        if expected_revision != revision:
            raise PlatformPluginProfileSourceV2Error("profile_source_head_conflict", "CAS conflict")
        if parsed.revision != (revision or 0) + 1:
            raise PlatformPluginProfileSourceV2Error("profile_source_revision_gap", "revision gap")
        self._session.add(
            PlatformPluginV2ProfileSourceModel(
                id=PlatformPluginV2ProfileSourceModel.generate_id(),
                **binding.fields,
                source_id=parsed.source_id,
                profile_id=parsed.profile_id,
                revision=parsed.revision,
                digest=parsed.digest,
                payload=deepcopy(profile_source_v2_to_payload(parsed)),
            )
        )
        await self._session.flush()
        return parsed

    async def read_exact(
        self, *, scope: ScopeV2, source_id: str, revision: int, digest: str
    ) -> ProfileSourceV2 | None:
        binding = ScopeLedgerBindingV2(scope, PlatformPluginProfileSourceV2Error)
        if type(revision) is not int or revision < 1:
            raise PlatformPluginProfileSourceV2Error("profile_source_reference_invalid", "revision")
        result = await self._session.execute(
            refresh_select_statement(
                select(PlatformPluginV2ProfileSourceModel).where(
                    PlatformPluginV2ProfileSourceModel.scope_key == binding.key,
                    PlatformPluginV2ProfileSourceModel.source_id == source_id,
                    PlatformPluginV2ProfileSourceModel.revision == revision,
                    PlatformPluginV2ProfileSourceModel.digest == digest,
                )
            )
        )
        row = result.scalar_one_or_none()
        return None if row is None else self._decode(binding, row)
