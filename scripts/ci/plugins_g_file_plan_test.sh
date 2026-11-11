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

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/work"
cat > "$tmp/bin/uv" << 'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "${UV_LOG:?}"
if [[ -n "${UV_EXIT:-}" ]]; then
  exit "$UV_EXIT"
fi
printf x >> "${COVERAGE_FILE:?}"
exit 0
EOF
chmod +x "$tmp/bin/uv"
(
  cd "$tmp/work"
  export PATH="$tmp/bin:$PATH"
  export UV_LOG="$tmp/uv.log"
  touch present.py
  if bash "$root/scripts/ci/plugins_g_file_step.sh" absent.py; then
    echo "missing file was accepted" >&2
    exit 1
  fi
  grep -q 'status=missing' shard-logs/absent.status
  if [[ -s "$UV_LOG" ]]; then
    echo "missing file invoked pytest" >&2
    exit 1
  fi
  set +e
  UV_EXIT=5 bash "$root/scripts/ci/plugins_g_file_step.sh" present.py
  status=$?
  set -e
  [[ "$status" -eq 5 ]]
  grep -q 'status=5' shard-logs/present.status
  unset UV_EXIT
  : > "$UV_LOG"
  bash "$root/scripts/ci/plugins_g_file_step.sh" present.py
  bash "$root/scripts/ci/plugins_g_file_step.sh" present.py
  [[ "$(wc -c < coverage-plugins-g)" -eq 2 ]]
  grep -c -- '--cov-append' "$UV_LOG" | grep -q '^1$'
)
echo "wrapper failure, missing file, and coverage append checked"
