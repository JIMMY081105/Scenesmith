# Codex CLI Autonomous Pipeline Benchmark

- Run ID: `real_vlm_5_20260629_usage_guard_v2`
- Status: `complete`
- Codex version: `codex-cli 0.142.3`
- Config hash: `44e47e57a5de88ddf9d3732fbf3289a829e560cea46b6c90ba5aaa5cf9037404`
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

| module | scenario | calls | success_rate | failure_rate | avg_latency_ms | max_latency_ms | timeout_rate | attempt_timeout_count | rate_limit_count | usage_exhausted_count | invalid_json_rate | schema_failure_count | classification_wrong_rate | avg_retries | cache_hit_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| all | all | 5 | 1.0000 | 0.0000 | 16209.3598 | 23890.6736 | 0.0000 | 0 | 0 | 0 | 0.0000 | 0 | 0.0000 | 0.0000 | 0.0000 |

## Scenario Results

| module | scenario | calls | success_rate | failure_rate | avg_latency_ms | max_latency_ms | timeout_rate | attempt_timeout_count | rate_limit_count | usage_exhausted_count | invalid_json_rate | schema_failure_count | classification_wrong_rate | avg_retries | cache_hit_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| vlm | scene_image_json | 5 | 1.0000 | 0.0000 | 16209.3598 | 23890.6736 | 0.0000 | 0 | 0 | 0 | 0.0000 | 0 | 0.0000 | 0.0000 | 0.0000 |

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
- Use `--output-schema`, strict JSON parsing, retries, and schema-specific rejection logs.

## Artifacts

- calls_csv: `E:\Researches\Tsinghua papers\codex_benchmark\reports\calls.csv`
- summary_csv: `E:\Researches\Tsinghua papers\codex_benchmark\reports\summary.csv`
- success_rate_plot: `E:\Researches\Tsinghua papers\codex_benchmark\reports\success_rate_by_scenario.png`
- latency_plot: `E:\Researches\Tsinghua papers\codex_benchmark\reports\latency_by_scenario.png`
