#!/usr/bin/env bash
# Collect the plugins-g node ids before any test file runs.
# This step finishes and its artifact is uploaded before the per-file steps.
# A hang here is collection, not a later test file.
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"
list="$root/scripts/ci/plugins_g_files.txt"
mapfile -t expected < "$list"
mapfile -t found < <(LC_ALL=C find src/tests/unit/infrastructure/plugins -name 'test_*.py' | LC_ALL=C sort)
mapfile -t runner_found < <(find src/tests/unit/infrastructure/plugins -name 'test_*.py' | sort)
shard=()
runner_shard=()
for i in "${!found[@]}"; do
  if (( i % 16 == 6 )); then
    shard+=("${found[$i]}")
    runner_shard+=("${runner_found[$i]}")
  fi
done
mkdir -p shard-logs
{
  echo "locale=$(locale | tr '\n' ' ')"
  if [[ "${shard[*]}" != "${runner_shard[*]}" ]]; then
    echo "runner sort does not match the C-locale plugins-g list"
    exit 1
  fi
} > shard-logs/plugins-g-collected.txt
if [[ "${#shard[@]}" -ne "${#expected[@]}" ]]; then
  echo "plugins-g file list has ${#expected[@]} entries; shard has ${#shard[@]}" >&2
  exit 1
fi
for i in "${!expected[@]}"; do
  if [[ "${expected[$i]}" != "${shard[$i]}" ]]; then
    echo "plugins-g file list drifted at ${expected[$i]} != ${shard[$i]}" >&2
    exit 1
  fi
done
uv run pytest "${expected[@]}" \
  -m "not integration" \
  --collect-only -q \
  > shard-logs/plugins-g-nodes.txt
{
  echo "locale=$(locale | tr '\n' ' ')"
  cat shard-logs/plugins-g-nodes.txt
} > shard-logs/plugins-g-collected.txt
echo "plugins-g collected $(grep -c '::' shard-logs/plugins-g-nodes.txt || true) nodes"
