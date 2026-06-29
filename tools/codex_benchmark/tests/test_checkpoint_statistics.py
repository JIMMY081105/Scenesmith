from __future__ import annotations

from pathlib import Path

from codex_benchmark.checkpoint import CallRecord, CheckpointStore, utc_now
from codex_benchmark.statistics import compute_summary


def test_checkpoint_records_calls_and_attempt_timeouts(tmp_path: Path) -> None:
    store = CheckpointStore(str(tmp_path / "benchmark.sqlite3"))
    run_id = "unit_run"
    now = utc_now()
    try:
        store.start_run(
            run_id=run_id,
            config_hash="hash",
            config_json="{}",
            codex_version="unit",
            resume=False,
        )
        store.record_call(
            CallRecord(
                run_id=run_id,
                module="structured",
                scenario="schema_json",
                call_index=0,
                status="success",
                success=True,
                started_at=now,
                ended_at=now,
                latency_ms=100.0,
                retries=1,
                attempt_count=2,
                attempt_json_failures=1,
                attempt_schema_failures=1,
                invalid_json=False,
                schema_valid=True,
                metadata={
                    "attempts": [
                        {
                            "attempt": 0,
                            "success": False,
                            "error_kind": "timeout",
                            "invalid_json": True,
                            "schema_valid": False,
                        },
                        {
                            "attempt": 1,
                            "success": True,
                            "error_kind": None,
                            "invalid_json": False,
                            "schema_valid": True,
                        },
                    ]
                },
            )
        )

        assert store.call_exists(run_id, "structured", "schema_json", 0)
        summary = compute_summary(store, run_id)
    finally:
        store.close()

    scenario = summary["scenarios"][0]
    assert scenario["calls"] == 1
    assert scenario["success_rate"] == 1.0
    assert scenario["attempt_timeout_count"] == 1
    assert scenario["attempt_json_failure_rate"] == 0.5
    assert scenario["attempt_schema_failure_rate"] == 0.5
