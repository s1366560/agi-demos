"""Unit tests for channel service factory logging."""

from types import SimpleNamespace

import pytest

from src.application.services.channels import channel_service_factory as factory


class _ScalarResult:
    def __init__(self, value: object) -> None:
        self._value = value

    def scalar_one_or_none(self) -> object:
        return self._value


class _DbSession:
    def __init__(self, value: object) -> None:
        self._value = value

    async def execute(self, _query: object) -> _ScalarResult:
        return _ScalarResult(self._value)


@pytest.mark.unit
def test_create_media_import_service_log_does_not_disclose_exception_secret(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_load_channel_module(_channel: str, _module: str) -> object:
        raise ValueError("secret-app-credential")

    monkeypatch.setattr(factory, "load_channel_module", fail_load_channel_module)

    with caplog.at_level("ERROR", logger="src.application.services.channels.channel_service_factory"):
        result = factory.create_media_import_service(
            db_session=SimpleNamespace(),
            app_id="app-id",
            app_secret="app-secret",
        )

    assert result is None
    assert "secret-app-credential" not in caplog.text
    assert "app-secret" not in caplog.text


@pytest.mark.unit
async def test_create_media_import_service_from_config_decrypt_log_omits_secret(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = SimpleNamespace(
        id="channel-1",
        app_id="app-id",
        app_secret="encrypted-secret-value",
        project_id="project-1",
        domain="feishu",
        extra_settings={},
    )

    class _EncryptionService:
        def decrypt(self, _value: str) -> str:
            raise ValueError("decryption failed for plaintext-secret")

    monkeypatch.setattr(
        "src.infrastructure.security.encryption_service.get_encryption_service",
        lambda: _EncryptionService(),
    )
    monkeypatch.setattr(factory, "create_media_import_service", lambda **_kwargs: None)

    with caplog.at_level("WARNING", logger="src.application.services.channels.channel_service_factory"):
        result = await factory.create_media_import_service_from_config(
            _DbSession(config),
            channel_config_id="channel-1",
        )

    assert result is None
    assert "plaintext-secret" not in caplog.text
    assert "encrypted-secret-value" not in caplog.text
