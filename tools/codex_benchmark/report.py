"""Markdown final report generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import BenchmarkConfig


def write_markdown_report(
    summary: dict[str, Any],
    config: BenchmarkConfig,
    artifact_paths: dict[str, str],
) -> str:
    reports_dir = Path(config.paths.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / config.reporting.markdown_report

    decision = assess_replacement(summary, config)
    run = summary["run"]
    overall = summary["overall"]

    lines = [
        f"# Codex CLI Autonomous Pipeline Benchmark",
        "",
        f"- Run ID: `{run.get('run_id', 'unknown')}`",
        f"- Status: `{run.get('status', 'unknown')}`",
        f"- Codex version: `{run.get('codex_version', 'unknown')}`",
        f"- Config hash: `{run.get('config_hash', 'unknown')}`",
        f"- Resume count: `{run.get('resume_count', 0)}`",
        f"- Interrupted count: `{run.get('interrupted_count', 0)}`",
        "",
        "## Executive Decision",
        "",
        f"- SceneSmith replacement: **{decision['scenesmith']}**",
        f"- SAGE replacement: **{decision['sage']}**",
        f"- Large autonomous pipelines: **{decision['large_autonomous_pipelines']}**",
        f"- Large robotics workflows: **{decision['large_robotics_workflows']}**",
        f"- Large scene generation pipelines: **{decision['large_scene_generation_pipelines']}**",
        "",
        "These verdicts assess CLI reliability as an orchestration substrate. They do not measure model quality.",
        "",
        "## Overall Results",
        "",
        _summary_table([overall]),
        "",
        "## Scenario Results",
        "",
        _summary_table(summary["scenarios"]),
        "",
        "## Practical Limits",
        "",
        f"- Maximum stable stress level observed: `{decision['max_stable_stress_calls']}` consecutive calls",
        f"- Estimated practical project size: `{decision['maximum_practical_project_size']}` Codex calls",
        f"- Estimated maximum continuous runtime: `{decision['maximum_practical_runtime']}`",
        f"- Primary bottlenecks: {decision['major_bottlenecks']}",
        "",
        "## Engineering Recommendations",
        "",
    ]
    lines.extend([f"- {item}" for item in decision["recommendations"]])
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
        ]
    )
    for label, artifact_path in artifact_paths.items():
        lines.append(f"- {label}: `{artifact_path}`")
    lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return str(path)


def assess_replacement(summary: dict[str, Any], config: BenchmarkConfig) -> dict[str, Any]:
    scenarios = summary["scenarios"]
    overall = summary["overall"]
    by_module = _group_by_module(scenarios)

    stress_ok_level = _max_stable_stress(scenarios, config.reporting.success_threshold)
    structured = _combine(by_module.get("structured", []))
    image = _combine(by_module.get("image", []))
    cache = _combine(by_module.get("cache", []))
    resume = _combine(by_module.get("resume", []))

    stable_json = (
        structured["calls"] > 0
        and structured["invalid_json_rate"] <= config.reporting.json_failure_threshold
        and structured["schema_failure_count"] == 0
        and structured["hallucinated_fields"] == 0
        and structured["missing_fields"] == 0
    )
    image_stable = image["calls"] == 0 or image["success_rate"] >= config.reporting.success_threshold
    cache_effective = cache["calls"] == 0 or cache["cache_hit_rate"] >= config.reporting.cache_hit_threshold
    resume_effective = resume["calls"] == 0 or resume["success_rate"] >= config.reporting.success_threshold
    no_limitations = (
        overall["timeout_rate"] <= config.reporting.timeout_threshold
        and overall["rate_limit_count"] == 0
        and overall["usage_exhausted_count"] == 0
    )

    strong = (
        stress_ok_level >= 1000
        and stable_json
        and image_stable
        and cache_effective
        and resume_effective
        and no_limitations
    )
    moderate = (
        stress_ok_level >= 200
        and stable_json
        and cache_effective
        and resume_effective
        and no_limitations
    )

    if strong:
        base_verdict = "Yes, with normal production guardrails"
    elif moderate:
        base_verdict = "Conditional; suitable with checkpointing, caching, and operator limits"
    else:
        base_verdict = "No, not for unattended large pipelines under this run"

    scene_generation = base_verdict
    if image["calls"] > 0 and not image_stable:
        scene_generation = "No, image artifact generation was not stable enough"

    bottlenecks = _bottlenecks(overall, structured, image, cache, resume, stress_ok_level)
    project_size = _estimate_project_size(stress_ok_level)
    runtime = _estimate_runtime(stress_ok_level, scenarios)

    return {
        "scenesmith": scene_generation,
        "sage": base_verdict,
        "large_autonomous_pipelines": base_verdict,
        "large_robotics_workflows": base_verdict,
        "large_scene_generation_pipelines": scene_generation,
        "max_stable_stress_calls": stress_ok_level,
        "maximum_practical_project_size": project_size,
        "maximum_practical_runtime": runtime,
        "major_bottlenecks": bottlenecks,
        "recommendations": _recommendations(
            stable_json=stable_json,
            image_stable=image_stable,
            cache_effective=cache_effective,
            resume_effective=resume_effective,
            no_limitations=no_limitations,
            stress_ok_level=stress_ok_level,
        ),
    }


def _summary_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No data._"
    headers = [
        "module",
        "scenario",
        "calls",
        "success_rate",
        "failure_rate",
        "avg_latency_ms",
        "max_latency_ms",
        "timeout_rate",
        "attempt_timeout_count",
        "rate_limit_count",
        "usage_exhausted_count",
        "invalid_json_rate",
        "schema_failure_count",
        "classification_wrong_rate",
        "avg_retries",
        "cache_hit_rate",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_format_cell(row.get(header, "")) for header in headers) + " |")
    return "\n".join(lines)


def _format_cell(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _group_by_module(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["module"], []).append(row)
    return grouped


def _combine(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "calls": 0,
            "success_rate": 0.0,
            "invalid_json_rate": 0.0,
            "schema_failure_count": 0,
            "hallucinated_fields": 0,
            "missing_fields": 0,
            "cache_hit_rate": 0.0,
        }
    calls = sum(int(row["calls"]) for row in rows)
    successes = sum(int(row["successes"]) for row in rows)
    return {
        "calls": calls,
        "success_rate": successes / calls if calls else 0.0,
        "invalid_json_rate": _weighted(rows, "invalid_json_rate", "calls"),
        "schema_failure_count": sum(int(row["schema_failure_count"]) for row in rows),
        "hallucinated_fields": sum(int(row["hallucinated_fields"]) for row in rows),
        "missing_fields": sum(int(row["missing_fields"]) for row in rows),
        "cache_hit_rate": _weighted(rows, "cache_hit_rate", "calls"),
    }


def _weighted(rows: list[dict[str, Any]], value_key: str, weight_key: str) -> float:
    total_weight = sum(float(row[weight_key]) for row in rows)
    if total_weight == 0:
        return 0.0
    return sum(float(row[value_key]) * float(row[weight_key]) for row in rows) / total_weight


def _max_stable_stress(rows: list[dict[str, Any]], threshold: float) -> int:
    levels = []
    for row in rows:
        if row["module"] != "stress":
            continue
        try:
            count = int(str(row["scenario"]).replace("calls_", ""))
        except ValueError:
            continue
        if (
            row["success_rate"] >= threshold
            and row["rate_limit_count"] == 0
            and row["usage_exhausted_count"] == 0
        ):
            levels.append(count)
    return max(levels) if levels else 0


def _estimate_project_size(stress_ok_level: int) -> str:
    if stress_ok_level >= 2000:
        return "2000+ observed; larger projects should still shard by checkpointed stage"
    if stress_ok_level >= 1000:
        return "1000-2000 calls per uninterrupted shard"
    if stress_ok_level >= 200:
        return "200-1000 calls per shard"
    if stress_ok_level > 0:
        return f"up to about {stress_ok_level} consecutive calls before sharding"
    return "not established"


def _estimate_runtime(stress_ok_level: int, scenarios: list[dict[str, Any]]) -> str:
    stress_rows = [row for row in scenarios if row["module"] == "stress" and row["calls"] > 0]
    if not stress_rows or stress_ok_level == 0:
        return "not established"
    matching = [
        row
        for row in stress_rows
        if str(row["scenario"]) == f"calls_{stress_ok_level}"
    ]
    row = matching[0] if matching else max(stress_rows, key=lambda item: item["calls"])
    seconds = (float(row["avg_latency_ms"]) * stress_ok_level) / 1000
    hours = seconds / 3600
    if hours >= 1:
        return f"{hours:.2f} hours observed-equivalent at average stress latency"
    return f"{seconds / 60:.2f} minutes observed-equivalent at average stress latency"


def _bottlenecks(
    overall: dict[str, Any],
    structured: dict[str, Any],
    image: dict[str, Any],
    cache: dict[str, Any],
    resume: dict[str, Any],
    stress_ok_level: int,
) -> str:
    items = []
    if stress_ok_level == 0:
        items.append("no stable stress level")
    if overall["timeout_rate"] > 0:
        items.append("timeouts")
    if overall["rate_limit_count"] > 0:
        items.append("rate limiting")
    if overall["usage_exhausted_count"] > 0:
        items.append("usage exhaustion")
    if structured["calls"] and structured["invalid_json_rate"] > 0:
        items.append("invalid JSON")
    if structured["schema_failure_count"] > 0:
        items.append("schema failures")
    if image["calls"] and image["success_rate"] < 1:
        items.append("image artifact failures")
    if cache["calls"] and cache["cache_hit_rate"] < 0.70:
        items.append("low cache hit ratio")
    if resume["calls"] and resume["success_rate"] < 1:
        items.append("resume failures")
    return ", ".join(items) if items else "none observed"


def _recommendations(
    *,
    stable_json: bool,
    image_stable: bool,
    cache_effective: bool,
    resume_effective: bool,
    no_limitations: bool,
    stress_ok_level: int,
) -> list[str]:
    recommendations = [
        "Keep every pipeline step idempotent and keyed by prompt, schema, image input, and Codex configuration hashes.",
        "Commit SQLite checkpoints after every Codex call; never use only in-memory queues for long jobs.",
        "Shard large projects into bounded call batches and resume by run id.",
    ]
    if stress_ok_level < 1000:
        recommendations.append("Do not run thousand-call autonomous jobs without external scheduling and backoff.")
    if not stable_json:
        recommendations.append("Use `--output-schema`, strict JSON parsing, retries, and schema-specific rejection logs.")
    if not image_stable:
        recommendations.append("Treat image artifacts as first-class outputs and verify existence, size, format, and hash before advancing.")
    if not cache_effective:
        recommendations.append("Normalize prompts and schemas before hashing so repeated work is actually eliminated.")
    if not resume_effective:
        recommendations.append("Run the resume test with simulated crashes before using the CLI for unattended workflows.")
    if not no_limitations:
        recommendations.append("Add exponential backoff and account-limit detection around `codex exec` invocations.")
    return recommendations
