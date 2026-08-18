import pytest

from src.domain.model.plugins import PluginManifestError, parse_plugin_manifest


@pytest.mark.unit
def test_parse_manifest_returns_immutable_capability_contract() -> None:
    manifest = parse_plugin_manifest(
        {
            "schemaVersion": 1,
            "id": "memstack.feishu-channel",
            "version": "1.2.0",
            "runtime": "subprocess",
            "trust": "tenant-approved",
            "requires": [{"capability": "channel-adapter-contract", "minVersion": "1.0.0"}],
            "provides": [
                {
                    "kind": "channel",
                    "id": "feishu",
                    "contract": "channel:feishu",
                    "permissions": ["channel.message.read"],
                }
            ],
            "activation": {
                "defaultScope": "tenant",
                "restartPolicy": "process-boundary",
            },
        }
    )

    assert manifest.provided_contracts == {"channel:feishu"}
    assert manifest.to_payload()["requires"][0]["min_version"] == "1.0.0"
    assert manifest.to_json().startswith('{"activation":')


@pytest.mark.unit
def test_parse_manifest_collects_all_validation_errors() -> None:
    with pytest.raises(PluginManifestError) as exc_info:
        parse_plugin_manifest(
            {
                "schemaVersion": 2,
                "id": "Bad Id",
                "version": "1",
                "runtime": "python-trusted",
                "trust": "untrusted",
                "provides": [],
            }
        )

    errors = exc_info.value.errors
    assert "schemaVersion must be 1" in errors
    assert any("id must match" in item for item in errors)
    assert any("version must match" in item for item in errors)
    assert "runtime python-trusted requires builtin or signed trust" in errors
    assert "provides is required and must be a non-empty array" in errors


@pytest.mark.unit
def test_manifest_parses_and_preserves_declared_resource_quotas() -> None:
    manifest = parse_plugin_manifest(
        {
            "schemaVersion": 1,
            "id": "third-party-tool",
            "version": "1.0.0",
            "runtime": "wasm",
            "trust": "signed",
            "provides": [{"kind": "tool", "id": "demo", "permissions": ["tools.execute"]}],
            "activation": {
                "defaultScope": "tenant",
                "restartPolicy": "process-boundary",
                "quotas": {
                    "max_wasm_fuel": 1000,
                    "max_wasm_memory_bytes": 65536,
                    "max_wall_time_ms": 50,
                    "max_concurrent_calls": 2,
                    "max_output_bytes": 128,
                    "max_network_requests_per_minute": 3,
                    "max_storage_bytes": 1024,
                    "max_monthly_usd": 0.25,
                },
            },
        }
    )

    assert manifest.to_payload()["activation"]["quotas"] == {
        "max_wasm_fuel": 1000,
        "max_wasm_memory_bytes": 65536,
        "max_wall_time_ms": 50,
        "max_concurrent_calls": 2,
        "max_output_bytes": 128,
        "max_network_requests_per_minute": 3,
        "max_storage_bytes": 1024,
        "max_monthly_usd": 0.25,
    }


@pytest.mark.unit
def test_manifest_rejects_invalid_or_unknown_resource_quotas() -> None:
    with pytest.raises(PluginManifestError) as exc_info:
        parse_plugin_manifest(
            {
                "schemaVersion": 1,
                "id": "third-party-tool",
                "version": "1.0.0",
                "runtime": "wasm",
                "trust": "signed",
                "provides": [{"kind": "tool", "id": "demo"}],
                "activation": {
                    "quotas": {
                        "max_wasm_fuel": 0,
                        "max_monthly_usd": "0.25",
                        "unexpected": 1,
                    }
                },
            }
        )

    errors = exc_info.value.errors
    assert "activation.quotas.max_wasm_fuel must be an integer >= 1" in errors
    assert "activation.quotas.max_monthly_usd must be a number > 0" in errors
    assert "activation.quotas has unknown fields: unexpected" in errors


@pytest.mark.unit
def test_manifest_parses_signed_call_pricing_for_spend_quotas() -> None:
    manifest = parse_plugin_manifest(
        {
            "schemaVersion": 1,
            "id": "third-party-tool",
            "version": "1.0.0",
            "runtime": "mcp",
            "trust": "signed",
            "provides": [{"kind": "tool", "id": "echo"}],
            "activation": {"quotas": {"max_monthly_usd": 0.01}},
            "billing": {"usdMicrosPerCall": 1_000},
        }
    )

    assert manifest.to_payload()["billing"] == {"usd_micros_per_call": 1_000}


@pytest.mark.unit
def test_manifest_rejects_invalid_or_unknown_billing_fields() -> None:
    with pytest.raises(PluginManifestError) as exc_info:
        parse_plugin_manifest(
            {
                "schemaVersion": 1,
                "id": "third-party-tool",
                "version": "1.0.0",
                "runtime": "mcp",
                "trust": "signed",
                "provides": [{"kind": "tool", "id": "echo"}],
                "billing": {"usdMicrosPerCall": -1, "currency": "USD"},
            }
        )

    errors = exc_info.value.errors
    assert "billing.usdMicrosPerCall must be an integer >= 0" in errors
    assert "billing has unknown fields: currency" in errors


@pytest.mark.unit
def test_untrusted_plugin_cannot_claim_kernel_capability() -> None:
    with pytest.raises(PluginManifestError) as exc_info:
        parse_plugin_manifest(
            {
                "schemaVersion": 1,
                "id": "third-party-loop",
                "version": "0.1.0",
                "runtime": "wasm",
                "trust": "signed",
                "provides": [{"kind": "agent_loop", "id": "default"}],
            }
        )

    assert "agent_loop and credential_source capabilities must be builtin" in exc_info.value.errors
