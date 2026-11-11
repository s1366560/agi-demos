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
mkdir -p shard-logs
log="shard-logs/ordered-group-${start}-${count}.log"
printf 'plugins-g ordered group start=%s count=%s first=%s\n' "$start" "${#slice[@]}" "${slice[0]}"
# Pytest output stays in the log file. A verbose node id for the oversized
# artifact body is several megabytes, and that line stalled the runner log
# pipe so the step timeout never got to reap the process.
set +e
PYTHONUNBUFFERED=1 \
  uv run pytest "${slice[@]}" \
    -m "not integration" \
    --timeout=120 \
    --timeout-method=signal \
    --durations=20 \
    >"$log" 2>&1
status=$?
set -e
echo "plugins-g ordered group start=${start} status=${status}"
tail -n 40 "$log" | cut -c -400
exit "$status"
