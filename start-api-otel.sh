#!/bin/bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
export ENABLE_TELEMETRY=true
export SERVICE_NAME=memstack
export ENVIRONMENT=development

cd /Users/tiejun.sun/Documents/github/vip-memory
uv run uvicorn src.infrastructure.adapters.primary.web.main:app --host 0.0.0.0 --port 8000
