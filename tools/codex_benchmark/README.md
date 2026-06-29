# Codex CLI Autonomous Pipeline Benchmark

This project benchmarks Codex CLI as an orchestration substrate for large autonomous pipelines. It does not benchmark model quality.

It measures:

- consecutive `codex exec` endurance
- latency drift over long call sequences
- structured JSON stability and schema failures
- JSON parsing failure rate and retries
- image artifact generation stability
- checkpoint/resume behavior after interruption
- prompt/schema/image cache effectiveness
- CSV, plot, and Markdown reporting

## Quick Smoke Test

Run the framework without making real Codex calls:

```powershell
python -m codex_benchmark.benchmark --quick --dry-run
```

If you are inside this repository root, use:

```powershell
python benchmark.py --quick --dry-run
```

This creates SQLite state under `outputs/`, CSV files under `reports/`, plots, and `reports/final_report.md`.

## Full Benchmark

```powershell
python -m codex_benchmark.benchmark --config codex_benchmark/config.yaml
```

From this repository root:

```powershell
python benchmark.py --config config.yaml
```

The default stress levels run 10, 50, 100, 200, 500, 1000, and 2000 consecutive calls. This is intentionally large and may consume substantial Codex usage.

## Resume

Every completed call is committed to SQLite. To resume an interrupted run:

```powershell
python -m codex_benchmark.benchmark --config codex_benchmark/config.yaml --resume --run-id <RUN_ID>
```

To test automatic restart behavior:

```powershell
python -m codex_benchmark.benchmark --config codex_benchmark/config.yaml --modules resume --resume-total-calls 10 --simulate-crash-every 2 --auto-restart
```

The supervisor restarts the worker until the resume module reaches `resume.total_calls`.

## Module Selection

```powershell
python -m codex_benchmark.benchmark --modules stress,structured
python -m codex_benchmark.benchmark --modules stress --stress-calls 20
python -m codex_benchmark.benchmark --modules structured --structured-calls 20
python -m codex_benchmark.benchmark --modules image
python -m codex_benchmark.benchmark --modules cache
```

Convenience scripts:

```powershell
.\scripts\run_smoke.ps1
.\scripts\run_real_small.ps1
.\scripts\run_real_100.ps1
```

## Tests

```powershell
pip install -r requirements.txt pytest
pytest
```

## Real Results

Real benchmark summaries are committed under `reports/` and documented in
`docs/REAL_BENCHMARK_RESULTS.md`.

## Outputs

- `outputs/benchmark.sqlite3`: run metadata, checkpoints, call results, cache entries
- `outputs/artifacts/<run_id>/`: stdout, stderr, and final messages per call
- `outputs/images/<run_id>/`: image artifacts produced by the image benchmark
- `reports/calls.csv`: one row per logical benchmark call
- `reports/summary.csv`: aggregate metrics by module and scenario
- `reports/final_report.md`: automated replacement assessment for SceneSmith, SAGE, robotics workflows, and scene generation pipelines

## Notes

- The image module asks Codex to create image artifacts in the benchmark workspace. SVG is the default because it is dependency-free and easy to validate.
- Cache keys include prompt hash, schema hash, image-input hash, and the Codex runner fingerprint.
- The benchmark uses `codex exec --output-schema` for structured modules and still independently validates the final message.
- `Ctrl+C` marks the run interrupted without deleting completed results.
