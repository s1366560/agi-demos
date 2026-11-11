#!/usr/bin/env bash
# Run one contiguous slice of the plugins-g shard in a single pytest process.
# The full 19-file shard still runs afterward. These slices only name which
# part of that order hangs, and they do not write coverage-plugins-g.
set -euo pipefail

start="${1:?start index}"
count="${2:?file count}"
mapfile -t files < scripts/ci/plugins_g_files.txt
slice=("${files[@]:start:count}")
if [[ ${#slice[@]} -eq 0 ]]; then
  echo "plugins-g ordered group ${start}+${count} is empty" >&2
  exit 1
fi
printf 'plugins-g ordered group start=%s count=%s first=%s\n' "$start" "${#slice[@]}" "${slice[0]}"
uv run pytest "${slice[@]}" \
  -m "not integration" \
  --timeout=120 \
  --timeout-method=signal \
  --durations=20
