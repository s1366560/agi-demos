#!/usr/bin/env bash
# Re-run the whole plugins-g shard in one pytest process after every file has
# passed alone. This keeps cross-file state visible. It does not write
# coverage-plugins-g, so the per-file coverage data stays intact.
set -euo pipefail

mapfile -t files < scripts/ci/plugins_g_files.txt
if [[ -f coverage-plugins-g ]]; then
  cp coverage-plugins-g shard-logs/coverage-plugins-g.before-full-shard
fi
# Job 130518613039: every file passed, then this one-process rerun stayed
# in progress for 29 minutes and the step log was never uploaded. The signal
# timeout did not end that process. The thread timeout still fails the stuck
# test at 120s and prints its stack, so the step can finish and the log exists.
uv run pytest "${files[@]}" \
  -m "not integration" \
  --timeout=120 \
  --timeout-method=thread \
  --durations=20
if [[ -f shard-logs/coverage-plugins-g.before-full-shard ]]; then
  if ! cmp -s coverage-plugins-g shard-logs/coverage-plugins-g.before-full-shard; then
    echo "full shard changed coverage-plugins-g" >&2
    exit 1
  fi
fi
