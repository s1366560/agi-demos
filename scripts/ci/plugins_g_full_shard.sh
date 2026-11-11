#!/usr/bin/env bash
# Re-run the whole plugins-g shard in one pytest process after every file has
# passed alone. This keeps cross-file state visible. It does not write
# coverage-plugins-g, so the per-file coverage data stays intact.
set -euo pipefail

mapfile -t files < scripts/ci/plugins_g_files.txt
if [[ -f coverage-plugins-g ]]; then
  cp coverage-plugins-g shard-logs/coverage-plugins-g.before-full-shard
fi
uv run pytest "${files[@]}" \
  -m "not integration" \
  --timeout=120 \
  --timeout-method=signal \
  --durations=20
if [[ -f shard-logs/coverage-plugins-g.before-full-shard ]]; then
  if ! cmp -s coverage-plugins-g shard-logs/coverage-plugins-g.before-full-shard; then
    echo "full shard changed coverage-plugins-g" >&2
    exit 1
  fi
fi
