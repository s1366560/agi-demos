#!/usr/bin/env bash
# Collect the plugins-g node ids before any test file runs.
# This step finishes and its artifact is uploaded before the per-file steps.
# A hang here is collection, not a later test file.
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"
list="$root/scripts/ci/plugins_g_files.txt"
mapfile -t expected < "$list"
# These cases run in individual steps as well as together to expose cross-file
# hangs. Other plugin shards exclude exactly this set from their test pool.
for file in "${expected[@]}"; do
  [[ -f "$file" ]] || { echo "plugins-g file missing: $file" >&2; exit 1; }
done
mkdir -p shard-logs
uv run pytest "${expected[@]}" \
  -m "not integration" \
  --collect-only -q \
  > shard-logs/plugins-g-nodes.txt
{
  echo "locale=$(locale | tr '\n' ' ')"
  cat shard-logs/plugins-g-nodes.txt
} > shard-logs/plugins-g-collected.txt
echo "plugins-g collected $(grep -c '::' shard-logs/plugins-g-nodes.txt || true) nodes"
