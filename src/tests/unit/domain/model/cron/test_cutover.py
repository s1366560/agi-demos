"""Deployment receipts are structural evidence, never an enable switch."""

import pytest

from src.domain.model.cron.cutover import CronDeploymentManifest, CronDeploymentReceipt

pytestmark = pytest.mark.unit


def manifest_wire():
    return {
        "protocol": "cron-deployment-inventory.v1",
        "deployment_id": "deployment-1",
        "source_generation": "python-old",
        "target_generation": "rust-new",
        "participants": [{"kind": "producer", "participant_id": "python-api-1"}],
    }


def receipt_wire():
    return {
        "protocol": "cron-deployment-drain-receipt.v1",
        "receipt_id": "receipt-1",
        "deployment_id": "deployment-1",
        "source_generation": "python-old",
        "participant": {"kind": "producer", "participant_id": "python-api-1"},
        "observation": "closed",
        "evidence_sha256": "a" * 64,
    }


def test_manifest_and_receipt_round_trip_preserve_protocol_identity():
    assert CronDeploymentManifest.from_wire(manifest_wire()).to_wire() == manifest_wire()
    assert CronDeploymentReceipt.from_wire(receipt_wire()).to_wire() == receipt_wire()


@pytest.mark.parametrize("field", ["verified", "enable", "force", "verifier_id"])
def test_receipts_cannot_carry_an_enable_or_verification_override(field):
    wire = receipt_wire() | {field: True}
    with pytest.raises(ValueError):
        CronDeploymentReceipt.from_wire(wire)


def test_empty_or_duplicate_participants_cannot_define_deployment_inventory():
    wire = manifest_wire()
    for participants in ([], wire["participants"] * 2):
        with pytest.raises(ValueError):
            CronDeploymentManifest.from_wire(wire | {"participants": participants})


@pytest.mark.parametrize("observation", [True, "verified", "success", "expired"])
def test_only_explicit_deployment_observations_are_accepted(observation):
    with pytest.raises(ValueError):
        CronDeploymentReceipt.from_wire(receipt_wire() | {"observation": observation})


def test_receipt_payloads_cannot_contain_raw_logs_or_credentials():
    with pytest.raises(ValueError):
        CronDeploymentReceipt.from_wire(receipt_wire() | {"log": "sensitive content"})
    with pytest.raises(ValueError):
        CronDeploymentReceipt.from_wire(receipt_wire() | {"evidence_sha256": "invalid"})
