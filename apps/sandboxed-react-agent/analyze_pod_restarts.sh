#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${NAMESPACE:-alt-default}"
TARGET="${1:-sandboxed-react-agent-backend}"
TAIL_LINES="${TAIL_LINES:-300}"

tmp_dir="$(mktemp -d)"
cleanup() {
  rm -rf "${tmp_dir}"
}
trap cleanup EXIT

echo "Analyzing pod restarts in namespace=${NAMESPACE} target=${TARGET}"

pods_json="${tmp_dir}/pods.json"
kubectl -n "${NAMESPACE}" get pods -o json > "${pods_json}"

python3 - "${pods_json}" "${TARGET}" > "${tmp_dir}/pod_candidates.txt" <<'PY'
import json
import sys

path = sys.argv[1]
target = sys.argv[2]
data = json.load(open(path))

def total_restarts(item):
    statuses = item.get("status", {}).get("containerStatuses", []) or []
    return sum(int(s.get("restartCount", 0)) for s in statuses)

rows = []
for item in data.get("items", []):
    name = item.get("metadata", {}).get("name", "")
    if target in name:
        rows.append((name, total_restarts(item), item.get("metadata", {}).get("creationTimestamp", "")))

rows.sort(key=lambda x: (x[1], x[2], x[0]), reverse=True)
for name, restarts, created in rows:
    print(f"{name}\t{restarts}\t{created}")
PY

if [[ ! -s "${tmp_dir}/pod_candidates.txt" ]]; then
  echo "No pods found matching target '${TARGET}'."
  exit 1
fi

echo
echo "Candidate pods (sorted by restart count):"
python3 - "${tmp_dir}/pod_candidates.txt" <<'PY'
import sys
for line in open(sys.argv[1]):
    name, restarts, created = line.strip().split("\t")
    print(f"- {name}: restarts={restarts}, created={created}")
PY

pod_name="$(python3 - "${tmp_dir}/pod_candidates.txt" <<'PY'
import sys
line = open(sys.argv[1]).readline().strip()
print(line.split("\t")[0] if line else "")
PY
)"

if [[ -z "${pod_name}" ]]; then
  echo "Failed to select a pod candidate."
  exit 1
fi

echo
echo "Inspecting pod: ${pod_name}"

pod_json="${tmp_dir}/pod.json"
kubectl -n "${NAMESPACE}" get pod "${pod_name}" -o json > "${pod_json}"
kubectl -n "${NAMESPACE}" describe pod "${pod_name}" > "${tmp_dir}/describe.txt"
kubectl -n "${NAMESPACE}" logs "${pod_name}" --tail="${TAIL_LINES}" > "${tmp_dir}/logs_current.txt" 2>&1 || true
kubectl -n "${NAMESPACE}" logs "${pod_name}" --previous --tail="${TAIL_LINES}" > "${tmp_dir}/logs_previous.txt" 2>&1 || true
kubectl -n "${NAMESPACE}" get events --field-selector "involvedObject.kind=Pod,involvedObject.name=${pod_name}" --sort-by=.metadata.creationTimestamp > "${tmp_dir}/events.txt" 2>&1 || true

kubectl -n "${NAMESPACE}" get deploy sandbox-router-deployment -o json > "${tmp_dir}/router_deploy.json" 2>/dev/null || true
kubectl -n "${NAMESPACE}" get endpoints sandbox-router-svc -o json > "${tmp_dir}/router_endpoints.json" 2>/dev/null || true

python3 - "${tmp_dir}" <<'PY'
import json
import os
import re
import sys

tmp_dir = sys.argv[1]

pod = json.load(open(os.path.join(tmp_dir, "pod.json")))
statuses = pod.get("status", {}).get("containerStatuses", []) or []

print("\nRestart details:")
if not statuses:
    print("- No container status available")

for st in statuses:
    name = st.get("name", "unknown")
    restarts = st.get("restartCount", 0)
    state = st.get("state", {})
    last = st.get("lastState", {})
    print(f"- container={name} restarts={restarts}")

    term = last.get("terminated") if isinstance(last, dict) else None
    if term:
        print(
            "  last_terminated="
            f"reason={term.get('reason')} exitCode={term.get('exitCode')} "
            f"startedAt={term.get('startedAt')} finishedAt={term.get('finishedAt')}"
        )

events = open(os.path.join(tmp_dir, "events.txt")).read()
logs_current = open(os.path.join(tmp_dir, "logs_current.txt")).read()
logs_prev = open(os.path.join(tmp_dir, "logs_previous.txt")).read()
describe = open(os.path.join(tmp_dir, "describe.txt")).read()

router_replicas = None
router_ready = None
router_file = os.path.join(tmp_dir, "router_deploy.json")
if os.path.exists(router_file) and os.path.getsize(router_file) > 0:
    try:
        r = json.load(open(router_file))
        router_replicas = r.get("spec", {}).get("replicas")
        router_ready = r.get("status", {}).get("readyReplicas", 0)
    except Exception:
        pass

router_endpoints = []
ep_file = os.path.join(tmp_dir, "router_endpoints.json")
if os.path.exists(ep_file) and os.path.getsize(ep_file) > 0:
    try:
        ep = json.load(open(ep_file))
        subsets = ep.get("subsets", []) or []
        for s in subsets:
            for a in s.get("addresses", []) or []:
                ip = a.get("ip")
                if ip:
                    router_endpoints.append(ip)
    except Exception:
        pass

print("\nRouter status:")
if router_replicas is None:
    print("- sandbox-router-deployment not found")
else:
    print(f"- sandbox-router-deployment replicas={router_replicas} ready={router_ready}")
print(f"- sandbox-router-svc endpoints={len(router_endpoints)} {router_endpoints}")

signals = []

if "OOMKilled" in describe or "OOMKilled" in events:
    signals.append("OOMKilled detected")

if "Liveness probe failed" in events or "Readiness probe failed" in events:
    signals.append("Probe failures detected")

if (
    "Request to gateway router failed" in logs_current
    or "Request to gateway router failed" in logs_prev
    or "connection refused" in logs_current.lower()
    or "connection refused" in logs_prev.lower()
    or "Read timed out" in logs_current
    or "Read timed out" in logs_prev
    or "Sandbox did not become ready" in logs_current
    or "Sandbox did not become ready" in logs_prev
):
    signals.append("Sandbox router/sandbox readiness errors in logs")

if router_replicas == 0 or len(router_endpoints) == 0:
    signals.append("Router unavailable (0 replicas or no service endpoints)")

print("\nDetected signals:")
if not signals:
    print("- none")
else:
    for s in signals:
        print(f"- {s}")

print("\nLikely root cause:")
if "OOMKilled detected" in signals:
    print("- Backend likely restarted due to memory pressure (OOM).")
elif "Probe failures detected" in signals and "Sandbox router/sandbox readiness errors in logs" in signals:
    print("- Backend likely restarted by failed health probes while blocked on sandbox/router operations.")
elif "Probe failures detected" in signals:
    print("- Backend likely restarted by kubelet after health probe failures.")
elif "Sandbox router/sandbox readiness errors in logs" in signals:
    print("- Tool calls likely failed due to router/sandbox readiness issues; restarts may be secondary.")
else:
    print("- No single dominant cause detected; inspect previous logs and pod events in detail.")

print("\nFiles saved for deeper inspection:")
for name in [
    "describe.txt",
    "events.txt",
    "logs_previous.txt",
    "logs_current.txt",
]:
    print(f"- {os.path.join(tmp_dir, name)}")
PY
