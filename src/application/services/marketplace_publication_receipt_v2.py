"""Persist the actual ROOT marketplace outcome with a separately owned session."""

from collections.abc import Callable
from typing import Any

from src.infrastructure.adapters.secondary.persistence.platform_plugin_publication_v2 import (
    PYTHON_API_DATA_PLANE_ID_V2,
    PlatformPluginPublicationPolicyV2,
)
from src.infrastructure.adapters.secondary.persistence.platform_plugin_repository_v2 import (
    PlatformPluginRepositoryV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginPublicationV2


async def persist_marketplace_receipt_v2(
    session_factory: Callable[[], Any],
    publication: PlatformPluginPublicationV2,
    *,
    policy: PlatformPluginPublicationPolicyV2,
) -> None:
    """Write only a receipt for an already committed request, including idempotent retries."""
    async with session_factory() as session:
        repository = PlatformPluginRepositoryV2(session)
        if PYTHON_API_DATA_PLANE_ID_V2 in policy.required_data_plane_ids:
            _ = await repository.record_data_plane_receipt(
                data_plane_id=PYTHON_API_DATA_PLANE_ID_V2,
                nonce=publication.envelope.nonce,
                receipt=publication.receipt,
            )
        else:
            latest = await repository.latest_publication_readiness()
            if latest is None or latest.nonce != publication.envelope.nonce:
                raise RuntimeV2Error("root_publication_changed", "ROOT request was superseded")
        await session.commit()
