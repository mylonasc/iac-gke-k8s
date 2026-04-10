#!/usr/bin/env python3
"""Build results_table.md from results_rows.csv.

Optimized for low-sample runs (2-3 repetitions per case).
"""

from __future__ import annotations

import argparse
import csv
import math
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


METRICS = [
    "t_first_tool_ms",
    "t_steady_tool_ms",
    "t_workspace_prepare_ms",
    "t_workspace_ready_ms",
    "t_claim_ready_ms",
    "t_router_exec_ms",
]


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_float(value: str | None) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def to_int(value: str | None) -> int | None:
    parsed = to_float(value)
    if parsed is None:
        return None
    return int(parsed)


def percentile_nearest_rank(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    rank = max(1, math.ceil((percentile / 100.0) * n))
    return ordered[rank - 1]


def fmt_num(value: float | None) -> str:
    if value is None:
        return ""
    return str(int(round(value)))


def parse_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        return [{k: (v or "") for k, v in row.items()} for row in reader]


def failure_row(row: dict[str, str]) -> bool:
    result = str(row.get("result") or "").strip().lower()
    if result and result not in {"pass", "ok", "success"}:
        return True
    tool_failures = to_int(row.get("tool_failures"))
    return bool(tool_failures and tool_failures > 0)


def safe_median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def build_markdown(run_id: str, rows: list[dict[str, str]]) -> str:
    lines: list[str] = []
    lines.append("# Results Table")
    lines.append("")
    lines.append("## Run metadata")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| run_id | {run_id} |")
    lines.append(f"| generated_utc | {utc_now_iso()} |")
    lines.append(f"| total_rows | {len(rows)} |")

    lines.append("")
    lines.append("## Latency summary (ms)")
    lines.append("")
    lines.append("| Metric | n | p50 | p95 | p99 | Notes |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for metric in METRICS:
        values = [to_float(row.get(metric)) for row in rows]
        samples = [v for v in values if v is not None]
        p50 = percentile_nearest_rank(samples, 50)
        p95 = percentile_nearest_rank(samples, 95)
        p99 = percentile_nearest_rank(samples, 99)
        note = ""
        if 0 < len(samples) < 5:
            note = f"low-sample n={len(samples)}"
        lines.append(
            f"| {metric} | {len(samples)} | {fmt_num(p50)} | {fmt_num(p95)} | {fmt_num(p99)} | {note} |"
        )

    total_rows = len(rows)
    failed_rows = sum(1 for row in rows if failure_row(row))
    failure_rate = (failed_rows / total_rows * 100.0) if total_rows else 0.0

    failed_mount_total = 0
    lease_stale_total = 0
    for row in rows:
        failed_mount_total += to_int(row.get("failed_mount_count")) or 0
        lease_stale_total += to_int(row.get("lease_stale_count")) or 0

    lines.append("")
    lines.append("## Reliability summary")
    lines.append("")
    lines.append("| Metric | Value | Notes |")
    lines.append("| --- | --- | --- |")
    lines.append(
        f"| tool_failure_rate | {failure_rate:.1f}% | fail_rows={failed_rows}/{total_rows} |"
    )
    lines.append(f"| failed_mount_count | {failed_mount_total} | summed from rows |")
    lines.append(f"| lease_stale_count | {lease_stale_total} | summed from rows |")

    scenario_groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        sid = str(row.get("scenario_id") or "")
        tid = str(row.get("task_id") or "")
        scenario_groups[(sid, tid)].append(row)

    lines.append("")
    lines.append("## Scenario outcomes")
    lines.append("")
    lines.append("| Scenario ID | Task ID | Outcome | Key observation |")
    lines.append("| --- | --- | --- | --- |")

    for (scenario_id, task_id), group in sorted(scenario_groups.items()):
        passes = sum(1 for row in group if not failure_row(row))
        total = len(group)
        first_vals = [to_float(row.get("t_first_tool_ms")) for row in group]
        first_samples = [v for v in first_vals if v is not None]
        med_first = safe_median(first_samples)
        outcome = f"{passes}/{total} pass"
        observation = (
            f"median t_first={fmt_num(med_first)}ms"
            if med_first is not None
            else "no t_first samples"
        )
        lines.append(f"| {scenario_id} | {task_id} | {outcome} | {observation} |")

    lines.append("")
    lines.append("## Insights")
    lines.append("")

    transient_first = [
        to_float(row.get("t_first_tool_ms"))
        for row in rows
        if str(row.get("profile") or "") == "transient"
    ]
    transient_first_samples = [v for v in transient_first if v is not None]

    persistent_first = [
        to_float(row.get("t_first_tool_ms"))
        for row in rows
        if str(row.get("profile") or "") == "persistent_workspace"
    ]
    persistent_first_samples = [v for v in persistent_first if v is not None]

    med_transient = safe_median(transient_first_samples)
    med_persistent = safe_median(persistent_first_samples)

    if med_transient is not None and med_persistent is not None:
        delta = med_persistent - med_transient
        if delta > 0:
            lines.append(
                f"- Persistent first-tool latency is slower than transient by ~{int(round(delta))}ms (median)."
            )
        elif delta < 0:
            lines.append(
                f"- Persistent first-tool latency is faster than transient by ~{int(round(abs(delta)))}ms (median)."
            )
        else:
            lines.append(
                "- Persistent and transient first-tool medians are equal in this sample."
            )
    else:
        lines.append(
            "- Not enough mixed profile data yet for transient vs persistent latency comparison."
        )

    if total_rows < 5:
        lines.append(
            "- Sample size is very small; prefer paired before/after comparisons and rerun only the highest-impact cases."
        )

    lines.append(
        "- For this repository, tracking median + max usually provides a more stable signal than tail percentiles at n<=3."
    )

    lines.append("")
    return "\n".join(lines)


def read_run_id(run_dir: Path) -> str:
    run_id_path = run_dir / "run_id.txt"
    if run_id_path.exists():
        text = run_id_path.read_text(encoding="utf-8").strip()
        if text:
            return text
    return run_dir.name


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate results_table.md from results_rows.csv"
    )
    parser.add_argument(
        "--run-dir", required=True, help="Path to benchmarks/runs/<run_id>"
    )
    parser.add_argument(
        "--rows", default="results_rows.csv", help="CSV filename under run-dir"
    )
    parser.add_argument(
        "--out",
        default="results_table.md",
        help="Output markdown filename under run-dir",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).expanduser().resolve()
    if not run_dir.exists() or not run_dir.is_dir():
        print(f"Run directory not found: {run_dir}")
        return 2

    rows_path = run_dir / args.rows
    if not rows_path.exists():
        print(f"Rows CSV not found: {rows_path}")
        return 2

    rows = parse_rows(rows_path)
    run_id = read_run_id(run_dir)
    output_path = run_dir / args.out
    output_path.write_text(build_markdown(run_id, rows), encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
