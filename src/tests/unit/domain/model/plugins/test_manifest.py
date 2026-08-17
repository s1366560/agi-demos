import pytest

from src.domain.model.plugins import PluginManifestError, parse_plugin_manifest


@pytest.mark.unit
def test_parse_manifest_returns_immutable_capability_contract():
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
def test_parse_manifest_collects_all_validation_errors():
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
def test_untrusted_plugin_cannot_claim_kernel_capability():
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
