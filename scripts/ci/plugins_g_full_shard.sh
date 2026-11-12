#!/usr/bin/env bash
# Re-run the whole plugins-g shard in one pytest process after every file has
# passed alone. This keeps cross-file state visible. It does not write
# coverage-plugins-g, so the per-file coverage data stays intact.
set -euo pipefail

mapfile -t files < scripts/ci/plugins_g_files.txt
mkdir -p shard-logs
if [[ -f coverage-plugins-g ]]; then
  cp coverage-plugins-g shard-logs/coverage-plugins-g.before-full-shard
fi
# The rerun writes its own log. Streaming pytest -v to the step pipe prints
# the multi-megabyte artifact node id and the runner stops reading, so neither
# the pytest timeout nor the step timeout can finish the step.
log="shard-logs/full-shard.log"
set +e
PYTHONUNBUFFERED=1 \
  uv run pytest "${files[@]}" \
    -m "not integration" \
    --timeout=120 \
    --timeout-method=thread \
    --durations=20 \
    >"$log" 2>&1
status=$?
set -e
echo "plugins-g full shard status=${status}"
tail -n 40 "$log" | cut -c -400
if [[ "$status" -ne 0 ]]; then
  exit "$status"
fi
if [[ -f shard-logs/coverage-plugins-g.before-full-shard ]]; then
  if ! cmp -s coverage-plugins-g shard-logs/coverage-plugins-g.before-full-shard; then
    echo "full shard changed coverage-plugins-g" >&2
    exit 1
  fi
fi
