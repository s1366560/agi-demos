#!/usr/bin/env bash
# Record the plugins-g shard boundary before pytest starts.
# The workflow uploads this file in the preceding step, so a later hung
# pytest step is not required for the evidence to exist.
set -euo pipefail

output="${1:?prelude output path}"
mkdir -p "$(dirname "$output")"

mapfile -t files < <(find src/tests/unit/infrastructure/plugins -name 'test_*.py' | sort)
shard_count=0
for i in "${!files[@]}"; do
  if (( i % 16 == 6 )); then
    shard_count=$((shard_count + 1))
  fi
done

{
  echo "sha=$(git rev-parse HEAD)"
  echo "workflow_sha256=$(sha256sum .github/workflows/ci.yml | awk '{print $1}')"
  echo "date=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "runner=${RUNNER_NAME:-unknown} os=${RUNNER_OS:-unknown} arch=${RUNNER_ARCH:-unknown}"
  echo "nproc=$(nproc)"
  echo "plugins_g_shard_files=${shard_count}"
  echo "watch_script=scripts/ci/plugins_g_shard_watch.sh"
  echo "pytest_stdout=log_file"
  echo "watchdog_heartbeat=state_file"
  echo "exec_replaces_watchdog=no"
  df -h .
} > "$output"

if grep -E 'DATABASE_URL=|password=|token=|ms_sk_|Bearer |SECRET|API_KEY=' "$output" >/dev/null; then
  echo "plugins-g prelude contained a credential-shaped line" >&2
  exit 1
fi

echo "::notice title=plugins-g-boundary::files=${shard_count} sha=$(git rev-parse --short HEAD)"
