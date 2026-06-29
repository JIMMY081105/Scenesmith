"""One-call SceneSmith Codex VLM replacement smoke test.

This script proves the first replacement stage:

1. Disable OPENAI_API_KEY in-process.
2. Route VLMService through Codex CLI.
3. Run the real AssetRouter structured JSON prompt.
4. Parse the normal AnalysisResult.
5. Hand the parsed item to the HSSD/existing-asset path with image generation off.

It intentionally does not run the full OpenAI Agents SDK scene pipeline, Blender,
image generation, or large benchmarks.
"""

from __future__ import annotations

import argparse
import json
import os
import time

from pathlib import Path

from omegaconf import OmegaConf

from scenesmith.agent_utils.asset_router import AssetRouter
from scenesmith.agent_utils.hssd_retrieval_server.dataclasses import (
    HssdRetrievalResult,
    HssdRetrievalServerResponse,
)
from scenesmith.agent_utils.room import AgentType
from scenesmith.agent_utils.vlm_service import VLMService


class LocalHssdClient:
    """Tiny HSSD client stand-in backed by an existing local mesh."""

    def __init__(self, mesh_path: Path) -> None:
        self.mesh_path = mesh_path.resolve()

    def retrieve_objects(self, requests):
        for index, request in enumerate(requests):
            result = HssdRetrievalResult(
                mesh_path=str(self.mesh_path),
                hssd_id="local_smoke_hssd_candidate",
                object_name=request.object_description,
                similarity_score=1.0,
                size=tuple(request.desired_dimensions or (1.2, 0.6, 0.75)),
                category=request.object_type,
            )
            yield index, HssdRetrievalServerResponse(
                results=[result],
                query_description=request.object_description,
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one Codex-backed SceneSmith VLM replacement smoke test."
    )
    parser.add_argument("--description", default="work desk")
    parser.add_argument("--dimensions", default="1.2,0.6,0.75")
    parser.add_argument(
        "--existing-mesh",
        default=(
            "tests/test_data/realistic_scene/generated_assets/sdf/"
            "work_desk_1761578426/work_desk.gltf"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default="outputs/codex_vlm_replacement_smoke",
    )
    parser.add_argument("--model", default="gpt-5.2")
    return parser.parse_args()


def load_smoke_config(model: str):
    base = OmegaConf.load("configurations/furniture_agent/base_furniture_agent.yaml")
    overrides = OmegaConf.create(
        {
            "openai": {
                "model": model,
                "vision_detail": "low",
                "reasoning_effort": {"asset_analysis": "low"},
                "verbosity": {"asset_analysis": "low"},
            },
            "asset_manager": {
                "general_asset_source": "hssd",
                "router": {
                    "analysis_max_retries": 1,
                    "strategies": {
                        "generated": {"enabled": True, "max_retries": 0},
                        "articulated": {"enabled": False},
                        "thin_covering": {"enabled": False},
                    },
                },
                "image_generation": {"backend": "disabled"},
            },
        }
    )
    return OmegaConf.merge(base, overrides)


def main() -> int:
    args = parse_args()
    dimensions = [float(value.strip()) for value in args.dimensions.split(",")]
    if len(dimensions) != 3:
        raise ValueError("--dimensions must contain width,depth,height")

    # Prove this path does not depend on the OpenAI API key.
    os.environ.pop("OPENAI_API_KEY", None)
    os.environ["SCENESMITH_VLM_BACKEND"] = "codex"
    os.environ.setdefault("SCENESMITH_CODEX_SANDBOX", "read-only")
    os.environ.setdefault("SCENESMITH_CODEX_APPROVAL_POLICY", "never")

    output_root = Path(args.output_dir) / time.strftime("%Y%m%d_%H%M%S")
    geometry_dir = output_root / "geometry"
    debug_dir = output_root / "debug"
    geometry_dir.mkdir(parents=True, exist_ok=True)
    debug_dir.mkdir(parents=True, exist_ok=True)

    existing_mesh = Path(args.existing_mesh)
    if not existing_mesh.exists():
        raise FileNotFoundError(f"Existing mesh not found: {existing_mesh}")

    cfg = load_smoke_config(args.model)
    vlm_service = VLMService(backend="codex")
    router = AssetRouter(
        agent_type=AgentType.FURNITURE,
        vlm_service=vlm_service,
        cfg=cfg,
        blender_server=None,
    )

    analysis = router.analyze_request(args.description, dimensions)
    if analysis.error:
        raise RuntimeError(f"Codex router analysis failed: {analysis.error}")
    if not analysis.items:
        raise RuntimeError("Codex router analysis returned no items")

    item = analysis.items[0]
    if "generated" not in item.strategies:
        raise RuntimeError(
            f"Expected generated/HSSD-compatible strategy, got {item.strategies}"
        )

    hssd_client = LocalHssdClient(mesh_path=existing_mesh)
    geometry = router.generate_with_validation(
        item=item,
        geometry_client=None,
        image_generator=None,
        images_dir=None,
        geometry_dir=geometry_dir,
        debug_dir=debug_dir,
        hssd_client=hssd_client,
        objaverse_client=None,
        articulated_client=None,
        materials_client=None,
        scene_id="codex_smoke_scene_000",
    )
    if geometry is None:
        raise RuntimeError("HSSD/existing-asset handoff returned no geometry")

    summary = {
        "status": "success",
        "openai_api_key_present_after_disable": bool(os.getenv("OPENAI_API_KEY")),
        "vlm_backend": vlm_service.backend,
        "description": args.description,
        "dimensions": dimensions,
        "parsed_items": [
            {
                "description": parsed_item.description,
                "short_name": parsed_item.short_name,
                "object_type": parsed_item.object_type.value,
                "strategies": parsed_item.strategies,
                "dimensions": parsed_item.dimensions,
            }
            for parsed_item in analysis.items
        ],
        "hssd_handoff": {
            "asset_source": geometry.asset_source,
            "hssd_id": geometry.hssd_id,
            "geometry_path": str(geometry.geometry_path),
        },
        "image_generation": "off",
        "next_stage_reached": "hssd_existing_asset_candidate_selected",
    }
    summary_path = output_root / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(f"Summary written to {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
