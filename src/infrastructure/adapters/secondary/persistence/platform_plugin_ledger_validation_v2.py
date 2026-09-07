"""Strict distribution and receipt validation for the durable V2 ledger."""

from src.domain.model.plugins.generated_v2 import (
    ApplyStatusV2,
    ControlPlaneEnvelopeV2,
    ProfileSnapshotV2,
)
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2.protocol import (
    PLUGIN_PROFILE_TYPE_URL_V2,
    control_envelope_v2_to_payload,
    parse_control_envelope_v2,
    parse_profile_snapshot_v2,
    profile_snapshot_v2_to_payload,
)
from src.infrastructure.plugins.v2.runtime_host import (
    PlatformPluginDistributionV2,
    PlatformPluginPublicationV2,
)


def requested_distribution_v2(
    snapshot: ProfileSnapshotV2, envelope: ControlPlaneEnvelopeV2
) -> PlatformPluginDistributionV2:
    """Validate typed input as wire data before any persistence or version allocation."""
    snapshot = parse_profile_snapshot_v2(profile_snapshot_v2_to_payload(snapshot))
    envelope = parse_control_envelope_v2(control_envelope_v2_to_payload(envelope))
    if (
        envelope.snapshot_digest != snapshot.digest
        or envelope.type_url != PLUGIN_PROFILE_TYPE_URL_V2
    ):
        raise ValueError("plugin v2 requested envelope does not match snapshot")
    return PlatformPluginDistributionV2(
        descriptor=PluginGenerationDescriptorV2(
            profile_id=snapshot.profile_id, generation=snapshot.generation, digest=snapshot.digest
        ),
        snapshot=snapshot,
        envelope=envelope,
    )


def _validate_receipt(publication: PlatformPluginPublicationV2) -> None:
    receipt = publication.receipt
    envelope = publication.envelope
    if (
        receipt.requested_version != envelope.version
        or receipt.requested_digest != publication.snapshot.digest
        or envelope.snapshot_digest != publication.snapshot.digest
    ):
        raise ValueError("plugin v2 receipt does not match publication")
    if receipt.status is ApplyStatusV2.ACK:
        if (
            receipt.applied_version != receipt.requested_version
            or receipt.applied_digest != receipt.requested_digest
            or receipt.error_code is not None
            or receipt.error_message is not None
        ):
            raise ValueError("plugin v2 ACK receipt is inconsistent")
    elif not receipt.error_code or not receipt.error_message:
        raise ValueError("plugin v2 NACK receipt requires an error code and message")


def validate_publication_receipt_v2(publication: PlatformPluginPublicationV2) -> None:
    """Validate the observed receipt used by the compatibility publication API."""
    _validate_receipt(publication)
