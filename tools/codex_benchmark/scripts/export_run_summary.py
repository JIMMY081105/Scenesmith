"""Export compact run summaries from the benchmark SQLite database."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path


PROJECT_PARENT = Path(__file__).resolve().parents[2]
if str(PROJECT_PARENT) not in sys.path:
    sys.path.insert(0, str(PROJECT_PARENT))

from codex_benchmark.statistics import compute_summary  # noqa: E402
from codex_benchmark.checkpoint import CheckpointStore  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print a compact benchmark run summary.")
    parser.add_argument("--database", default="outputs/benchmark.sqlite3")
    parser.add_argument("--run-id", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    database = Path(args.database)
    if not database.exists():
        print(f"Database not found: {database}", file=sys.stderr)
        return 2

    store = CheckpointStore(str(database))
    try:
        summary = compute_summary(store, args.run_id)
    finally:
        store.close()

    run = summary["run"]
    if not run:
        print(f"Run not found: {args.run_id}", file=sys.stderr)
        return 1

    print(f"run_id: {run['run_id']}")
    print(f"status: {run['status']}")
    print(f"codex_version: {run['codex_version']}")
    for row in summary["scenarios"]:
        print(
            f"{row['module']}:{row['scenario']} "
            f"calls={row['calls']} "
            f"success_rate={row['success_rate']:.4f} "
            f"avg_ms={row['avg_latency_ms']:.2f} "
            f"max_ms={row['max_latency_ms']:.2f} "
            f"attempt_timeouts={row['attempt_timeout_count']} "
            f"invalid_json={row['invalid_json_count']} "
            f"schema_failures={row['schema_failure_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
