# Real Codex CLI Benchmark Results

These are real `codex exec` runs captured on June 29, 2026 with `codex-cli 0.142.3`.

The benchmark measures CLI reliability and operational behavior. It does not measure model quality.

| Test | Run ID | Result | Average Latency | Max Latency | Notes |
| --- | --- | --- | --- | --- | --- |
| Stress 20 | `run_20260629_093624_7850bff5` | 20/20 success | 5.74s | 12.45s | No timeout, rate limit, or usage exhaustion |
| Structured JSON 20 | `run_20260629_093842_38b60f57` | 20/20 success | 9.20s | 17.62s | Invalid JSON 0, schema failures 0 |
| Resume 10, crash every 3 | `run_20260629_094211_a7d87fc1` | 10/10 success | 4.91s | 7.51s | 3 simulated crashes, 3 successful resumes |
| Stress 100 | `real_stress_100_20260629_0944` | 100/100 success | 6.58s | 16.28s | No slowdown observed; second half was faster |
| Structured JSON 100 | `real_structured_100_20260629_0955` | 100/100 final success | 11.51s | 35.95s | One attempt timeout recovered by retry |

## Interpretation

The 20-call gate passed for stress, structured JSON, and resume. The 100-call stress and structured tests also passed.

The strongest signal is that final structured JSON validity stayed at 100/100 in the 100-call run. The main operational concern is latency tail behavior: the structured 100-call test had one recovered attempt timeout and a max latency of 35.95 seconds.

Before treating Codex CLI as a replacement for OpenAI API in large SceneSmith or SAGE runs, the remaining tests should cover image artifact generation, cache effectiveness, and 200/500-call endurance.
