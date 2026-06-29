from __future__ import annotations

import json
from pathlib import Path

from codex_benchmark.benchmark import (
    count_schema_field_issues,
    load_vlm_manifest,
    validate_output,
    validate_vlm_classification,
    verify_image,
)


def test_validate_output_accepts_schema_compliant_json() -> None:
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "structured_output.schema.json"
    payload = {
        "benchmark_id": "unit",
        "call_index": 0,
        "scenario": "schema_json",
        "scene_category": "indoor_scene",
        "objects": [{"name": "chair", "count": 1, "role": "asset"}],
        "quality_flags": {
            "deterministic": True,
            "schema_checked": True,
            "requires_human_review": False,
        },
        "confidence": 0.9,
    }

    result = validate_output(json.dumps(payload), str(schema_path))

    assert result["invalid_json"] is False
    assert result["schema_valid"] is True
    assert result["hallucinated_fields"] == 0
    assert result["missing_fields"] == 0


def test_validate_output_rejects_invalid_json() -> None:
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "structured_output.schema.json"

    result = validate_output("{not json", str(schema_path))

    assert result["invalid_json"] is True
    assert result["schema_valid"] is False


def test_count_schema_field_issues_detects_extra_and_missing_fields() -> None:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "count"],
        "properties": {"name": {"type": "string"}, "count": {"type": "integer"}},
    }

    hallucinated, missing = count_schema_field_issues({"name": "box", "extra": True}, schema)

    assert hallucinated == 1
    assert missing == 1


def test_verify_image_accepts_valid_svg(tmp_path: Path) -> None:
    svg = tmp_path / "image.svg"
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64">'
        '<rect width="64" height="64" fill="black"/></svg>',
        encoding="utf-8",
    )

    result = verify_image(str(svg), min_bytes=20)

    assert result["valid"] is True
    assert result["image_hash"]


def test_vlm_classification_validation_counts_wrong_scene_type() -> None:
    output = json.dumps(
        {
            "scene_type": "classroom",
            "main_objects": ["desk", "chair"],
            "is_simulation_ready": True,
            "collision_risk": "low",
            "confidence": 0.8,
        }
    )
    expected = {
        "path": "image.png",
        "expected_scene_type": "office",
        "expected_main_objects": ["desk"],
    }

    result = validate_vlm_classification(output, expected)

    assert result["classification_wrong"] is True
    assert result["object_overlap"] == 1


def test_load_vlm_manifest_resolves_relative_paths() -> None:
    manifest_path = Path(__file__).resolve().parents[1] / "manifests" / "scenesmith_vlm_images.json"
    dataset_root = Path(__file__).resolve().parents[2] / "scenesmith-main"

    items = load_vlm_manifest(str(manifest_path), str(dataset_root))

    assert items
    assert Path(items[0]["path"]).is_absolute()
    assert "expected_scene_type" in items[0]
