#!/usr/bin/env python3
"""Run low-sample benchmark chat cases and append CSV rows.

This runner is intentionally optimized for expensive provisioning paths.
Defaults: 2 runs per case, max 3 unless explicitly overridden.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


CSV_COLUMNS = [
    "run_id",
    "scenario_id",
    "task_id",
    "profile",
    "execution_model",
    "template_name",
    "router_replicas",
    "warm_pool_replicas",
    "gvisor_min_nodes",
    "background_load",
    "t_first_tool_ms",
    "t_steady_tool_ms",
    "t_workspace_prepare_ms",
    "t_workspace_ready_ms",
    "t_claim_ready_ms",
    "t_router_exec_ms",
    "tool_failures",
    "failed_mount_count",
    "lease_stale_count",
    "result",
    "notes",
]

TASK_PROMPTS = {
    "T1": "Use sandbox_exec_python once to print 2+2.",
    "T2": "Create hello.txt in /workspace, then read it back.",
    "T3": "Generate a CSV with 100 rows and summarize row count.",
    "T4": "Create an image asset and return it using the app asset path.",
    "T5": "Install a package in-session and run code using it.",
}

STEADY_PROMPT = "Use sandbox_exec_python once to print 3+3."


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso_utc(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_rfc3339(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def detect_lease_stale_count(status_body: dict[str, Any]) -> str:
    sandbox = status_body.get("sandbox")
    if not isinstance(sandbox, dict):
        return ""

    has_active = bool(sandbox.get("has_active_lease"))
    expires_at_raw = str(sandbox.get("expires_at") or "").strip()
    expires_at = parse_rfc3339(expires_at_raw)
    if not has_active or not expires_at:
        return "0"

    return "1" if expires_at < now_utc() else "0"


def endpoint(base_url: str, api_prefix: str, suffix: str) -> str:
    base = base_url.rstrip("/")
    prefix = api_prefix.strip()
    if not prefix.startswith("/"):
        prefix = f"/{prefix}"
    prefix = prefix.rstrip("/")
    path = suffix if suffix.startswith("/") else f"/{suffix}"
    return f"{base}{prefix}{path}"


def request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None,
    auth_token: str,
    forwarded_access_token: str,
    cookie_header: str,
    timeout_seconds: float,
) -> tuple[int, dict[str, Any], float, str | None]:
    body = None
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    req = urllib.request.Request(url=url, data=body, method=method)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if auth_token:
        req.add_header("Authorization", f"Bearer {auth_token}")
    if forwarded_access_token:
        req.add_header("x-auth-request-access-token", forwarded_access_token)
    if cookie_header:
        req.add_header("Cookie", cookie_header)

    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            raw = resp.read().decode("utf-8", errors="replace")
            if raw.strip():
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    data = {"raw": raw}
            else:
                data = {}
            return (
                int(resp.status),
                data if isinstance(data, dict) else {"data": data},
                elapsed_ms,
                None,
            )
    except urllib.error.HTTPError as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        raw = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        data: dict[str, Any]
        if raw.strip():
            try:
                parsed = json.loads(raw)
                data = parsed if isinstance(parsed, dict) else {"data": parsed}
            except json.JSONDecodeError:
                data = {"raw": raw}
        else:
            data = {}
        return int(exc.code), data, elapsed_ms, f"http_{exc.code}"
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return 0, {}, elapsed_ms, str(exc)


def kubectl_json(
    args: list[str], *, timeout_seconds: int = 20
) -> dict[str, Any] | None:
    cmd = ["kubectl", *args]
    try:
        raw = subprocess.check_output(
            cmd, text=True, stderr=subprocess.DEVNULL, timeout=timeout_seconds
        )
    except Exception:  # noqa: BLE001
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def detect_cluster_state(
    namespace: str, router_deployment: str, warm_pool_name: str
) -> dict[str, str]:
    state = {
        "router_replicas": "",
        "warm_pool_replicas": "",
        "gvisor_min_nodes": "",
    }

    router = kubectl_json(
        ["-n", namespace, "get", "deployment", router_deployment, "-o", "json"]
    )
    if router:
        replicas = (router.get("spec") or {}).get("replicas")
        if replicas is not None:
            state["router_replicas"] = str(replicas)

    warm_pool = kubectl_json(
        ["-n", namespace, "get", "sandboxwarmpool", warm_pool_name, "-o", "json"]
    )
    if warm_pool:
        replicas = (warm_pool.get("spec") or {}).get("replicas")
        if replicas is not None:
            state["warm_pool_replicas"] = str(replicas)

    nodes = kubectl_json(["get", "nodes", "-o", "json"])
    if nodes:
        count = 0
        for item in list(nodes.get("items") or []):
            name = str(((item.get("metadata") or {}).get("name") or ""))
            if "gvisor" in name.lower():
                count += 1
        if count > 0:
            state["gvisor_min_nodes"] = str(count)

    return state


def failed_mount_count_since(namespace: str, started_at: datetime) -> str:
    events = kubectl_json(
        [
            "-n",
            namespace,
            "get",
            "events",
            "--field-selector",
            "reason=FailedMount",
            "-o",
            "json",
        ]
    )
    if not events:
        return ""
    count = 0
    for item in list(events.get("items") or []):
        ts = (
            item.get("eventTime")
            or item.get("lastTimestamp")
            or ((item.get("metadata") or {}).get("creationTimestamp"))
            or ""
        )
        parsed = parse_rfc3339(str(ts))
        if parsed and parsed >= started_at:
            count += 1
    return str(count)


def ensure_csv_with_header(path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writeheader()


def append_csv_row(path: Path, row: dict[str, Any]) -> None:
    ensure_csv_with_header(path)
    normalized = {col: row.get(col, "") for col in CSV_COLUMNS}
    with path.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        writer.writerow(normalized)


def run_case_once(
    args: argparse.Namespace, run_idx: int, run_id: str
) -> dict[str, Any]:
    case_started = now_utc()
    notes: list[str] = [f"case_started={iso_utc(case_started)}", f"run_index={run_idx}"]
    tool_failures = 0
    result = "pass"

    create_url = endpoint(args.base_url, args.api_prefix, "/sessions")
    status, create_body, _, create_err = request_json(
        "POST",
        create_url,
        payload={"title": f"benchmark {args.scenario_id} {args.task_id} run {run_idx}"},
        auth_token=args.auth_token,
        forwarded_access_token=args.forwarded_access_token,
        cookie_header=args.cookie_header,
        timeout_seconds=args.request_timeout_seconds,
    )
    if status != 200 or create_err:
        return {
            "run_id": run_id,
            "scenario_id": args.scenario_id,
            "task_id": args.task_id,
            "profile": args.profile,
            "execution_model": args.execution_model,
            "template_name": args.template_name,
            "router_replicas": args.router_replicas,
            "warm_pool_replicas": args.warm_pool_replicas,
            "gvisor_min_nodes": args.gvisor_min_nodes,
            "background_load": args.background_load,
            "t_first_tool_ms": "",
            "t_steady_tool_ms": "",
            "t_workspace_prepare_ms": "",
            "t_workspace_ready_ms": "",
            "t_claim_ready_ms": "",
            "t_router_exec_ms": "",
            "tool_failures": "1",
            "failed_mount_count": "",
            "lease_stale_count": "",
            "result": "fail",
            "notes": f"session_create_failed status={status} error={create_err} body={json.dumps(create_body, ensure_ascii=True)}",
            "_record": {
                "session_create": {
                    "status": status,
                    "error": create_err,
                    "body": create_body,
                }
            },
        }

    session_id = str(create_body.get("session_id") or "").strip()
    if not session_id:
        return {
            "run_id": run_id,
            "scenario_id": args.scenario_id,
            "task_id": args.task_id,
            "profile": args.profile,
            "execution_model": args.execution_model,
            "template_name": args.template_name,
            "router_replicas": args.router_replicas,
            "warm_pool_replicas": args.warm_pool_replicas,
            "gvisor_min_nodes": args.gvisor_min_nodes,
            "background_load": args.background_load,
            "t_first_tool_ms": "",
            "t_steady_tool_ms": "",
            "t_workspace_prepare_ms": "",
            "t_workspace_ready_ms": "",
            "t_claim_ready_ms": "",
            "t_router_exec_ms": "",
            "tool_failures": "1",
            "failed_mount_count": "",
            "lease_stale_count": "",
            "result": "fail",
            "notes": "session_create_missing_session_id",
            "_record": {"session_create": create_body},
        }

    notes.append(f"session_id={session_id}")

    policy_url = endpoint(
        args.base_url, args.api_prefix, f"/sessions/{session_id}/sandbox/policy"
    )
    policy_payload: dict[str, Any] = {
        "mode": args.mode,
        "profile": args.profile,
        "execution_model": args.execution_model,
    }
    if args.template_name:
        policy_payload["template_name"] = args.template_name
    if args.session_idle_ttl_seconds is not None:
        policy_payload["session_idle_ttl_seconds"] = args.session_idle_ttl_seconds

    policy_status, policy_body, _, policy_err = request_json(
        "PATCH",
        policy_url,
        payload=policy_payload,
        auth_token=args.auth_token,
        forwarded_access_token=args.forwarded_access_token,
        cookie_header=args.cookie_header,
        timeout_seconds=args.request_timeout_seconds,
    )
    if policy_status != 200 or policy_err:
        tool_failures += 1
        result = "fail"
        notes.append(f"policy_patch_failed status={policy_status} error={policy_err}")

    workspace_prepare_ms = ""
    workspace_action_record: dict[str, Any] = {}
    if args.workspace_action != "none":
        action_url = endpoint(
            args.base_url, args.api_prefix, f"/sessions/{session_id}/sandbox/actions"
        )
        action_started = time.perf_counter()
        action_status, action_body, _, action_err = request_json(
            "POST",
            action_url,
            payload={
                "action": args.workspace_action,
                "wait": bool(args.workspace_wait),
            },
            auth_token=args.auth_token,
            forwarded_access_token=args.forwarded_access_token,
            cookie_header=args.cookie_header,
            timeout_seconds=args.request_timeout_seconds,
        )
        elapsed = (time.perf_counter() - action_started) * 1000.0
        workspace_prepare_ms = str(int(round(elapsed)))
        workspace_action_record = {
            "status": action_status,
            "error": action_err,
            "body": action_body,
        }
        if action_status != 200 or action_err:
            tool_failures += 1
            result = "fail"
            notes.append(
                f"workspace_action_failed status={action_status} error={action_err}"
            )

    status_url = endpoint(
        args.base_url, args.api_prefix, f"/sessions/{session_id}/sandbox/status"
    )
    _, pre_status_body, _, _ = request_json(
        "GET",
        status_url,
        payload=None,
        auth_token=args.auth_token,
        forwarded_access_token=args.forwarded_access_token,
        cookie_header=args.cookie_header,
        timeout_seconds=args.request_timeout_seconds,
    )

    chat_url = endpoint(args.base_url, args.api_prefix, "/chat")
    task_prompt = TASK_PROMPTS[args.task_id]

    first_status, first_body, first_elapsed_ms, first_err = request_json(
        "POST",
        chat_url,
        payload={"session_id": session_id, "message": task_prompt},
        auth_token=args.auth_token,
        forwarded_access_token=args.forwarded_access_token,
        cookie_header=args.cookie_header,
        timeout_seconds=args.request_timeout_seconds,
    )
    t_first_tool_ms = str(int(round(first_elapsed_ms)))
    if first_status != 200 or first_err or first_body.get("error"):
        tool_failures += 1
        result = "fail"
        notes.append(
            f"first_chat_failed status={first_status} error={first_err} detail={first_body.get('error')}"
        )

    t_steady_tool_ms = ""
    second_status = 0
    second_err: str | None = None
    second_body: dict[str, Any] = {}
    if args.measure_steady:
        second_status, second_body, second_elapsed_ms, second_err = request_json(
            "POST",
            chat_url,
            payload={"session_id": session_id, "message": STEADY_PROMPT},
            auth_token=args.auth_token,
            forwarded_access_token=args.forwarded_access_token,
            cookie_header=args.cookie_header,
            timeout_seconds=args.request_timeout_seconds,
        )
        t_steady_tool_ms = str(int(round(second_elapsed_ms)))
        if second_status != 200 or second_err or second_body.get("error"):
            tool_failures += 1
            result = "fail"
            notes.append(
                f"steady_chat_failed status={second_status} error={second_err} detail={second_body.get('error')}"
            )

    if args.idle_wait_seconds > 0:
        notes.append(f"idle_wait_seconds={args.idle_wait_seconds}")
        time.sleep(float(args.idle_wait_seconds))

    _, post_status_body, _, _ = request_json(
        "GET",
        status_url,
        payload=None,
        auth_token=args.auth_token,
        forwarded_access_token=args.forwarded_access_token,
        cookie_header=args.cookie_header,
        timeout_seconds=args.request_timeout_seconds,
    )

    if args.release_lease:
        action_url = endpoint(
            args.base_url, args.api_prefix, f"/sessions/{session_id}/sandbox/actions"
        )
        request_json(
            "POST",
            action_url,
            payload={"action": "release_lease", "wait": False},
            auth_token=args.auth_token,
            forwarded_access_token=args.forwarded_access_token,
            cookie_header=args.cookie_header,
            timeout_seconds=args.request_timeout_seconds,
        )

    failed_mount_count = ""
    if args.collect_failed_mounts:
        failed_mount_count = failed_mount_count_since(args.namespace, case_started)

    lease_stale_count = detect_lease_stale_count(post_status_body)

    row = {
        "run_id": run_id,
        "scenario_id": args.scenario_id,
        "task_id": args.task_id,
        "profile": args.profile,
        "execution_model": args.execution_model,
        "template_name": args.template_name,
        "router_replicas": args.router_replicas,
        "warm_pool_replicas": args.warm_pool_replicas,
        "gvisor_min_nodes": args.gvisor_min_nodes,
        "background_load": args.background_load,
        "t_first_tool_ms": t_first_tool_ms,
        "t_steady_tool_ms": t_steady_tool_ms,
        "t_workspace_prepare_ms": workspace_prepare_ms,
        "t_workspace_ready_ms": "",
        "t_claim_ready_ms": "",
        "t_router_exec_ms": "",
        "tool_failures": str(tool_failures),
        "failed_mount_count": failed_mount_count,
        "lease_stale_count": lease_stale_count,
        "result": result,
        "notes": "; ".join(notes),
        "_record": {
            "session_id": session_id,
            "policy": {
                "status": policy_status,
                "error": policy_err,
                "body": policy_body,
            },
            "workspace_action": workspace_action_record,
            "pre_status": pre_status_body,
            "first_chat": {
                "status": first_status,
                "error": first_err,
                "elapsed_ms": t_first_tool_ms,
                "body": first_body,
            },
            "steady_chat": {
                "status": second_status,
                "error": second_err,
                "elapsed_ms": t_steady_tool_ms,
                "body": second_body,
            },
            "post_status": post_status_body,
        },
    }
    return row


def read_run_id(run_dir: Path) -> str:
    run_id_path = run_dir / "run_id.txt"
    if run_id_path.exists():
        return run_id_path.read_text(encoding="utf-8").strip() or run_dir.name
    return run_dir.name


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute low-sample benchmark chat runs."
    )
    parser.add_argument(
        "--run-dir", required=True, help="Path to benchmarks/runs/<run_id>"
    )
    parser.add_argument(
        "--scenario-id", required=True, help="Scenario id (example: S1)"
    )
    parser.add_argument("--task-id", default="T1", choices=sorted(TASK_PROMPTS.keys()))
    parser.add_argument(
        "--runs", type=int, default=2, help="Number of runs for this case (default: 2)"
    )
    parser.add_argument(
        "--max-runs-per-case",
        type=int,
        default=3,
        help="Soft cap for expensive provisioning paths (default: 3)",
    )
    parser.add_argument(
        "--allow-more-runs",
        action="store_true",
        help="Allow run counts above --max-runs-per-case",
    )

    parser.add_argument(
        "--base-url", default="http://localhost:8080", help="Backend base URL"
    )
    parser.add_argument(
        "--api-prefix", default="/api", help="API prefix (default: /api)"
    )
    parser.add_argument("--auth-token", default=os.getenv("BENCHMARK_AUTH_TOKEN", ""))
    parser.add_argument(
        "--forwarded-access-token",
        default=os.getenv("BENCHMARK_X_AUTH_REQUEST_ACCESS_TOKEN", ""),
        help="Optional x-auth-request-access-token header value",
    )
    parser.add_argument(
        "--cookie-header",
        default=os.getenv("BENCHMARK_COOKIE", ""),
        help="Optional raw Cookie header value (example: _oauth2_proxy=...)",
    )
    parser.add_argument("--request-timeout-seconds", type=float, default=180.0)

    parser.add_argument("--mode", default="cluster")
    parser.add_argument(
        "--profile",
        default="transient",
        choices=["transient", "persistent_workspace", "persistent"],
    )
    parser.add_argument(
        "--execution-model", default="session", choices=["session", "ephemeral"]
    )
    parser.add_argument("--template-name", default="python-runtime-template-small")
    parser.add_argument(
        "--session-idle-ttl-seconds",
        type=int,
        default=None,
        help="Optional session lease idle TTL override in seconds",
    )

    parser.add_argument(
        "--workspace-action",
        default="none",
        choices=[
            "none",
            "ensure_workspace_async",
            "ensure_workspace",
            "reconcile_workspace",
        ],
    )
    parser.add_argument("--workspace-wait", action="store_true")
    parser.add_argument("--measure-steady", action="store_true", default=True)
    parser.add_argument(
        "--no-measure-steady", action="store_false", dest="measure_steady"
    )

    parser.add_argument(
        "--namespace",
        default="alt-default",
        help="Namespace for kubectl-derived signals",
    )
    parser.add_argument("--router-deployment", default="sandbox-router-deployment")
    parser.add_argument("--warm-pool-name", default="python-sandbox-warmpool")
    parser.add_argument("--background-load", default="low", choices=["low", "moderate"])
    parser.add_argument("--collect-failed-mounts", action="store_true")
    parser.add_argument(
        "--idle-wait-seconds",
        type=int,
        default=0,
        help="Optional idle wait after tool execution before final status read",
    )
    parser.add_argument("--release-lease", action="store_true", default=True)
    parser.add_argument(
        "--no-release-lease", action="store_false", dest="release_lease"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.profile == "persistent":
        args.profile = "persistent_workspace"

    if args.runs <= 0:
        print("--runs must be >= 1", file=sys.stderr)
        return 2
    if args.max_runs_per_case <= 0:
        print("--max-runs-per-case must be >= 1", file=sys.stderr)
        return 2
    if args.runs > args.max_runs_per_case and not args.allow_more_runs:
        print(
            f"Requested runs ({args.runs}) exceeds max-runs-per-case ({args.max_runs_per_case}). "
            "Use --allow-more-runs to override.",
            file=sys.stderr,
        )
        return 2

    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.exists() or not run_dir.is_dir():
        print(f"Run directory not found: {run_dir}", file=sys.stderr)
        return 2

    run_id = read_run_id(run_dir)
    rows_csv_path = run_dir / "results_rows.csv"
    records_path = run_dir / "records.jsonl"

    cluster_state = detect_cluster_state(
        namespace=args.namespace,
        router_deployment=args.router_deployment,
        warm_pool_name=args.warm_pool_name,
    )
    args.router_replicas = cluster_state["router_replicas"]
    args.warm_pool_replicas = cluster_state["warm_pool_replicas"]
    args.gvisor_min_nodes = cluster_state["gvisor_min_nodes"]

    print(
        f"Running case scenario={args.scenario_id} task={args.task_id} profile={args.profile} "
        f"execution={args.execution_model} template={args.template_name} runs={args.runs}"
    )

    passes = 0
    failures = 0

    for idx in range(1, args.runs + 1):
        row = run_case_once(args, idx, run_id)
        append_csv_row(rows_csv_path, row)

        record = dict(row.get("_record") or {})
        record["row"] = {k: v for k, v in row.items() if not k.startswith("_")}
        with records_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=True) + "\n")

        if row.get("result") == "pass":
            passes += 1
        else:
            failures += 1

        print(
            f"  run {idx}/{args.runs}: result={row.get('result')} "
            f"t_first={row.get('t_first_tool_ms')}ms t_steady={row.get('t_steady_tool_ms')}ms"
        )

    print(
        f"Completed case. pass={passes} fail={failures}. "
        f"Rows appended to {rows_csv_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
