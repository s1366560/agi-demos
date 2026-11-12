#!/usr/bin/env bash
# Foreground watchdog for the plugins-g pytest command.
#
# The command is not exec'd: this shell has to stay alive to enforce the
# deadline. The command's stdout and stderr go to the log file, not to the
# step pipe. Heartbeats go to the state file. A full step pipe therefore
# cannot block the deadline check. set -e is disabled around wait so a
# nonzero pytest status is recorded instead of skipping the cleanup.
set -euo pipefail

log=""
deadline="960"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --log)
      log="${2:?}"
      shift 2
      ;;
    --deadline)
      deadline="${2:?}"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

if [[ -z "$log" || $# -eq 0 ]]; then
  echo "usage: plugins_g_shard_watch.sh --log PATH --deadline SECONDS -- COMMAND" >&2
  exit 2
fi

mkdir -p "$(dirname "$log")"
state="${log}.state"
tree=()

collect_descendants() {
  local pid="$1"
  local child
  local -a children=()
  mapfile -t children < <(ps -o pid= --ppid "$pid" 2>/dev/null | awk '{$1=$1; print}')
  for child in "${children[@]}"; do
    [[ -n "$child" ]] || continue
    collect_descendants "$child"
    echo "$child"
  done
}

"$@" >"$log" 2>&1 &
child=$!
printf 'start %s pid=%s\n' "$(date -u +%H:%M:%S)" "$child" >>"$state"
ps -o pid,ppid,stat,cmd -p "$child" >>"$state" 2>/dev/null || true
echo "::notice title=plugins-g-pytest-pid::pid=${child} shell=$$"

deadline_at=$((SECONDS + deadline))
tick=0
while kill -0 "$child" 2>/dev/null; do
  if (( SECONDS >= deadline_at )); then
    mapfile -t tree < <(collect_descendants "$child")
    printf 'deadline %s TERM %s %s\n' "$(date -u +%H:%M:%S)" "$child" "${tree[*]-}" >>"$state"
    kill -TERM "$child" 2>/dev/null || true
    if [[ ${#tree[@]} -gt 0 ]]; then
      kill -TERM "${tree[@]}" 2>/dev/null || true
    fi
    sleep 2
    mapfile -t tree < <(collect_descendants "$child")
    printf 'deadline %s KILL %s %s\n' "$(date -u +%H:%M:%S)" "$child" "${tree[*]-}" >>"$state"
    kill -KILL "$child" 2>/dev/null || true
    if [[ ${#tree[@]} -gt 0 ]]; then
      kill -KILL "${tree[@]}" 2>/dev/null || true
    fi
    break
  fi
  sleep 1
  tick=$((tick + 1))
  if (( tick % 15 == 0 )); then
    if [[ -s "$log" ]]; then
      printf 'heartbeat %s %s\n' "$(date -u +%H:%M:%S)" "$(head -n 1 "$log")" >>"$state"
    else
      printf 'heartbeat %s log=empty\n' "$(date -u +%H:%M:%S)" >>"$state"
    fi
  fi
done

set +e
status=124
for _ in 1 2 3 4 5; do
  if ! kill -0 "$child" 2>/dev/null; then
    wait "$child"
    status=$?
    break
  fi
  child_state="$(ps -o stat= -p "$child" 2>/dev/null | awk 'NR==1 { print $1 }')"
  if [[ "$child_state" == Z* ]]; then
    wait "$child"
    status=$?
    break
  fi
  sleep 0.2
done
if [[ "$status" -eq 124 ]]; then
  printf 'still-alive %s\n' "$child" >>"$state"
fi
set -e
printf 'exit %s status=%s\n' "$(date -u +%H:%M:%S)" "$status" >>"$state"
echo "::notice title=plugins-g-pytest-exit::status=${status}"
exit "$status"
