import pytest

from src.domain.model.plugins import parse_plugin_manifest
from src.infrastructure.plugins import compose_profile, parse_profile_document
from src.infrastructure.plugins.profile import control_envelope, load_profile_document


def _manifest(plugin_id: str, requires=None):
    return parse_plugin_manifest(
        {
            "schemaVersion": 1,
            "id": plugin_id,
            "version": "1.0.0",
            "runtime": "python-trusted",
            "trust": "builtin",
            "requires": requires or [],
            "provides": [{"kind": "tool", "id": f"{plugin_id}-tool"}],
        }
    )


@pytest.mark.unit
def test_default_profile_file_composes_builtin_manifests():
    from src.infrastructure.plugins.builtin_manifests import default_builtin_manifests

    document = load_profile_document("config/plugin-profiles/memstack-default.yaml")
    snapshot = compose_profile(document, default_builtin_manifests())

    assert snapshot.profile_id == "memstack-default"
    assert [row.manifest.id for row in snapshot.rows] == [
        "sisyphus-runtime",
        "workspace-runtime",
    ]
    assert len(snapshot.digest) == 64
    assert snapshot.to_payload()["plugins"][0]["config"] == {}


@pytest.mark.unit
def test_patch_replaces_whole_config_and_last_write_wins():
    document = parse_profile_document(
        {
            "profile": {
                "id": "test-profile",
                "layers": [
                    {
                        "id": "base",
                        "plugins": [
                            {"id": "plugin-a", "config": {"old": True}},
                            {"id": "plugin-b", "enabled": False},
                        ],
                    }
                ],
            },
            "patches": [
                {"target": "plugin-a", "config": {"new": "value"}},
                {"target": "plugin-b", "enabled": True},
            ],
        }
    )
    snapshot = compose_profile(
        document,
        {"plugin-a": _manifest("plugin-a"), "plugin-b": _manifest("plugin-b")},
    )

    assert snapshot.rows[0].config == {"new": "value"}
    assert "old" not in snapshot.rows[0].config
    assert [row.manifest.id for row in snapshot.rows] == ["plugin-a", "plugin-b"]


@pytest.mark.unit
def test_missing_requirement_fails_loud():
    document = parse_profile_document(
        {
            "profile": {
                "id": "bad-profile",
                "layers": [{"id": "base", "plugins": [{"id": "consumer"}]}],
            }
        }
    )

    with pytest.raises(ValueError, match="requires missing capability tool:missing-tool"):
        compose_profile(
            document,
            {
                "consumer": _manifest(
                    "consumer",
                    [{"capability": "tool:missing-tool", "minVersion": "1.0.0"}],
                )
            },
        )


@pytest.mark.unit
def test_patch_to_absent_row_fails_loud():
    document = parse_profile_document(
        {
            "profile": {"id": "bad-profile", "layers": [{"id": "base", "plugins": []}]},
            "patches": [{"target": "absent", "enabled": False}],
        }
    )

    with pytest.raises(ValueError, match="patch target is absent"):
        compose_profile(document, {})


@pytest.mark.unit
def test_control_envelope_is_versioned_and_deterministic_when_nonce_given():
    document = parse_profile_document(
        {
            "profile": {
                "id": "test-profile",
                "layers": [{"id": "base", "plugins": [{"id": "plugin-a"}]}],
            }
        }
    )
    snapshot = compose_profile(document, {"plugin-a": _manifest("plugin-a")})
    envelope = control_envelope(snapshot, version=7, nonce="nonce-7")

    assert envelope.to_payload() == {
        "version": 7,
        "nonce": "nonce-7",
        "snapshot_digest": snapshot.digest,
        "type_url": "types.memstack.ai/plugin.profile.v1",
    }
