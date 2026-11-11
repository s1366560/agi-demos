#!/usr/bin/env bash
# The workflow steps name every plugins-g file, and desktop tests do not
# start a release compile in the same step.
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"
fail() { echo "FAIL: $*" >&2; exit 1; }

mapfile -t expected < scripts/ci/plugins_g_files.txt
mapfile -t found < <(LC_ALL=C find src/tests/unit/infrastructure/plugins -name 'test_*.py' | LC_ALL=C sort)
shard=()
for i in "${!found[@]}"; do
  if (( i % 16 == 6 )); then shard+=("${found[$i]}"); fi
done
[[ "${#shard[@]}" -eq "${#expected[@]}" ]] || fail "list length"
for i in "${!expected[@]}"; do
  [[ "${expected[$i]}" == "${shard[$i]}" ]] || fail "list drift ${expected[$i]}"
done

workflow="$(cat .github/workflows/ci.yml)"
for file in "${expected[@]}"; do
  count="$(grep -c "plugins_g_file_step.sh ${file}$" .github/workflows/ci.yml || true)"
  [[ "$count" -eq 1 ]] || fail "workflow steps for ${file}: ${count}"
done
if grep -n "cargo build --release" .github/workflows/ci.yml | grep -n "Run desktop unit" >/dev/null; then
  fail "release compile is still attached to the desktop test heading"
fi
python3 - << 'PY'
from pathlib import Path
text = Path(".github/workflows/ci.yml").read_text()
start = text.index("      - name: Run desktop unit and integration tests\n")
end = text.index("      - name: Build desktop bundle\n", start)
block = text[start:end]
if "cargo build --release" in block or "cargo.sh build --release" in block:
    raise SystemExit("desktop test step still starts a release compile")
print("desktop test step has no release compile")
PY
echo "plugins-g file plan matches the shard"
