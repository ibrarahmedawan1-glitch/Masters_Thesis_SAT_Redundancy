#!/usr/bin/env bash
set -eu

pilot_unit="alg10-parcommit-sqrt-30m-20260614-0129.service"
pilot_summary="results_optimized/parallel_commit_sqrt_30m_20260614_0129/summary.json"

echo "Waiting for ${pilot_unit} to finish..."
while systemctl --user is-active --quiet "$pilot_unit"; do
  sleep 15
done

if [ ! -f "$pilot_summary" ]; then
  echo "NO-GO: pilot summary was not written: ${pilot_summary}"
  exit 0
fi

if ! venv/bin/python -c '
import json
import sys

path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

totals = data.get("totals", {})
verify_ok = data.get("final_verify") == "PASS"
cec_ok = int(totals.get("cec_failed_commits", 0)) == 0
useful = (
    int(totals.get("coordinator_unsat_accept", 0)) > 0
    or int(totals.get("worker_sat_reject", 0)) > 0
)
print(
    "Pilot decision:",
    {
        "verify": data.get("final_verify"),
        "elapsed": data.get("elapsed"),
        "removed": data.get("removed"),
        "totals": totals,
        "go": bool(verify_ok and cec_ok and useful),
    },
)
sys.exit(0 if verify_ok and cec_ok and useful else 1)
' "$pilot_summary"; then
  echo "NO-GO: pilot produced no useful classification or accepted commit."
  exit 0
fi

export RUN_TAG="sqrt_12h_$(date +%Y%m%d_%H%M%S)"
echo "GO: starting overnight continuation with tag ${RUN_TAG}"
exec /bin/bash /home/ibrar/MyThesis/run_alg10_parallel_commit_sqrt_12h.sh
