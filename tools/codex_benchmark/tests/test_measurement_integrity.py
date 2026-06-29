"""Regression tests for measurement integrity."""

from __future__ import annotations

from pathlib import Path

from codex_benchmark.benchmark import marker_matches
from codex_benchmark.cache import CacheManager
from codex_benchmark.checkpoint import CheckpointStore
from codex_benchmark.codex_runner import is_rate_limited, is_usage_exhausted
from codex_benchmark.config import load_config, quick_config


def test_usage_exhausted_ignores_generic_exceeded() -> None:
    assert is_usage_exhausted("You've hit your usage limit") is True
    assert is_usage_exhausted("insufficient_quota: please add credits") is True
    assert is_usage_exhausted("maximum context length exceeded") is False
    assert is_usage_exhausted("deadline exceeded") is False
    assert is_usage_exhausted("rate limit exceeded") is False


def test_rate_limit_and_usage_are_distinguishable() -> None:
    assert is_rate_limited("HTTP 429 too many requests") is True
    assert is_usage_exhausted("HTTP 429 too many requests") is False


def test_marker_matches_requires_marker_tokens() -> None:
    marker = "CODEX_BENCHMARK_OK run_id=r1 scenario=calls_20 call_index=3"
    assert marker_matches(marker, marker) is True
    assert marker_matches(f"  {marker}\n", marker) is True
    assert marker_matches(f"Sure!\n{marker}\nDone.", marker) is True
    assert marker_matches("CODEX_BENCHMARK_OK run_id=r1", marker) is False
    assert marker_matches("", marker) is False
    assert marker_matches(None, marker) is False
    assert marker_matches("anything", None) is True


def test_cache_key_changes_with_codex_version(tmp_path: Path) -> None:
    config = quick_config(load_config(Path(__file__).resolve().parents[1] / "config.yaml"))
    config.paths.database = str(tmp_path / "benchmark.sqlite3")
    store = CheckpointStore(config.paths.database)
    try:
        cache = CacheManager(store, config)
        cache.codex_version = "codex-cli 0.142.3"
        key_v1, *_ = cache.make_key(module="cache", prompt="same prompt")
        cache.codex_version = "codex-cli 0.150.0"
        key_v2, *_ = cache.make_key(module="cache", prompt="same prompt")
    finally:
        store.close()

    assert key_v1 != key_v2


def test_cache_prompt_template_is_run_scoped() -> None:
    config = load_config(Path(__file__).resolve().parents[1] / "config.yaml")
    assert "{run_id}" in config.cache_test.prompt_template
