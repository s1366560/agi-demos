#!/usr/bin/env bash
# Run one plugins-g file in the foreground. Pytest output stays in the log
# file that the following upload step publishes. There is no heartbeat.
set -euo pipefail

file="${1:?plugins-g test file}"
base="$(basename "$file" .py)"
mkdir -p shard-logs
log="shard-logs/${base}.log"
append=()
if [[ -f coverage-plugins-g ]]; then
  append=(--cov-append)
fi
set +e
COVERAGE_FILE="coverage-plugins-g" \
  PYTHONFAULTHANDLER=1 \
  PYTHONUNBUFFERED=1 \
  uv run pytest "$file" \
    -m "not integration" \
    --timeout=120 \
    --timeout-method=signal \
    --durations=20 \
    --cov=src \
    --cov-report= \
    --cov-fail-under=0 \
    "${append[@]}" \
    >"$log" 2>&1
status=$?
set -e
printf 'file=%s status=%s\n' "$file" "$status" > "shard-logs/${base}.status"
echo "plugins-g ${base} status=${status}"
exit "$status"
