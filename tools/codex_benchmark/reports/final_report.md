# Codex CLI Autonomous Pipeline Benchmark

- Run ID: `real_structured_100_20260629_0955`
- Status: `complete`
- Codex version: `codex-cli 0.142.3`
- Config hash: `1c5100f826bc2b21a35cbf4dda0fa75a6e8a06fc735c539a0c20505b11dc07d5`
- Resume count: `0`
- Interrupted count: `0`

## Executive Decision

- SceneSmith replacement: **No, not for unattended large pipelines under this run**
- SAGE replacement: **No, not for unattended large pipelines under this run**
- Large autonomous pipelines: **No, not for unattended large pipelines under this run**
- Large robotics workflows: **No, not for unattended large pipelines under this run**
- Large scene generation pipelines: **No, not for unattended large pipelines under this run**

These verdicts assess CLI reliability as an orchestration substrate. They do not measure model quality.

## Overall Results

| module | scenario | calls | success_rate | failure_rate | avg_latency_ms | max_latency_ms | timeout_rate | attempt_timeout_count | rate_limit_count | usage_exhausted_count | invalid_json_rate | schema_failure_count | avg_retries | cache_hit_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| all | all | 100 | 1.0000 | 0.0000 | 11509.3874 | 35946.4855 | 0.0000 | 1 | 0 | 0 | 0.0000 | 0 | 0.0100 | 0.0000 |

## Scenario Results

| module | scenario | calls | success_rate | failure_rate | avg_latency_ms | max_latency_ms | timeout_rate | attempt_timeout_count | rate_limit_count | usage_exhausted_count | invalid_json_rate | schema_failure_count | avg_retries | cache_hit_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| structured | schema_json | 100 | 1.0000 | 0.0000 | 11509.3874 | 35946.4855 | 0.0000 | 1 | 0 | 0 | 0.0000 | 0 | 0.0100 | 0.0000 |

## Practical Limits

- Maximum stable stress level observed: `0` consecutive calls
- Estimated practical project size: `not established` Codex calls
- Estimated maximum continuous runtime: `not established`
- Primary bottlenecks: no stable stress level

## Engineering Recommendations

- Keep every pipeline step idempotent and keyed by prompt, schema, image input, and Codex configuration hashes.
- Commit SQLite checkpoints after every Codex call; never use only in-memory queues for long jobs.
- Shard large projects into bounded call batches and resume by run id.
- Do not run thousand-call autonomous jobs without external scheduling and backoff.

## Artifacts

- calls_csv: `E:\Researches\Tsinghua papers\codex_benchmark\reports\calls.csv`
- summary_csv: `E:\Researches\Tsinghua papers\codex_benchmark\reports\summary.csv`
- success_rate_plot: `E:\Researches\Tsinghua papers\codex_benchmark\reports\success_rate_by_scenario.png`
- latency_plot: `E:\Researches\Tsinghua papers\codex_benchmark\reports\latency_by_scenario.png`
