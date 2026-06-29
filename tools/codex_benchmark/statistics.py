"""Aggregation, CSV export, and plot generation."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from .checkpoint import CheckpointStore
from .config import BenchmarkConfig


def compute_summary(store: CheckpointStore, run_id: str) -> dict[str, Any]:
    rows = [dict(row) for row in store.iter_results(run_id)]
    run = store.get_run(run_id)
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["module"], row["scenario"])].append(row)

    scenarios = []
    for (module, scenario), group in sorted(grouped.items()):
        scenarios.append(_summarize_group(module, scenario, group))

    overall = _summarize_group("all", "all", rows) if rows else _empty_summary("all", "all")
    return {
        "run": dict(run) if run else {},
        "overall": overall,
        "scenarios": scenarios,
        "rows": rows,
    }


def write_csv_reports(summary: dict[str, Any], config: BenchmarkConfig) -> dict[str, str]:
    reports_dir = Path(config.paths.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    calls_path = reports_dir / config.reporting.calls_csv
    summary_path = reports_dir / config.reporting.summary_csv

    rows = summary["rows"]
    if rows:
        fieldnames = list(rows[0].keys())
        with calls_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    else:
        calls_path.write_text("", encoding="utf-8")

    scenario_rows = summary["scenarios"]
    if scenario_rows:
        fieldnames = list(scenario_rows[0].keys())
        with summary_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(scenario_rows)
    else:
        summary_path.write_text("", encoding="utf-8")

    return {"calls_csv": str(calls_path), "summary_csv": str(summary_path)}


def generate_plots(summary: dict[str, Any], config: BenchmarkConfig) -> dict[str, str]:
    if not config.reporting.generate_plots:
        return {}

    reports_dir = Path(config.paths.reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    scenarios = summary["scenarios"]
    if not scenarios:
        return {}

    paths: dict[str, str] = {}
    try:
        import matplotlib.pyplot as plt  # type: ignore

        labels = [f"{row['module']}:{row['scenario']}" for row in scenarios]
        success_rates = [row["success_rate"] * 100 for row in scenarios]
        avg_latencies = [row["avg_latency_ms"] for row in scenarios]

        success_path = reports_dir / "success_rate_by_scenario.png"
        plt.figure(figsize=(max(8, len(labels) * 0.6), 4))
        plt.bar(labels, success_rates)
        plt.ylabel("Success rate (%)")
        plt.xticks(rotation=75, ha="right")
        plt.tight_layout()
        plt.savefig(success_path, dpi=160)
        plt.close()
        paths["success_rate_plot"] = str(success_path)

        latency_path = reports_dir / "latency_by_scenario.png"
        plt.figure(figsize=(max(8, len(labels) * 0.6), 4))
        plt.bar(labels, avg_latencies)
        plt.ylabel("Average latency (ms)")
        plt.xticks(rotation=75, ha="right")
        plt.tight_layout()
        plt.savefig(latency_path, dpi=160)
        plt.close()
        paths["latency_plot"] = str(latency_path)
    except Exception:
        paths.update(_generate_svg_fallback(scenarios, reports_dir))

    return paths


def _summarize_group(module: str, scenario: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    calls = len(rows)
    if calls == 0:
        return _empty_summary(module, scenario)

    successes = sum(int(row["success"]) for row in rows)
    failures = calls - successes
    cache_hits = sum(int(row["cache_hit"]) for row in rows)
    actual_latencies = [
        float(row["latency_ms"])
        for row in rows
        if row["latency_ms"] is not None and not int(row["cache_hit"])
    ]
    retry_values = [int(row["retries"]) for row in rows]
    attempt_counts = [int(row["attempt_count"]) for row in rows]
    attempt_json_failures = sum(int(row["attempt_json_failures"]) for row in rows)
    attempt_schema_failures = sum(int(row["attempt_schema_failures"]) for row in rows)
    attempt_timeouts = sum(_attempt_timeout_count(row) for row in rows)
    total_attempts = sum(attempt_counts) or calls

    return {
        "module": module,
        "scenario": scenario,
        "calls": calls,
        "successes": successes,
        "failures": failures,
        "success_rate": successes / calls,
        "failure_rate": failures / calls,
        "avg_latency_ms": _mean(actual_latencies),
        "max_latency_ms": max(actual_latencies) if actual_latencies else 0.0,
        "timeout_count": sum(int(row["timeout"]) for row in rows),
        "timeout_rate": sum(int(row["timeout"]) for row in rows) / calls,
        "attempt_timeout_count": attempt_timeouts,
        "attempt_timeout_rate": attempt_timeouts / total_attempts,
        "rate_limit_count": sum(int(row["rate_limited"]) for row in rows),
        "usage_exhausted_count": sum(int(row["usage_exhausted"]) for row in rows),
        "invalid_json_count": sum(int(row["invalid_json"]) for row in rows),
        "invalid_json_rate": sum(int(row["invalid_json"]) for row in rows) / calls,
        "schema_failure_count": sum(
            1 for row in rows if row["schema_valid"] is not None and not int(row["schema_valid"])
        ),
        "attempt_json_failure_rate": attempt_json_failures / total_attempts,
        "attempt_schema_failure_rate": attempt_schema_failures / total_attempts,
        "hallucinated_fields": sum(int(row["hallucinated_fields"]) for row in rows),
        "missing_fields": sum(int(row["missing_fields"]) for row in rows),
        "avg_retries": _mean(retry_values),
        "cache_hits": cache_hits,
        "cache_hit_rate": cache_hits / calls,
    }


def _empty_summary(module: str, scenario: str) -> dict[str, Any]:
    return {
        "module": module,
        "scenario": scenario,
        "calls": 0,
        "successes": 0,
        "failures": 0,
        "success_rate": 0.0,
        "failure_rate": 0.0,
        "avg_latency_ms": 0.0,
        "max_latency_ms": 0.0,
        "timeout_count": 0,
        "timeout_rate": 0.0,
        "attempt_timeout_count": 0,
        "attempt_timeout_rate": 0.0,
        "rate_limit_count": 0,
        "usage_exhausted_count": 0,
        "invalid_json_count": 0,
        "invalid_json_rate": 0.0,
        "schema_failure_count": 0,
        "attempt_json_failure_rate": 0.0,
        "attempt_schema_failure_rate": 0.0,
        "hallucinated_fields": 0,
        "missing_fields": 0,
        "avg_retries": 0.0,
        "cache_hits": 0,
        "cache_hit_rate": 0.0,
    }


def _mean(values: list[int] | list[float]) -> float:
    if not values:
        return 0.0
    return float(sum(values) / len(values))


def _attempt_timeout_count(row: dict[str, Any]) -> int:
    metadata_json = row.get("metadata_json")
    if not metadata_json:
        return 0
    try:
        metadata = json.loads(metadata_json)
    except (TypeError, json.JSONDecodeError):
        return 0
    attempts = metadata.get("attempts", [])
    if not isinstance(attempts, list):
        return 0
    return sum(1 for attempt in attempts if attempt.get("error_kind") == "timeout")


def _generate_svg_fallback(
    scenarios: list[dict[str, Any]], reports_dir: Path
) -> dict[str, str]:
    success_path = reports_dir / "success_rate_by_scenario.svg"
    latency_path = reports_dir / "latency_by_scenario.svg"
    _write_bar_svg(
        success_path,
        [(row["scenario"], row["success_rate"] * 100) for row in scenarios],
        "Success rate (%)",
    )
    _write_bar_svg(
        latency_path,
        [(row["scenario"], row["avg_latency_ms"]) for row in scenarios],
        "Average latency (ms)",
    )
    return {"success_rate_plot": str(success_path), "latency_plot": str(latency_path)}


def _write_bar_svg(path: Path, values: list[tuple[str, float]], title: str) -> None:
    width = max(640, 80 * len(values))
    height = 360
    max_value = max([value for _, value in values] + [1.0])
    bar_width = max(20, (width - 120) // max(len(values), 1))
    bars = []
    for index, (label, value) in enumerate(values):
        x = 60 + index * bar_width
        bar_height = int((value / max_value) * 240)
        y = height - 60 - bar_height
        bars.append(
            f'<rect x="{x}" y="{y}" width="{bar_width - 8}" height="{bar_height}" '
            'fill="#2f80ed" />'
        )
        bars.append(
            f'<text x="{x}" y="{height - 38}" font-size="10" '
            f'transform="rotate(60 {x},{height - 38})">{_escape(label)}</text>'
        )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">'
        f'<text x="20" y="28" font-size="18">{_escape(title)}</text>'
        + "".join(bars)
        + "</svg>"
    )
    path.write_text(svg, encoding="utf-8")


def _escape(value: Any) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
