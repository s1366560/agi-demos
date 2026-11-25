from dataclasses import asdict
from types import SimpleNamespace

import pytest

from src.host.operations import package_voice_lease as voice
from src.host.packages.release_pin import ACTIVE_APPLICATION_PIN, AgentPackagePin

pytestmark = pytest.mark.unit


def test_admission_requires_pinned_principal_scope_signature_and_private_signing_key(monkeypatch):
    settings = SimpleNamespace(secret_key="testing-only-private-auth-secret-32chars")
    monkeypatch.setattr(voice, "get_settings", lambda: settings)
    scope = {"tenant": "tenant", "project": "project", "conversation": "conversation"}
    pin = AgentPackagePin(
        tenant_id="tenant",
        project_id="project",
        plugin_id="plugin",
        version="1",
        digest="digest",
        authorization_epoch=10,
    )
    with pytest.raises(voice.OptionalBusinessError):
        voice.voice_ticket(principal="user", **scope)
    token = ACTIVE_APPLICATION_PIN.set(pin)
    try:
        ticket = voice.voice_ticket(principal="user", **scope)
    finally:
        ACTIVE_APPLICATION_PIN.reset(token)
    expected = {"user": "user", **scope}
    assert asdict(voice.PackageVoiceLease.admit(ticket, **expected)) == {
        **expected,
        "plugin": "plugin",
        "version": "1",
        "digest": "digest",
        "epoch": 10,
    }
    for key in expected:
        with pytest.raises(voice.VoiceGrantDenied):
            voice.PackageVoiceLease.admit(ticket, **{**expected, key: "different"})
    settings.secret_key = "a-different-testing-only-private-auth-secret"
    with pytest.raises(voice.VoiceGrantDenied):
        voice.PackageVoiceLease.admit(ticket, **expected)
    settings.secret_key = "dev-secret-key-change-in-production"
    with pytest.raises(voice.VoiceGrantDenied):
        voice.PackageVoiceLease.admit(ticket, **expected)
