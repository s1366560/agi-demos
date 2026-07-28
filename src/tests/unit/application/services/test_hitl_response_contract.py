"""Tests for the replay-safe HITL response contract."""

import json

from src.application.services.hitl_response_contract import (
    build_hitl_response_digest,
    merge_hitl_response_contract_metadata,
    read_hitl_response_contract_metadata,
)


def test_response_digest_is_stable_without_persisting_plaintext() -> None:
    response_data = {"values": {"API_KEY": "unit-secret-value"}, "save": False}

    first = build_hitl_response_digest(
        secret="unit-test-secret",
        request_id="req-1",
        hitl_type="env_var",
        response_data=response_data,
    )
    second = build_hitl_response_digest(
        secret="unit-test-secret",
        request_id="req-1",
        hitl_type="env_var",
        response_data={"save": False, "values": {"API_KEY": "unit-secret-value"}},
    )

    assert first == second
    assert first != build_hitl_response_digest(
        secret="unit-test-secret",
        request_id="req-1",
        hitl_type="env_var",
        response_data={"values": {"API_KEY": "different"}, "save": False},
    )
    assert "unit-secret-value" not in first


def test_response_contract_metadata_preserves_sealed_payload_without_exposing_values() -> None:
    metadata = merge_hitl_response_contract_metadata(
        {"sealed_response": "ciphertext", "variable_names": ["API_KEY"]},
        expected_revision=1,
        idempotency_key="desktop:req-1:env_var",
        payload_digest="a" * 64,
    )

    contract = read_hitl_response_contract_metadata(metadata)

    assert contract is not None
    assert contract.contract_version == 2
    assert contract.expected_revision == 1
    assert contract.idempotency_key == "desktop:req-1:env_var"
    assert contract.payload_digest == "a" * 64
    assert metadata["sealed_response"] == "ciphertext"
    assert "unit-secret-value" not in json.dumps(metadata)


def test_malformed_response_contract_metadata_fails_closed() -> None:
    assert (
        read_hitl_response_contract_metadata(
            {
                "_hitl_response_contract": {
                    "contract_version": 2,
                    "expected_revision": 1,
                    "idempotency_key": "",
                    "payload_digest": "a" * 64,
                }
            }
        )
        is None
    )
