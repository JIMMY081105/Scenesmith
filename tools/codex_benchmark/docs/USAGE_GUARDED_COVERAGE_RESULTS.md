# Usage-Guarded Codex Coverage Results

Date: June 29, 2026

Codex CLI: `codex-cli 0.142.3`

This pass was designed to cover the remaining benchmark surfaces without burning through a large usage budget. It intentionally avoided 200+ stress calls and 20/100 image-artifact runs after a Windows sandbox helper failure appeared.

## Coverage Summary

| Area | Run ID | Result | Decision |
| --- | --- | --- | --- |
| Stress 20 | `run_20260629_093624_7850bff5` | 20/20 success | Passed small gate |
| Structured JSON 20 | `run_20260629_093842_38b60f57` | 20/20 success | Passed small gate |
| Resume 10, crash every 3 | `run_20260629_094211_a7d87fc1` | 10/10 success, 3 resumes | Passed small gate |
| Stress 100 | `real_stress_100_20260629_0944` | 100/100 success | Passed medium gate |
| Structured JSON 100 | `real_structured_100_20260629_0955` | 100/100 final success | Passed medium gate with one recovered timeout attempt |
| VLM image input 5 | `real_vlm_5_20260629_usage_guard_v2` | 5/5 success | Passed smoke gate |
| Image artifact 5 | `real_image_5_20260629_usage_guard` | 1 completed, run interrupted | Blocked by native Windows sandbox helper modal |

## VLM Image Input

Command:

```powershell
python benchmark.py --config config.yaml --modules vlm --vlm-count 5 --run-id real_vlm_5_20260629_usage_guard_v2
```

Observed:

- Calls: 5
- Success rate: 100%
- Invalid JSON: 0
- Schema failures: 0
- Classification wrong count: 0
- Average latency: 16.21 seconds
- Max latency: 23.89 seconds
- Timeout, rate limit, usage exhaustion: 0
- Manifest availability: 15 local SceneSmith/test/media images

Interpretation:

Codex CLI image input works for a small SceneSmith-style VLM inspection gate. This does not yet prove the requested 50/50 target because only 5 calls were run under the usage guard and the current local manifest has 15 available images, not 50.

## Image Artifact Generation

Command:

```powershell
python benchmark.py --config config.yaml --modules image --image-count 5 --run-id real_image_5_20260629_usage_guard
```

Observed:

- Completed artifacts: 1
- Completed artifact validity: valid SVG, schema-valid final JSON
- Completed artifact latency: 147.05 seconds
- Completed artifact retries: 1
- Attempt JSON/schema failures before retry: 1
- Run status: interrupted
- Failure mode: second image call stalled after the native Windows sandbox setup helper showed `The specified module could not be found.`

Interpretation:

Image artifact generation-on is not currently safe to scale on this native Windows setup. The blocker is operational: Codex attempted a workspace-write sandboxed command path and the Windows sandbox helper failed interactively. This is not evidence of model-quality failure, API usage exhaustion, or SceneSmith pipeline failure.

## Windows Sandbox Note

The Codex manual states that native Windows Codex uses the Windows sandbox in PowerShell, with `elevated` and `unelevated` modes, and recommends WSL2 when native Windows sandbox modes do not meet the workflow needs. The local `codex doctor` check reported Codex itself as installed and authenticated, so the practical issue is specific to the native sandbox helper path used during the image artifact run.

## Usage Decision

Do not run `--image-count 20`, `--image-count 100`, `--stress-calls 200`, `--stress-calls 500`, `--stress-calls 1000`, or `--stress-calls 2000` until the image sandbox helper issue is fixed or the benchmark is moved to WSL2/Linux.

Recommended next usage-efficient sequence:

1. Update Codex CLI from `0.142.3` to the available `0.142.4`.
2. Restart VS Code or start a fresh terminal so the IDE-bundled CLI is not holding stale helper binaries.
3. Run one image smoke call only:

```powershell
python benchmark.py --config config.yaml --modules image --image-count 1 --run-id real_image_1_after_sandbox_fix
```

4. If that succeeds without a modal, run all 15 currently available VLM images:

```powershell
python benchmark.py --config config.yaml --modules vlm --vlm-count 15 --run-id real_vlm_15_after_sandbox_fix
```

5. Only then spend usage on `--stress-calls 200`.

## Current Replacement Assessment

Codex CLI is promising for structured JSON, resume/checkpointing, caching architecture, and small VLM-style image inspection. It is not yet proven as a full OpenAI API replacement for unattended SceneSmith/SAGE production pipelines on this native Windows environment because image artifact generation and large endurance ceilings remain unproven.

For SceneSmith specifically, the stronger near-term path is image generation off: use HSSD/existing assets and use Codex only for structured planning, validation, routing, VLM inspection, and checkpointed orchestration.
