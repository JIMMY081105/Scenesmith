"""SQLite checkpoint and result store."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class CallRecord:
    run_id: str
    module: str
    scenario: str
    call_index: int
    status: str
    success: bool
    started_at: str
    ended_at: str
    latency_ms: float | None = None
    retries: int = 0
    attempt_count: int = 1
    attempt_json_failures: int = 0
    attempt_schema_failures: int = 0
    timeout: bool = False
    rate_limited: bool = False
    usage_exhausted: bool = False
    return_code: int | None = None
    error_kind: str | None = None
    error_message: str | None = None
    invalid_json: bool = False
    schema_valid: bool | None = None
    hallucinated_fields: int = 0
    missing_fields: int = 0
    cache_hit: bool = False
    cache_key: str | None = None
    prompt_hash: str | None = None
    schema_hash: str | None = None
    image_hash: str | None = None
    output_text: str | None = None
    output_path: str | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    last_message_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class CheckpointStore:
    """Durable benchmark state.

    Each completed call is stored in `call_results` and then the module checkpoint is
    advanced. On resume, the orchestrator skips rows already present for a
    `(run_id, module, scenario, call_index)` tuple.
    """

    def __init__(self, database_path: str):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.database_path), timeout=60)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self._migrate()

    def close(self) -> None:
        self.conn.close()

    def start_run(
        self,
        run_id: str,
        config_hash: str,
        config_json: str,
        codex_version: str,
        resume: bool,
    ) -> None:
        existing = self.conn.execute(
            "SELECT run_id FROM benchmark_runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        now = utc_now()
        if existing and not resume:
            raise ValueError(
                f"Run id already exists: {run_id}. Use --resume --run-id {run_id}."
            )
        if existing:
            self.conn.execute(
                """
                UPDATE benchmark_runs
                SET status = 'running',
                    updated_at = ?,
                    resume_count = resume_count + 1,
                    pid = ?
                WHERE run_id = ?
                """,
                (now, os.getpid(), run_id),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO benchmark_runs (
                    run_id, started_at, updated_at, status, config_hash,
                    config_json, codex_version, resume_count, interrupted_count, pid
                )
                VALUES (?, ?, ?, 'running', ?, ?, ?, 0, 0, ?)
                """,
                (run_id, now, now, config_hash, config_json, codex_version, os.getpid()),
            )
        self.conn.commit()

    def mark_run_status(self, run_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE benchmark_runs SET status = ?, updated_at = ? WHERE run_id = ?",
            (status, utc_now(), run_id),
        )
        self.conn.commit()

    def mark_interrupted(self, run_id: str, status: str = "interrupted") -> None:
        self.conn.execute(
            """
            UPDATE benchmark_runs
            SET status = ?, updated_at = ?, interrupted_count = interrupted_count + 1
            WHERE run_id = ?
            """,
            (status, utc_now(), run_id),
        )
        self.conn.commit()

    def record_call(self, record: CallRecord) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO call_results (
                run_id, module, scenario, call_index, status, success,
                started_at, ended_at, latency_ms, retries, attempt_count,
                attempt_json_failures, attempt_schema_failures, timeout,
                rate_limited, usage_exhausted, return_code, error_kind,
                error_message, invalid_json, schema_valid, hallucinated_fields,
                missing_fields, cache_hit, cache_key, prompt_hash, schema_hash,
                image_hash, output_text, output_path, stdout_path, stderr_path,
                last_message_path, metadata_json
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            (
                record.run_id,
                record.module,
                record.scenario,
                record.call_index,
                record.status,
                int(record.success),
                record.started_at,
                record.ended_at,
                record.latency_ms,
                record.retries,
                record.attempt_count,
                record.attempt_json_failures,
                record.attempt_schema_failures,
                int(record.timeout),
                int(record.rate_limited),
                int(record.usage_exhausted),
                record.return_code,
                record.error_kind,
                record.error_message,
                int(record.invalid_json),
                _nullable_bool(record.schema_valid),
                record.hallucinated_fields,
                record.missing_fields,
                int(record.cache_hit),
                record.cache_key,
                record.prompt_hash,
                record.schema_hash,
                record.image_hash,
                record.output_text,
                record.output_path,
                record.stdout_path,
                record.stderr_path,
                record.last_message_path,
                json.dumps(record.metadata, sort_keys=True),
            ),
        )
        self.update_checkpoint(record.run_id, record.module, record.scenario, record.call_index)
        self.conn.commit()

    def call_exists(self, run_id: str, module: str, scenario: str, call_index: int) -> bool:
        row = self.conn.execute(
            """
            SELECT 1 FROM call_results
            WHERE run_id = ? AND module = ? AND scenario = ? AND call_index = ?
            """,
            (run_id, module, scenario, call_index),
        ).fetchone()
        return row is not None

    def update_checkpoint(
        self, run_id: str, module: str, scenario: str, call_index: int
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO checkpoints (
                run_id, module, scenario, last_completed_index, updated_at
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(run_id, module, scenario)
            DO UPDATE SET
                last_completed_index = MAX(last_completed_index, excluded.last_completed_index),
                updated_at = excluded.updated_at
            """,
            (run_id, module, scenario, call_index, utc_now()),
        )

    def completed_count(self, run_id: str, module: str | None = None) -> int:
        if module is None:
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM call_results WHERE run_id = ?", (run_id,)
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) AS c FROM call_results WHERE run_id = ? AND module = ?",
                (run_id, module),
            ).fetchone()
        return int(row["c"])

    def get_run(self, run_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM benchmark_runs WHERE run_id = ?", (run_id,)
        ).fetchone()

    def iter_results(self, run_id: str) -> Iterable[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT * FROM call_results
            WHERE run_id = ?
            ORDER BY module, scenario, call_index
            """,
            (run_id,),
        )

    def cache_get(self, cache_key: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM cache_entries WHERE cache_key = ?", (cache_key,)
        ).fetchone()

    def cache_put(
        self,
        cache_key: str,
        prompt_hash: str,
        schema_hash: str | None,
        image_hash: str | None,
        module: str,
        status: str,
        output_text: str | None,
        output_path: str | None,
        metadata: dict[str, Any],
    ) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO cache_entries (
                cache_key, prompt_hash, schema_hash, image_hash, module,
                created_at, status, output_text, output_path, metadata_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                cache_key,
                prompt_hash,
                schema_hash,
                image_hash,
                module,
                utc_now(),
                status,
                output_text,
                output_path,
                json.dumps(metadata, sort_keys=True),
            ),
        )
        self.conn.commit()

    def _migrate(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_info (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS benchmark_runs (
                run_id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                config_json TEXT NOT NULL,
                codex_version TEXT,
                resume_count INTEGER NOT NULL DEFAULT 0,
                interrupted_count INTEGER NOT NULL DEFAULT 0,
                pid INTEGER
            );

            CREATE TABLE IF NOT EXISTS checkpoints (
                run_id TEXT NOT NULL,
                module TEXT NOT NULL,
                scenario TEXT NOT NULL,
                last_completed_index INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (run_id, module, scenario)
            );

            CREATE TABLE IF NOT EXISTS call_results (
                run_id TEXT NOT NULL,
                module TEXT NOT NULL,
                scenario TEXT NOT NULL,
                call_index INTEGER NOT NULL,
                status TEXT NOT NULL,
                success INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL,
                latency_ms REAL,
                retries INTEGER NOT NULL DEFAULT 0,
                attempt_count INTEGER NOT NULL DEFAULT 1,
                attempt_json_failures INTEGER NOT NULL DEFAULT 0,
                attempt_schema_failures INTEGER NOT NULL DEFAULT 0,
                timeout INTEGER NOT NULL DEFAULT 0,
                rate_limited INTEGER NOT NULL DEFAULT 0,
                usage_exhausted INTEGER NOT NULL DEFAULT 0,
                return_code INTEGER,
                error_kind TEXT,
                error_message TEXT,
                invalid_json INTEGER NOT NULL DEFAULT 0,
                schema_valid INTEGER,
                hallucinated_fields INTEGER NOT NULL DEFAULT 0,
                missing_fields INTEGER NOT NULL DEFAULT 0,
                cache_hit INTEGER NOT NULL DEFAULT 0,
                cache_key TEXT,
                prompt_hash TEXT,
                schema_hash TEXT,
                image_hash TEXT,
                output_text TEXT,
                output_path TEXT,
                stdout_path TEXT,
                stderr_path TEXT,
                last_message_path TEXT,
                metadata_json TEXT,
                PRIMARY KEY (run_id, module, scenario, call_index)
            );

            CREATE INDEX IF NOT EXISTS idx_call_results_run_module
                ON call_results (run_id, module, scenario);

            CREATE TABLE IF NOT EXISTS cache_entries (
                cache_key TEXT PRIMARY KEY,
                prompt_hash TEXT NOT NULL,
                schema_hash TEXT,
                image_hash TEXT,
                module TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                output_text TEXT,
                output_path TEXT,
                metadata_json TEXT
            );
            """
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO schema_info (key, value) VALUES ('version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.conn.commit()


def _nullable_bool(value: bool | None) -> int | None:
    if value is None:
        return None
    return int(value)
