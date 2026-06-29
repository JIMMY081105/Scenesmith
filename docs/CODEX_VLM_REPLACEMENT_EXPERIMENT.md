# Codex VLM Replacement Experiment

This experiment is the first SceneSmith replacement stage. It does not benchmark
model quality and does not run image generation.

## Scope

Covered:

- `VLMService.create_completion()` can use a Codex CLI backend.
- The OpenAI API client is not constructed when `backend="codex"`.
- The real `AssetRouter.analyze_request()` structured JSON prompt can be routed
  through the same `VLMService` interface.
- Parsed router output can reach the HSSD/existing-asset acquisition path.

Not covered:

- Full OpenAI Agents SDK planner/designer/critic replacement.
- Blender rendering.
- Image artifact generation.
- Large Codex benchmark calls.

## Command

Run this in a SceneSmith Python 3.11 environment where `codex` is installed:

```bash
unset OPENAI_API_KEY
export SCENESMITH_VLM_BACKEND=codex
export SCENESMITH_CODEX_SANDBOX=read-only
export SCENESMITH_CODEX_APPROVAL_POLICY=never

python scripts/codex_vlm_replacement_smoke.py \
  --description "work desk" \
  --dimensions "1.2,0.6,0.75"
```

Expected result:

- `openai_api_key_present_after_disable` is `false`.
- `vlm_backend` is `codex`.
- At least one parsed router item is returned.
- `hssd_handoff.asset_source` is `hssd`.
- `next_stage_reached` is `hssd_existing_asset_candidate_selected`.

The script writes a reproducible summary under
`outputs/codex_vlm_replacement_smoke/<timestamp>/summary.json`.

## Observed Result

Run date: June 29, 2026

Command used in this Windows checkout through WSL Python and the native Windows
Codex CLI:

```bash
unset OPENAI_API_KEY
export PYTHONPATH=.
export SCENESMITH_VLM_BACKEND=codex
export SCENESMITH_CODEX_EXECUTABLE=/mnt/c/Users/User/.vscode/extensions/openai.chatgpt-26.623.42026-win32-x64/bin/windows-x86_64/codex.exe
export SCENESMITH_CODEX_SANDBOX=read-only
export SCENESMITH_CODEX_APPROVAL_POLICY=never

python scripts/codex_vlm_replacement_smoke.py \
  --description "work desk" \
  --dimensions "1.2,0.6,0.75"
```

Result:

```json
{
  "status": "success",
  "openai_api_key_present_after_disable": false,
  "vlm_backend": "codex",
  "parsed_items": [
    {
      "description": "work desk",
      "short_name": "desk",
      "object_type": "furniture",
      "strategies": ["generated"],
      "dimensions": [1.2, 0.6, 0.75]
    }
  ],
  "hssd_handoff": {
    "asset_source": "hssd",
    "hssd_id": "local_smoke_hssd_candidate",
    "geometry_path": "tests/test_data/realistic_scene/generated_assets/sdf/work_desk_1761578426/work_desk.gltf"
  },
  "image_generation": "off",
  "next_stage_reached": "hssd_existing_asset_candidate_selected"
}
```

Interpretation:

The first real replacement stage passed. Codex CLI replaced the structured
`VLMService` OpenAI call for asset-router analysis, with no `OPENAI_API_KEY`, and
the result reached the existing-asset HSSD path. This does not yet replace the
OpenAI Agents SDK planner/designer/critic loop.
