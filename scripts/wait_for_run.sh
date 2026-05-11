#!/usr/bin/env bash
# Poll a Databricks job until its latest run terminates. Usage: wait_for_run.sh <job_id> [minutes]
set -u
job_id="$1"
minutes="${2:-90}"
for _ in $(seq 1 "$minutes"); do
  state=$(databricks jobs list-runs --job-id "$job_id" --limit 1 --output json 2>/dev/null \
    | python3 -c 'import json,sys; r=json.load(sys.stdin)[0]; s=r["state"]; print(s.get("life_cycle_state"), s.get("result_state"), (s.get("state_message") or "")[:300])')
  case "$state" in
    TERMINATED*|INTERNAL_ERROR*|SKIPPED*) echo "$state"; exit 0 ;;
  esac
  sleep 60
done
echo "still running after $minutes minutes: $state"
exit 1
