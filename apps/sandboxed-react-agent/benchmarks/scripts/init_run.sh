#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BENCHMARK_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNS_DIR="${BENCHMARK_DIR}/runs"
TEMPLATES_DIR="${BENCHMARK_DIR}/templates"

raw_label="${1:-}"
label=""
if [[ -n "${raw_label}" ]]; then
  label="$(printf "%s" "${raw_label}" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | tr -cd 'a-z0-9_-')"
  if [[ -z "${label}" ]]; then
    echo "Run label '${raw_label}' becomes empty after sanitization."
    exit 1
  fi
fi

timestamp="$(date -u +"%Y%m%dT%H%M%SZ")"
run_id="${timestamp}"
if [[ -n "${label}" ]]; then
  run_id="${run_id}_${label}"
fi

run_dir="${RUNS_DIR}/${run_id}"
if [[ -e "${run_dir}" ]]; then
  echo "Run directory already exists: ${run_dir}"
  exit 1
fi

mkdir -p "${run_dir}"

cp "${TEMPLATES_DIR}/run_notes_template.txt" "${run_dir}/notes.txt"
cp "${TEMPLATES_DIR}/results_table_template.md" "${run_dir}/results_table.md"
cp "${TEMPLATES_DIR}/results_rows_template.csv" "${run_dir}/results_rows.csv"

printf "%s\n" "${run_id}" >"${run_dir}/run_id.txt"

bash "${SCRIPT_DIR}/capture_state.sh" "${run_dir}"

echo "Created benchmark run: ${run_id}"
echo "Run folder: ${run_dir}"
echo "Next: fill notes.txt, results_rows.csv, and results_table.md after execution."
