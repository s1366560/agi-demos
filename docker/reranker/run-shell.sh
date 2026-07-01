#!/usr/bin/env sh
set -eu

exec uv run \
  --with torch \
  --with transformers==4.57.3 \
  --with fastapi \
  --with 'uvicorn[standard]' \
  -- python -u docker/reranker/app.py
