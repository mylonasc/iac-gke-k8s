# Benchmark Runs

Each benchmark execution should have its own timestamped subfolder created by:

```bash
bash benchmarks/scripts/init_run.sh <optional-label>
```

Expected run artifacts:

- `run_id.txt`
- `repo_state.txt`
- `cluster_state.txt`
- `notes.txt`
- `results_rows.csv`
- `results_table.md`

Optional generated artifacts:

- `records.jsonl` (raw API responses and per-run metadata)

Run folders are ignored by git to avoid noisy churn.
