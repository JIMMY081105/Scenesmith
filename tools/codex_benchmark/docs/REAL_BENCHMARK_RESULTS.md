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
| VLM image input 5 | `real_vlm_5_20260629_usage_guard_v2` | 5/5 success | 16.21s | 23.89s | Invalid JSON 0, schema failures 0, wrong classification 0 |
| Image artifact 5 | `real_image_5_20260629_usage_guard` | 1 completed, interrupted | 147.05s | 147.05s | First SVG artifact valid after retry; second call blocked by native Windows sandbox helper modal |

## Interpretation

The 20-call gate passed for stress, structured JSON, and resume. The 100-call stress and structured tests also passed.

The strongest signal is that final structured JSON validity stayed at 100/100 in the 100-call run. The main operational concern is latency tail behavior: the structured 100-call test had one recovered attempt timeout and a max latency of 35.95 seconds.

The usage-guarded VLM smoke test proves that Codex CLI can accept local SceneSmith-style images and return schema-valid JSON for a small sample. It does not yet prove the requested 50/50 VLM target.

The image-artifact test should not be scaled on the current native Windows setup until the sandbox helper issue is fixed or the benchmark is moved to WSL2/Linux. See `docs/USAGE_GUARDED_COVERAGE_RESULTS.md` for the guarded execution plan and blocker details.

Before treating Codex CLI as a replacement for OpenAI API in large SceneSmith or SAGE runs, the remaining tests should cover all available VLM manifest images, cache effectiveness, one clean post-fix image smoke call, and 200/500-call endurance.
