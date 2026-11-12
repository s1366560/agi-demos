#!/usr/bin/env bash
# Local proof for the plugins-g boundary: the prelude exists before the
# command starts, a full step pipe can block a heartbeat, and the watchdog
# still exits when the child ignores SIGTERM and floods its own stdout.
set -euo pipefail

root="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$root"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# A write to a full pipe blocks. The watchdog must not use that path.
python3 - <<'PY'
import os
import subprocess

read_fd, write_fd = os.pipe()
os.set_blocking(write_fd, False)
while True:
    try:
        os.write(write_fd, b"x" * 65536)
    except BlockingIOError:
        break
os.set_blocking(write_fd, True)
proc = subprocess.Popen(
    ["bash", "-c", f"echo blocked >&{write_fd}"],
    pass_fds=(write_fd,),
)
try:
    proc.wait(timeout=1)
except subprocess.TimeoutExpired:
    proc.kill()
    proc.wait()
else:
    raise SystemExit("echo on a full pipe returned; the block was not reproduced")
print("full-pipe echo blocks")
PY

# exec replaces the shell, so a deadline after exec never runs.
if bash -c 'exec true; echo after-exec' | grep -q after-exec; then
  fail "exec did not replace the shell"
fi
if grep -nE '^[[:space:]]*exec[[:space:]]' scripts/ci/plugins_g_shard_watch.sh; then
  fail "watch script execs the pytest command"
fi
echo "exec would skip the deadline"

DATABASE_URL='postgresql://postgres:secret-password@localhost/memstack' \
  API_KEY='ms_sk_secret' \
  bash scripts/ci/plugins_g_shard_prelude.sh "$work/summary.txt" >/dev/null
cp "$work/summary.txt" "$work/uploaded-summary.txt"
grep -q '^plugins_g_shard_files=19$' "$work/uploaded-summary.txt" || fail "shard file count"
grep -q 'exec_replaces_watchdog=no' "$work/uploaded-summary.txt" || fail "exec marker"
if grep -E 'secret-password|ms_sk_secret|DATABASE_URL=' "$work/uploaded-summary.txt"; then
  fail "prelude leaked the environment"
fi
echo "prelude uploaded before the command"

start=$(date +%s)
set +e
bash scripts/ci/plugins_g_shard_watch.sh \
  --log "$work/flood.log" \
  --deadline 2 \
  -- \
  python3 -c 'import os,signal,sys,time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
if os.fork()==0:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    time.sleep(30)
    os._exit(0)
sys.stdout.write("plugins-g-boundary-sleeper\n"+"x"*1048576)
sys.stdout.flush()
time.sleep(30)' \
  >"$work/watch.out" 2>"$work/watch.err"
watch_status=$?
set -e
elapsed=$(( $(date +%s) - start ))
[[ "$watch_status" -eq 137 ]] || fail "expected SIGKILL status 137, got ${watch_status}"
[[ "$elapsed" -lt 12 ]] || fail "watchdog blocked for ${elapsed}s"
if ps -eo args | grep -F 'plugins-g-boundary-sleeper' | grep -v grep >/dev/null; then
  fail "sleeper survived the watchdog"
fi
[[ -s "$work/flood.log" ]] || fail "child stdout did not reach the log file"
grep -q 'status=137' "$work/flood.log.state" || fail "state file missing the exit status"
grep -q 'plugins-g-pytest-pid' "$work/watch.out" || fail "pid notice missing"
echo "flood child killed without blocking on its output"

set +e
bash scripts/ci/plugins_g_shard_watch.sh \
  --log "$work/fail.log" \
  --deadline 30 \
  -- \
  bash -c 'echo pytest-started; exit 3' \
  >"$work/fail.out" 2>"$work/fail.err"
fail_status=$?
set -e
[[ "$fail_status" -eq 3 ]] || fail "nonzero child status was swallowed: ${fail_status}"
grep -q 'status=3' "$work/fail.log.state" || fail "cleanup did not record status 3"
grep -q 'pytest-started' "$work/fail.log" || fail "child stdout missing from the log"
echo "set -e preserved the child status"

bash scripts/ci/plugins_g_shard_watch.sh \
  --log "$work/ok.log" \
  --deadline 30 \
  -- \
  bash -c 'echo ok' \
  >"$work/ok.out"
grep -q 'status=0' "$work/ok.log.state" || fail "success status missing"
echo "successful command still returns 0"

start=$(date +%s)
set +e
bash scripts/ci/plugins_g_shard_watch.sh \
  --log "$work/load.log" \
  --deadline 2 \
  -- \
  python3 -c 'import os,signal,sys,time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
for _ in range(8):
    if os.fork()==0:
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        sys.stdout.write("x"*262144)
        sys.stdout.flush()
        time.sleep(30)
        os._exit(0)
time.sleep(30)' \
  >"$work/load.out" 2>"$work/load.err"
load_status=$?
set -e
load_elapsed=$(( $(date +%s) - start ))
[[ "$load_status" -eq 137 ]] || fail "load status ${load_status}"
[[ "$load_elapsed" -lt 12 ]] || fail "load watchdog blocked for ${load_elapsed}s"
if ps -eo args | grep -F 'range(8)' | grep -v grep >/dev/null; then
  fail "load sleepers survived"
fi
echo "eight ignoring children killed under output load"
echo "plugins-g boundary tests passed"
