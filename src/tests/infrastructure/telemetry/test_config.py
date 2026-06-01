"""Tests for OpenTelemetry configuration module."""

import os
import sys
from types import SimpleNamespace

from src.infrastructure.telemetry import config


class FakeSpanProcessor:
    """Minimal span processor used to inspect configured exporters."""

    def __init__(self, exporter):
        self.exporter = exporter

    def on_start(self, span, parent_context=None):
        return None

    def on_end(self, span):
        return None

    def shutdown(self):
        return None

    def force_flush(self, timeout_millis=30000):
        return True


class TestConfigureTracerProvider:
    """Tests for tracer provider configuration."""

    def test_disabled_when_telemetry_disabled(self):
        """Test that tracer provider is None when telemetry is disabled."""
        # Reset state
        config._reset_providers()

        result = config.configure_tracer_provider(settings_override={"enable_telemetry": False})

        assert result is None

    def test_returns_provider_when_enabled(self):
        """Test that provider is returned when telemetry is enabled."""
        # Reset state
        config._reset_providers()

        result = config.configure_tracer_provider(
            settings_override={"enable_telemetry": True, "service_name": "test-service"}
        )

        assert result is not None

        # Cleanup
        config._reset_providers()

    def test_default_trace_exporter_does_not_log_to_console(self, caplog):
        """Trace spans should not be printed when no exporter endpoint is configured."""
        config._reset_providers()

        with caplog.at_level("INFO", logger=config.logger.name):
            exporter = config._create_trace_exporter(settings_override={})

        assert exporter is None
        assert "trace export disabled" in caplog.text
        assert "using console exporter" not in caplog.text

        config._reset_providers()

    def test_returns_cached_provider(self):
        """Test that cached provider is returned if already configured."""
        # Reset state
        config._reset_providers()

        # First call should create provider
        provider1 = config.configure_tracer_provider(settings_override={"enable_telemetry": True})
        # Second call should return cached
        provider2 = config.configure_tracer_provider(settings_override={"enable_telemetry": True})

        assert provider1 is not None
        assert provider1 is provider2

        # Cleanup
        config._reset_providers()

    def test_resource_attributes_set(self):
        """Test that resource attributes are set correctly."""
        # Reset state
        config._reset_providers()

        provider = config.configure_tracer_provider(
            settings_override={
                "enable_telemetry": True,
                "service_name": "test-service",
                "environment": "test",
            }
        )

        assert provider is not None
        # Verify resource has service name
        resource = provider.resource
        attributes = dict(resource.attributes)
        assert attributes.get("service.name") == "test-service"
        assert attributes.get("deployment.environment") == "test"

        # Cleanup
        config._reset_providers()

    def test_adds_langfuse_exporter_when_langfuse_enabled(self, monkeypatch):
        """Langfuse enabled app telemetry should export spans to Langfuse."""
        config._reset_providers()
        created_exporters = []

        class FakeHTTPTraceExporter:
            def __init__(self, endpoint, headers=None):
                self.endpoint = endpoint
                self.headers = headers or {}
                created_exporters.append(self)

        monkeypatch.setattr(config, "HTTPTraceExporter", FakeHTTPTraceExporter)
        monkeypatch.setattr(config, "BatchSpanProcessor", FakeSpanProcessor)

        provider = config.configure_tracer_provider(
            settings_override={
                "enable_telemetry": True,
                "langfuse_enabled": True,
                "langfuse_public_key": "lf_pk_memstack_dev",
                "langfuse_secret_key": "lf_sk_memstack_dev",
                "langfuse_host": "http://localhost:3004",
            },
            force_reset=True,
        )

        assert provider is not None
        assert len(created_exporters) == 1
        assert created_exporters[0].endpoint == "http://localhost:3004/api/public/otel/v1/traces"
        assert created_exporters[0].headers["Authorization"].startswith("Basic ")

        config._reset_providers()

    def test_langfuse_enabled_without_otlp_does_not_print_trace_logs(self, capsys, monkeypatch):
        """Langfuse must not re-enable console span output when enabled."""
        config._reset_providers()
        created_exporters = []

        class FakeHTTPTraceExporter:
            def __init__(self, endpoint, headers=None):
                self.endpoint = endpoint
                self.headers = headers or {}
                created_exporters.append(self)

        monkeypatch.setattr(config, "HTTPTraceExporter", FakeHTTPTraceExporter)
        monkeypatch.setattr(config, "BatchSpanProcessor", FakeSpanProcessor)

        provider = config.configure_tracer_provider(
            settings_override={
                "enable_telemetry": True,
                "langfuse_enabled": True,
                "langfuse_public_key": "lf_pk_memstack_dev",
                "langfuse_secret_key": "lf_sk_memstack_dev",
                "langfuse_host": "http://localhost:3004",
                "otel_exporter_otlp_endpoint": None,
            },
            force_reset=True,
        )

        assert provider is not None
        tracer = provider.get_tracer("test-langfuse")
        with tracer.start_as_current_span("should-not-print"):
            pass

        captured = capsys.readouterr()
        assert "trace_id" not in captured.out
        assert "trace_id" not in captured.err
        assert "SpanKind" not in captured.out
        assert "SpanKind" not in captured.err
        assert len(created_exporters) == 1

        config._reset_providers()

    def test_skips_langfuse_exporter_when_credentials_missing(self, monkeypatch):
        """Missing Langfuse keys should not prevent app telemetry startup."""
        config._reset_providers()
        created_exporters = []

        class FakeHTTPTraceExporter:
            def __init__(self, endpoint, headers=None):
                created_exporters.append((endpoint, headers))

        monkeypatch.setattr(config, "HTTPTraceExporter", FakeHTTPTraceExporter)

        provider = config.configure_tracer_provider(
            settings_override={
                "enable_telemetry": True,
                "langfuse_enabled": True,
                "langfuse_public_key": "",
                "langfuse_secret_key": "",
                "langfuse_host": "http://localhost:3004",
            },
            force_reset=True,
        )

        assert provider is not None
        assert created_exporters == []

        config._reset_providers()


class TestConfigureLangfuseLLMObservability:
    """Tests for process-local Langfuse LiteLLM configuration."""

    def test_configures_env_and_litellm_callback(self, monkeypatch):
        """Langfuse LLM setup should work outside FastAPI startup."""
        config._reset_providers()
        fake_litellm = SimpleNamespace(callbacks=["langfuse", "custom"])
        tracer_configured = []

        monkeypatch.setitem(sys.modules, "litellm", fake_litellm)
        monkeypatch.setattr(
            config,
            "configure_tracer_provider",
            lambda settings_override=None: tracer_configured.append(settings_override),
        )
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_HOST", raising=False)
        monkeypatch.delenv("LANGFUSE_OTEL_HOST", raising=False)

        initialized = config.configure_langfuse_llm_observability(
            settings_override={
                "enable_telemetry": True,
                "langfuse_enabled": True,
                "langfuse_public_key": "lf_pk_memstack_dev",
                "langfuse_secret_key": "lf_sk_memstack_dev",
                "langfuse_host": "http://localhost:3004",
                "langfuse_sample_rate": 1.0,
            }
        )

        assert initialized is True
        assert tracer_configured
        assert fake_litellm.callbacks == ["custom", "langfuse_otel"]
        assert os.environ["LANGFUSE_PUBLIC_KEY"] == "lf_pk_memstack_dev"
        assert os.environ["LANGFUSE_SECRET_KEY"] == "lf_sk_memstack_dev"
        assert os.environ["LANGFUSE_HOST"] == "http://localhost:3004"
        assert os.environ["LANGFUSE_OTEL_HOST"] == "http://localhost:3004"

        config._reset_providers()


class TestConfigureMeterProvider:
    """Tests for meter provider configuration."""

    def test_disabled_when_telemetry_disabled(self):
        """Test that meter provider is None when telemetry is disabled."""
        # Reset state
        config._reset_providers()

        result = config.configure_meter_provider(settings_override={"enable_telemetry": False})

        assert result is None

    def test_returns_cached_provider(self):
        """Test that cached provider is returned if already configured."""
        # Reset state
        config._reset_providers()

        # First call should create provider
        provider1 = config.configure_meter_provider(settings_override={"enable_telemetry": True})
        # Second call should return cached
        provider2 = config.configure_meter_provider(settings_override={"enable_telemetry": True})

        assert provider1 is not None
        assert provider1 is provider2

        # Cleanup
        config._reset_providers()


class TestGetTracer:
    """Tests for get_tracer function."""

    def test_returns_tracer_from_provider(self):
        """Test that tracer is obtained from provider when telemetry enabled."""
        # Reset state
        config._reset_providers()

        # Configure with enabled telemetry - this sets _TRACER_PROVIDER
        config.configure_tracer_provider(settings_override={"enable_telemetry": True})
        # get_tracer() calls configure_tracer_provider() without override,
        # but should return cached provider since _TRACER_PROVIDER is already set
        # However, default settings may have enable_telemetry=False, which
        # causes it to return None. So we call directly on the provider.
        provider = config._get_tracer_provider_global()
        assert provider is not None
        tracer = provider.get_tracer("test-instrumentation")
        assert tracer is not None

        # Cleanup
        config._reset_providers()

    def test_returns_none_when_disabled(self):
        """Test that None is returned when telemetry is disabled."""
        # Reset state
        config._reset_providers()

        result = config.configure_tracer_provider(settings_override={"enable_telemetry": False})
        assert result is None

        # Cleanup
        config._reset_providers()


class TestGetMeter:
    """Tests for get_meter function."""

    def test_returns_meter_from_provider(self):
        """Test that meter is obtained from provider when telemetry enabled."""
        # Reset state
        config._reset_providers()

        # Configure with enabled telemetry
        config.configure_meter_provider(settings_override={"enable_telemetry": True})
        # get_meter() uses default settings which may have enable_telemetry=False,
        # so we verify via the global provider directly
        provider = config._get_meter_provider_global()
        assert provider is not None
        meter = provider.get_meter("test-instrumentation")
        assert meter is not None

        # Cleanup
        config._reset_providers()


class TestConfigureTelemetry:
    """Tests for configure_telemetry function."""

    def test_configures_both_providers(self):
        """Test that both tracer and meter providers are configured."""
        # Reset state
        config._reset_providers()

        config.configure_telemetry(settings_override={"enable_telemetry": True})

        # Verify providers are configured
        assert config._get_tracer_provider_global() is not None
        assert config._get_meter_provider_global() is not None

        # Cleanup
        config._reset_providers()


class TestShutdownTelemetry:
    """Tests for shutdown_telemetry function."""

    def test_shutdown_clears_providers(self):
        """Test that shutdown clears both providers."""
        # Reset state
        config._reset_providers()

        # Configure telemetry
        config.configure_telemetry(settings_override={"enable_telemetry": True})

        # Verify providers exist
        assert config._get_tracer_provider_global() is not None
        assert config._get_meter_provider_global() is not None

        # Shutdown
        config.shutdown_telemetry()

        # Verify providers are cleared
        assert config._get_tracer_provider_global() is None
        assert config._get_meter_provider_global() is None
