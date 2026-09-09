"""Deployment receipts are structural evidence, never an enable switch."""

import pytest

from src.domain.model.cron.cutover import (
    CronDeploymentManifest,
    CronDeploymentReceipt,
    CronReverseDrainCompletion,
    CronReverseDrainObservation,
)

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


def reverse_observation_wire():
    return {
        "protocol": "cron-reverse-drain-observation.v1",
        "counts": {
            "active_rust_owner_lease": 0,
            "live_running_runs": 0,
            "queued_runs": 2,
            "waiting_human_runs": 1,
        },
        "terminal_outcomes": {"success": 3, "failed": 1},
        "last_run_ids": ["run-9", "run-7"],
        "observed_at": "2026-09-09T01:02:03+00:00",
    }


def reverse_completion_wire():
    return {
        "protocol": "cron-reverse-drain-completion.v1",
        "completed_at": "2026-09-09T02:03:04+00:00",
        "final_observation": reverse_observation_wire(),
    }


def test_reverse_drain_observation_and_completion_round_trip():
    observation = CronReverseDrainObservation.from_wire(reverse_observation_wire())
    assert observation.to_wire() == reverse_observation_wire()
    completion = CronReverseDrainCompletion.from_wire(reverse_completion_wire())
    assert completion.to_wire() == reverse_completion_wire()


@pytest.mark.parametrize("field", ["verified", "enable", "force", "activate_python"])
def test_reverse_drain_records_cannot_carry_an_enable_or_force_override(field):
    with pytest.raises(ValueError):
        CronReverseDrainObservation.from_wire(reverse_observation_wire() | {field: True})
    with pytest.raises(ValueError):
        CronReverseDrainCompletion.from_wire(reverse_completion_wire() | {field: True})


@pytest.mark.parametrize("outcome", ["running", "queued", "waiting_human", "unknown"])
def test_reverse_drain_terminal_outcomes_only_accept_terminal_protocol_states(outcome):
    wire = reverse_observation_wire()
    wire["terminal_outcomes"] = {outcome: 1}
    with pytest.raises(ValueError):
        CronReverseDrainObservation.from_wire(wire)


@pytest.mark.parametrize("count", [-1, 1.5, "2", True])
def test_reverse_drain_counts_are_non_negative_integers(count):
    wire = reverse_observation_wire()
    wire["counts"] = {"queued_runs": count}
    with pytest.raises(ValueError):
        CronReverseDrainObservation.from_wire(wire)


def test_reverse_drain_run_id_roster_is_bounded_and_unique():
    wire = reverse_observation_wire()
    wire["last_run_ids"] = ["run-1", "run-1"]
    with pytest.raises(ValueError):
        CronReverseDrainObservation.from_wire(wire)
    wire["last_run_ids"] = [f"run-{index}" for index in range(101)]
    with pytest.raises(ValueError):
        CronReverseDrainObservation.from_wire(wire)
