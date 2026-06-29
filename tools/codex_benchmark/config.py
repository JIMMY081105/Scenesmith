"""Configuration loading for the Codex CLI benchmark."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping


try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - exercised only on minimal installs.
    yaml = None


@dataclass
class PathsConfig:
    database: str = "outputs/benchmark.sqlite3"
    artifacts_dir: str = "outputs/artifacts"
    reports_dir: str = "reports"
    logs_dir: str = "outputs/logs"
    images_dir: str = "outputs/images"
    schemas_dir: str = "schemas"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file_name: str = "benchmark.log"
    console: bool = True
    max_bytes: int = 10_485_760
    backup_count: int = 5


@dataclass
class CodexConfig:
    executable: str = "codex"
    model: str | None = None
    profile: str | None = None
    cwd: str = "."
    sandbox: str = "read-only"
    approval_policy: str = "never"
    timeout_seconds: int = 180
    skip_git_repo_check: bool = True
    ignore_user_config: bool = False
    ignore_rules: bool = False
    json_events: bool = False
    extra_args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class StressConfig:
    enabled: bool = True
    call_counts: list[int] = field(
        default_factory=lambda: [10, 50, 100, 200, 500, 1000, 2000]
    )
    prompt_template: str = (
        "You are running a systems benchmark. Do not inspect files or run tools. "
        "Reply with exactly: CODEX_BENCHMARK_OK run_id={run_id} "
        "scenario={scenario} call_index={call_index}"
    )
    max_retries: int = 0


@dataclass
class StructuredConfig:
    enabled: bool = True
    count: int = 300
    schema_path: str = "schemas/structured_output.schema.json"
    max_retries: int = 2
    retry_backoff_seconds: float = 1.0
    prompt_template: str = (
        "Return only a JSON object matching the configured output schema. "
        "Use run_id={run_id}, call_index={call_index}, scenario={scenario}. "
        "Do not add markdown, comments, or fields that are not in the schema."
    )


@dataclass
class ImageConfig:
    enabled: bool = True
    count: int = 50
    schema_path: str = "schemas/image_result.schema.json"
    output_format: str = "svg"
    min_bytes: int = 120
    sandbox: str = "workspace-write"
    max_retries: int = 1
    retry_backoff_seconds: float = 1.0
    prompt_template: str = (
        "BENCHMARK_IMAGE_OUTPUT_PATH={output_path}\n"
        "Create a deterministic {format} image at BENCHMARK_IMAGE_OUTPUT_PATH. "
        "The image should contain simple geometric scene-generation benchmark "
        "content for run_id={run_id}, call_index={call_index}. "
        "After writing the file, return only JSON matching the schema."
    )


@dataclass
class ResumeConfig:
    enabled: bool = True
    total_calls: int = 50
    prompt_template: str = (
        "You are running a checkpoint/resume benchmark. Do not inspect files. "
        "Reply with exactly: CODEX_RESUME_OK run_id={run_id} call_index={call_index}"
    )
    simulated_crash_every_calls: int = 0
    auto_restart: bool = False
    max_auto_restarts: int = 20


@dataclass
class CacheConfig:
    enabled: bool = True
    include_codex_fingerprint: bool = True


@dataclass
class CacheTestConfig:
    enabled: bool = True
    unique_prompts: int = 20
    repetitions_per_prompt: int = 5
    schema_path: str = "schemas/structured_output.schema.json"
    max_retries: int = 1
    prompt_template: str = (
        "Return only JSON matching the schema for cache_key_prompt={logical_id}. "
        "Use a deterministic answer and do not mention the physical call index."
    )


@dataclass
class ReportingConfig:
    enabled: bool = True
    success_threshold: float = 0.98
    json_failure_threshold: float = 0.01
    timeout_threshold: float = 0.01
    cache_hit_threshold: float = 0.70
    generate_plots: bool = True
    calls_csv: str = "calls.csv"
    summary_csv: str = "summary.csv"
    markdown_report: str = "final_report.md"


@dataclass
class BenchmarkConfig:
    name: str = "codex_cli_autonomy_replacement"
    random_seed: int = 20260629
    paths: PathsConfig = field(default_factory=PathsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    codex: CodexConfig = field(default_factory=CodexConfig)
    stress: StressConfig = field(default_factory=StressConfig)
    structured: StructuredConfig = field(default_factory=StructuredConfig)
    image: ImageConfig = field(default_factory=ImageConfig)
    resume: ResumeConfig = field(default_factory=ResumeConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    cache_test: CacheTestConfig = field(default_factory=CacheTestConfig)
    reporting: ReportingConfig = field(default_factory=ReportingConfig)

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    def stable_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_config(path: str | Path) -> BenchmarkConfig:
    """Load config from YAML or JSON and merge it over dataclass defaults."""

    config_path = Path(path).resolve()
    config = BenchmarkConfig()
    if config_path.exists():
        raw_text = config_path.read_text(encoding="utf-8")
        if yaml is not None:
            data = yaml.safe_load(raw_text) or {}
        else:
            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                raise RuntimeError(
                    "PyYAML is required for YAML config files. Install with "
                    "`pip install PyYAML`, or make config.yaml valid JSON."
                ) from exc
        if not isinstance(data, Mapping):
            raise ValueError(f"Top-level config must be a mapping: {config_path}")
        config = _merge_dataclass(config, data)

    return resolve_config_paths(config, config_path.parent)


def resolve_config_paths(config: BenchmarkConfig, base_dir: Path) -> BenchmarkConfig:
    """Resolve all project-relative paths against the directory containing config.yaml."""

    paths = config.paths
    for field_name in dataclasses.asdict(paths):
        value = getattr(paths, field_name)
        setattr(paths, field_name, _resolve_path(value, base_dir))

    config.codex.cwd = _resolve_path(config.codex.cwd, base_dir)
    config.structured.schema_path = _resolve_path(config.structured.schema_path, base_dir)
    config.image.schema_path = _resolve_path(config.image.schema_path, base_dir)
    config.cache_test.schema_path = _resolve_path(config.cache_test.schema_path, base_dir)
    return config


def quick_config(config: BenchmarkConfig) -> BenchmarkConfig:
    """Return a tiny deterministic config for smoke testing the framework."""

    config.stress.call_counts = [2]
    config.structured.count = 2
    config.image.count = 1
    config.resume.total_calls = 3
    config.resume.simulated_crash_every_calls = 0
    config.cache_test.unique_prompts = 2
    config.cache_test.repetitions_per_prompt = 2
    config.codex.timeout_seconds = min(config.codex.timeout_seconds, 60)
    return config


def ensure_directories(config: BenchmarkConfig) -> None:
    for directory in [
        Path(config.paths.artifacts_dir),
        Path(config.paths.reports_dir),
        Path(config.paths.logs_dir),
        Path(config.paths.images_dir),
    ]:
        directory.mkdir(parents=True, exist_ok=True)
    Path(config.paths.database).parent.mkdir(parents=True, exist_ok=True)


def _resolve_path(value: str, base_dir: Path) -> str:
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str((base_dir / path).resolve())


def _merge_dataclass(instance: Any, data: Mapping[str, Any]) -> Any:
    field_map = {field.name: field for field in dataclasses.fields(instance)}
    for key, value in data.items():
        if key not in field_map:
            raise ValueError(f"Unknown config key: {key}")
        current = getattr(instance, key)
        if dataclasses.is_dataclass(current):
            if not isinstance(value, Mapping):
                raise ValueError(f"Config section `{key}` must be a mapping")
            setattr(instance, key, _merge_dataclass(current, value))
        else:
            setattr(instance, key, value)
    return instance
