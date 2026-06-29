"""Codex CLI benchmark orchestrator.

Run:
    python -m codex_benchmark.benchmark --config codex_benchmark/config.yaml

Smoke test without real Codex calls:
    python -m codex_benchmark.benchmark --quick --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:  # Allows `python codex_benchmark/benchmark.py`.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from codex_benchmark.cache import CacheManager, sha256_file
from codex_benchmark.checkpoint import CallRecord, CheckpointStore, utc_now
from codex_benchmark.codex_runner import CodexResult, CodexRunner
from codex_benchmark.config import (
    BenchmarkConfig,
    ensure_directories,
    load_config,
    quick_config,
)
from codex_benchmark.logger import setup_logging
from codex_benchmark.report import write_markdown_report
from codex_benchmark.statistics import compute_summary, generate_plots, write_csv_reports


try:
    import jsonschema  # type: ignore
except ImportError:  # pragma: no cover - exercised only on minimal installs.
    jsonschema = None


EXIT_SIMULATED_CRASH = 86


class SimulatedCrash(RuntimeError):
    pass


class BenchmarkSuite:
    def __init__(
        self,
        *,
        config: BenchmarkConfig,
        run_id: str,
        resume: bool,
        dry_run: bool,
        modules: set[str] | None,
    ):
        self.config = config
        self.run_id = run_id
        self.resume = resume
        self.dry_run = dry_run
        self.modules = modules
        self.logger = setup_logging(config.logging, config.paths.logs_dir)
        self.store = CheckpointStore(config.paths.database)
        self.cache = CacheManager(self.store, config)
        self.runner = CodexRunner(config, run_id, dry_run=dry_run)
        self.resume_calls_this_process = 0

    def close(self) -> None:
        self.store.close()

    def run(self) -> dict[str, str]:
        codex_version = self.runner.version()
        # Fold the live codex version into cache keys so upgrading the binary
        # does not replay stale cached results from a previous version.
        self.cache.codex_version = codex_version
        self.store.start_run(
            run_id=self.run_id,
            config_hash=self.config.stable_hash(),
            config_json=json.dumps(self.config.to_dict(), sort_keys=True),
            codex_version=codex_version,
            resume=self.resume,
        )
        self.logger.info("Starting run_id=%s dry_run=%s", self.run_id, self.dry_run)
        try:
            self._run_enabled_modules()
        except KeyboardInterrupt:
            self.logger.warning("Interrupted by Ctrl+C")
            self.store.mark_interrupted(self.run_id)
            return self._write_reports()
        except SimulatedCrash:
            self.logger.warning("Simulated crash requested by resume test")
            self.store.mark_interrupted(self.run_id, status="simulated_crash")
            raise
        except Exception:
            self.logger.exception("Benchmark failed")
            self.store.mark_interrupted(self.run_id, status="failed")
            raise

        self.store.mark_run_status(self.run_id, "complete")
        self.logger.info("Benchmark complete")
        return self._write_reports()

    def _run_enabled_modules(self) -> None:
        if self._enabled("stress") and self.config.stress.enabled:
            self._run_stress()
        if self._enabled("structured") and self.config.structured.enabled:
            self._run_structured()
        if self._enabled("image") and self.config.image.enabled:
            self._run_image()
        if self._enabled("vlm") and self.config.vlm.enabled:
            self._run_vlm()
        if self._enabled("resume") and self.config.resume.enabled:
            self._run_resume()
        if self._enabled("cache") and self.config.cache_test.enabled:
            self._run_cache_test()

    def _enabled(self, module: str) -> bool:
        return self.modules is None or module in self.modules

    def _run_stress(self) -> None:
        for count in self.config.stress.call_counts:
            scenario = f"calls_{count}"
            self.logger.info("Stress scenario %s", scenario)
            for call_index in range(count):
                prompt = self.config.stress.prompt_template.format(
                    run_id=self.run_id,
                    scenario=scenario,
                    call_index=call_index,
                )
                expected_marker = (
                    f"CODEX_BENCHMARK_OK run_id={self.run_id} "
                    f"scenario={scenario} call_index={call_index}"
                )
                self._run_one(
                    module="stress",
                    scenario=scenario,
                    call_index=call_index,
                    prompt=prompt,
                    max_retries=self.config.stress.max_retries,
                    expected_marker=expected_marker,
                )

    def _run_structured(self) -> None:
        scenario = "schema_json"
        for call_index in range(self.config.structured.count):
            prompt = self.config.structured.prompt_template.format(
                run_id=self.run_id,
                scenario=scenario,
                call_index=call_index,
            )
            self._run_one(
                module="structured",
                scenario=scenario,
                call_index=call_index,
                prompt=prompt,
                schema_path=self.config.structured.schema_path,
                max_retries=self.config.structured.max_retries,
                retry_backoff_seconds=self.config.structured.retry_backoff_seconds,
            )

    def _run_image(self) -> None:
        scenario = f"{self.config.image.output_format}_artifact"
        image_dir = Path(self.config.paths.images_dir) / self.run_id
        image_dir.mkdir(parents=True, exist_ok=True)
        for call_index in range(self.config.image.count):
            output_path = image_dir / f"image_{call_index:06d}.{self.config.image.output_format}"
            prompt = self.config.image.prompt_template.format(
                run_id=self.run_id,
                scenario=scenario,
                call_index=call_index,
                output_path=str(output_path),
                format=self.config.image.output_format,
            )
            self._run_one(
                module="image",
                scenario=scenario,
                call_index=call_index,
                prompt=prompt,
                schema_path=self.config.image.schema_path,
                sandbox=self.config.image.sandbox,
                max_retries=self.config.image.max_retries,
                retry_backoff_seconds=self.config.image.retry_backoff_seconds,
                expected_image_path=str(output_path),
            )

    def _run_vlm(self) -> None:
        scenario = "scene_image_json"
        items = load_vlm_manifest(self.config.vlm.manifest_path, self.config.vlm.dataset_root)
        available = [item for item in items if Path(item["path"]).exists()]
        if len(available) < self.config.vlm.count:
            self.logger.warning(
                "VLM manifest has only %s available images, requested %s",
                len(available),
                self.config.vlm.count,
            )
        for call_index, item in enumerate(available[: self.config.vlm.count]):
            prompt = self.config.vlm.prompt_template.format(
                run_id=self.run_id,
                scenario=scenario,
                call_index=call_index,
                image_path=item["path"],
            )
            self._run_one(
                module="vlm",
                scenario=scenario,
                call_index=call_index,
                prompt=prompt,
                schema_path=self.config.vlm.schema_path,
                image_paths=[item["path"]],
                max_retries=self.config.vlm.max_retries,
                retry_backoff_seconds=self.config.vlm.retry_backoff_seconds,
                classification_expected=item,
                run_metadata={
                    "requested_count": self.config.vlm.count,
                    "available_count": len(available),
                    "insufficient_dataset_size": len(available) < self.config.vlm.count,
                },
            )

    def _run_resume(self) -> None:
        scenario = "checkpoint_resume"
        for call_index in range(self.config.resume.total_calls):
            prompt = self.config.resume.prompt_template.format(
                run_id=self.run_id,
                call_index=call_index,
                scenario=scenario,
            )
            expected_marker = (
                f"CODEX_RESUME_OK run_id={self.run_id} call_index={call_index}"
            )
            completed = self._run_one(
                module="resume",
                scenario=scenario,
                call_index=call_index,
                prompt=prompt,
                max_retries=0,
                expected_marker=expected_marker,
            )
            if completed:
                self.resume_calls_this_process += 1
            self._maybe_simulate_resume_crash()

    def _run_cache_test(self) -> None:
        scenario = "duplicate_prompts"
        total = self.config.cache_test.unique_prompts * self.config.cache_test.repetitions_per_prompt
        for call_index in range(total):
            logical_id = call_index % self.config.cache_test.unique_prompts
            prompt = self.config.cache_test.prompt_template.format(
                run_id=self.run_id,
                scenario=scenario,
                call_index=call_index,
                logical_id=logical_id,
            )
            self._run_one(
                module="cache",
                scenario=scenario,
                call_index=call_index,
                prompt=prompt,
                schema_path=self.config.cache_test.schema_path,
                max_retries=self.config.cache_test.max_retries,
            )

    def _run_one(
        self,
        *,
        module: str,
        scenario: str,
        call_index: int,
        prompt: str,
        schema_path: str | None = None,
        image_paths: list[str] | None = None,
        sandbox: str | None = None,
        max_retries: int = 0,
        retry_backoff_seconds: float = 0.0,
        expected_image_path: str | None = None,
        classification_expected: dict[str, Any] | None = None,
        run_metadata: dict[str, Any] | None = None,
        expected_marker: str | None = None,
    ) -> bool:
        if self.store.call_exists(self.run_id, module, scenario, call_index):
            return False

        cache_key, prompt_hash, schema_hash, image_hash = self.cache.make_key(
            module=module,
            prompt=prompt,
            schema_path=schema_path,
            image_paths=image_paths,
            extra={
                "expected_image_path": expected_image_path,
                "dry_run": self.dry_run,
                "run_id": None if module == "cache" else self.run_id,
            },
        )
        cached = self.cache.get(cache_key)
        if cached:
            record = self._record_from_cache(
                module=module,
                scenario=scenario,
                call_index=call_index,
                cache_key=cache_key,
                prompt_hash=prompt_hash,
                schema_hash=schema_hash,
                image_hash=image_hash,
                cached=cached,
            )
            self.store.record_call(record)
            return True

        attempt_results: list[dict[str, Any]] = []
        final_result: CodexResult | None = None
        final_validation: dict[str, Any] = {}
        final_image: dict[str, Any] = {}
        final_content_valid: bool = True

        for attempt in range(max_retries + 1):
            result = self.runner.run(
                prompt=prompt,
                module=module,
                scenario=scenario,
                call_index=call_index,
                schema_path=schema_path,
                image_paths=image_paths,
                sandbox=sandbox,
            )
            validation = validate_output(result.last_message, schema_path)
            classification_validation = (
                validate_vlm_classification(result.last_message, classification_expected)
                if classification_expected
                else {"classification_wrong": False, "classification_error": None}
            )
            image_validation = (
                verify_image(expected_image_path, self.config.image.min_bytes)
                if expected_image_path
                else {"valid": True, "image_hash": None, "error": None}
            )
            content_valid = marker_matches(result.last_message, expected_marker)
            attempt_results.append(
                {
                    "attempt": attempt,
                    "success": result.success,
                    "invalid_json": validation["invalid_json"],
                    "schema_valid": validation["schema_valid"],
                    "classification_wrong": classification_validation["classification_wrong"],
                    "image_valid": image_validation["valid"],
                    "content_valid": content_valid,
                    "error_kind": result.error_kind,
                }
            )
            final_result = result
            final_validation = validation
            final_validation["classification"] = classification_validation
            final_image = image_validation
            final_content_valid = content_valid
            if (
                result.success
                and not validation["invalid_json"]
                and validation["schema_valid"] is not False
                and image_validation["valid"]
                and content_valid
            ):
                break
            if attempt < max_retries and retry_backoff_seconds > 0:
                time.sleep(retry_backoff_seconds)

        assert final_result is not None
        record = self._record_from_result(
            module=module,
            scenario=scenario,
            call_index=call_index,
            cache_key=cache_key,
            prompt_hash=prompt_hash,
            schema_hash=schema_hash,
            image_hash=final_image.get("image_hash") or image_hash,
            result=final_result,
            validation=final_validation,
            image_validation=final_image,
            content_valid=final_content_valid,
            attempts=attempt_results,
            extra_metadata=run_metadata,
        )
        self.store.record_call(record)

        if record.success:
            self.cache.put(
                cache_key=cache_key,
                prompt_hash=prompt_hash,
                schema_hash=schema_hash,
                image_hash=record.image_hash,
                module=module,
                status=record.status,
                output_text=record.output_text,
                output_path=record.output_path,
                metadata=record.metadata,
            )
        return True

    def _record_from_result(
        self,
        *,
        module: str,
        scenario: str,
        call_index: int,
        cache_key: str,
        prompt_hash: str,
        schema_hash: str | None,
        image_hash: str | None,
        result: CodexResult,
        validation: dict[str, Any],
        image_validation: dict[str, Any],
        content_valid: bool,
        attempts: list[dict[str, Any]],
        extra_metadata: dict[str, Any] | None = None,
    ) -> CallRecord:
        attempt_json_failures = sum(1 for item in attempts if item["invalid_json"])
        attempt_schema_failures = sum(1 for item in attempts if item["schema_valid"] is False)
        image_valid = image_validation.get("valid", True)
        success = (
            result.success
            and not validation["invalid_json"]
            and validation["schema_valid"] is not False
            and image_valid
            and content_valid
        )
        if result.timeout:
            status = "timeout"
        elif result.rate_limited:
            status = "rate_limited"
        elif result.usage_exhausted:
            status = "usage_exhausted"
        elif not image_valid:
            status = "image_invalid"
        elif validation["invalid_json"]:
            status = "invalid_json"
        elif validation["schema_valid"] is False:
            status = "schema_invalid"
        elif not content_valid:
            status = "content_mismatch"
        elif success:
            status = "success"
        else:
            status = "failure"

        error_message = (
            result.error_message
            or validation.get("error")
            or image_validation.get("error")
            or (None if content_valid else "expected marker not found in final message")
        )
        metadata = {
            "attempts": attempts,
            "command": result.command,
            "image_validation": image_validation,
        }
        if validation.get("classification"):
            metadata["classification"] = validation["classification"]
        if extra_metadata:
            metadata.update(extra_metadata)
        return CallRecord(
            run_id=self.run_id,
            module=module,
            scenario=scenario,
            call_index=call_index,
            status=status,
            success=success,
            started_at=result.started_at,
            ended_at=result.ended_at,
            latency_ms=result.latency_ms,
            retries=max(0, len(attempts) - 1),
            attempt_count=len(attempts),
            attempt_json_failures=attempt_json_failures,
            attempt_schema_failures=attempt_schema_failures,
            timeout=result.timeout,
            rate_limited=result.rate_limited,
            usage_exhausted=result.usage_exhausted,
            return_code=result.return_code,
            error_kind=result.error_kind,
            error_message=error_message,
            invalid_json=validation["invalid_json"],
            schema_valid=validation["schema_valid"],
            hallucinated_fields=validation["hallucinated_fields"],
            missing_fields=validation["missing_fields"],
            cache_hit=False,
            cache_key=cache_key,
            prompt_hash=prompt_hash,
            schema_hash=schema_hash,
            image_hash=image_hash,
            output_text=result.last_message,
            output_path=image_validation.get("path"),
            stdout_path=result.stdout_path,
            stderr_path=result.stderr_path,
            last_message_path=result.last_message_path,
            metadata=metadata,
        )

    def _record_from_cache(
        self,
        *,
        module: str,
        scenario: str,
        call_index: int,
        cache_key: str,
        prompt_hash: str,
        schema_hash: str | None,
        image_hash: str | None,
        cached: dict[str, Any],
    ) -> CallRecord:
        now = utc_now()
        metadata = cached.get("metadata", {})
        return CallRecord(
            run_id=self.run_id,
            module=module,
            scenario=scenario,
            call_index=call_index,
            status="success",
            success=True,
            started_at=now,
            ended_at=now,
            latency_ms=0.0,
            retries=0,
            attempt_count=0,
            cache_hit=True,
            cache_key=cache_key,
            prompt_hash=prompt_hash,
            schema_hash=schema_hash,
            image_hash=image_hash,
            output_text=cached.get("output_text"),
            output_path=cached.get("output_path"),
            metadata={"cache_source": metadata},
        )

    def _maybe_simulate_resume_crash(self) -> None:
        every = self.config.resume.simulated_crash_every_calls
        if every <= 0:
            return
        if self.resume_calls_this_process == 0:
            return
        completed = self.store.completed_count(self.run_id, module="resume")
        if completed >= self.config.resume.total_calls:
            return
        if self.resume_calls_this_process >= every:
            raise SimulatedCrash("Configured resume crash interval reached")

    def _write_reports(self) -> dict[str, str]:
        if not self.config.reporting.enabled:
            return {}
        summary = compute_summary(self.store, self.run_id)
        paths = {}
        paths.update(write_csv_reports(summary, self.config))
        paths.update(generate_plots(summary, self.config))
        paths["markdown_report"] = write_markdown_report(summary, self.config, paths)
        return paths


def marker_matches(output: str | None, expected_marker: str | None) -> bool:
    """True when the model's final message contains the required marker."""

    if expected_marker is None:
        return True
    if output is None:
        return False
    normalized_output = " ".join(output.split())
    normalized_marker = " ".join(expected_marker.split())
    return normalized_marker in normalized_output


def validate_output(output: str | None, schema_path: str | None) -> dict[str, Any]:
    if schema_path is None:
        return {
            "invalid_json": False,
            "schema_valid": None,
            "hallucinated_fields": 0,
            "missing_fields": 0,
            "error": None,
        }
    if output is None:
        return {
            "invalid_json": True,
            "schema_valid": False,
            "hallucinated_fields": 0,
            "missing_fields": 0,
            "error": "missing final message",
        }
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        return {
            "invalid_json": True,
            "schema_valid": False,
            "hallucinated_fields": 0,
            "missing_fields": 0,
            "error": str(exc),
        }

    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    hallucinated, missing = count_schema_field_issues(parsed, schema)
    error = None
    schema_valid = True
    if jsonschema is not None:
        validator = jsonschema.Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(parsed), key=lambda item: list(item.path))
        if errors:
            schema_valid = False
            error = "; ".join(error.message for error in errors[:5])
    else:
        schema_valid = missing == 0 and hallucinated == 0
    return {
        "invalid_json": False,
        "schema_valid": schema_valid,
        "hallucinated_fields": hallucinated,
        "missing_fields": missing,
        "error": error,
    }


def load_vlm_manifest(manifest_path: str, dataset_root: str) -> list[dict[str, Any]]:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if not isinstance(manifest, list):
        raise ValueError(f"VLM manifest must be a list: {manifest_path}")

    root = Path(dataset_root)
    loaded: list[dict[str, Any]] = []
    for index, item in enumerate(manifest):
        if not isinstance(item, dict):
            raise ValueError(f"VLM manifest item {index} must be an object")
        raw_path = item.get("path")
        if not raw_path:
            raise ValueError(f"VLM manifest item {index} is missing `path`")
        image_path = Path(raw_path)
        if not image_path.is_absolute():
            image_path = root / image_path
        normalized = dict(item)
        normalized["path"] = str(image_path.resolve())
        normalized.setdefault("expected_scene_type", "unknown")
        normalized.setdefault("expected_main_objects", [])
        return_fields = {
            "path",
            "expected_scene_type",
            "expected_main_objects",
            "label",
            "notes",
        }
        loaded.append({key: value for key, value in normalized.items() if key in return_fields})
    return loaded


def validate_vlm_classification(
    output: str | None, expected: dict[str, Any]
) -> dict[str, Any]:
    if output is None:
        return {
            "classification_wrong": True,
            "classification_error": "missing final message",
            "expected_scene_type": expected.get("expected_scene_type"),
            "predicted_scene_type": None,
            "object_overlap": 0,
        }
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        return {
            "classification_wrong": True,
            "classification_error": f"invalid JSON: {exc}",
            "expected_scene_type": expected.get("expected_scene_type"),
            "predicted_scene_type": None,
            "object_overlap": 0,
        }

    expected_scene_type = str(expected.get("expected_scene_type", "unknown"))
    predicted_scene_type = str(parsed.get("scene_type", "unknown"))
    expected_objects = {_normalize_label(value) for value in expected.get("expected_main_objects", [])}
    raw_predicted_objects = parsed.get("main_objects", [])
    if not isinstance(raw_predicted_objects, list):
        raw_predicted_objects = []
    predicted_objects = {_normalize_label(value) for value in raw_predicted_objects}
    expected_objects.discard("")
    predicted_objects.discard("")
    object_overlap = len(expected_objects & predicted_objects)

    scene_wrong = (
        expected_scene_type != "unknown"
        and _normalize_label(predicted_scene_type) != _normalize_label(expected_scene_type)
    )
    # Treat scene_type as the classification label. Object overlap is diagnostic:
    # exact object vocabulary varies across valid VLM descriptions.
    classification_wrong = scene_wrong
    return {
        "classification_wrong": classification_wrong,
        "classification_error": None,
        "expected_scene_type": expected_scene_type,
        "predicted_scene_type": predicted_scene_type,
        "expected_main_objects": sorted(expected_objects),
        "predicted_main_objects": sorted(predicted_objects),
        "object_overlap": object_overlap,
        "expected_path": expected.get("path"),
    }


def _normalize_label(value: Any) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def count_schema_field_issues(data: Any, schema: dict[str, Any]) -> tuple[int, int]:
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next((item for item in schema_type if item != "null"), schema_type[0])
    if schema_type == "object" or "properties" in schema:
        if not isinstance(data, dict):
            return 0, len(schema.get("required", []))
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        missing = sum(1 for key in required if key not in data)
        hallucinated = 0
        if schema.get("additionalProperties") is False:
            hallucinated += sum(1 for key in data if key not in properties)
        for key, child_schema in properties.items():
            if key in data:
                child_hallucinated, child_missing = count_schema_field_issues(data[key], child_schema)
                hallucinated += child_hallucinated
                missing += child_missing
        return hallucinated, missing
    if schema_type == "array" and isinstance(data, list):
        hallucinated = 0
        missing = 0
        item_schema = schema.get("items", {})
        for item in data:
            child_hallucinated, child_missing = count_schema_field_issues(item, item_schema)
            hallucinated += child_hallucinated
            missing += child_missing
        return hallucinated, missing
    return 0, 0


def verify_image(path: str | None, min_bytes: int) -> dict[str, Any]:
    if path is None:
        return {"valid": True, "path": None, "image_hash": None, "error": None}
    file_path = Path(path)
    if not file_path.exists():
        return {"valid": False, "path": str(file_path), "image_hash": None, "error": "missing file"}
    size = file_path.stat().st_size
    if size < min_bytes:
        return {
            "valid": False,
            "path": str(file_path),
            "image_hash": None,
            "error": f"file too small: {size} bytes",
        }
    suffix = file_path.suffix.lower()
    data = file_path.read_bytes()[:256]
    if suffix == ".svg" and b"<svg" not in data.lower():
        return {"valid": False, "path": str(file_path), "image_hash": None, "error": "not an svg"}
    if suffix == ".png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        return {"valid": False, "path": str(file_path), "image_hash": None, "error": "not a png"}
    if suffix in {".jpg", ".jpeg"} and not data.startswith(b"\xff\xd8"):
        return {"valid": False, "path": str(file_path), "image_hash": None, "error": "not a jpeg"}
    return {
        "valid": True,
        "path": str(file_path),
        "image_hash": sha256_file(file_path),
        "error": None,
        "bytes": size,
    }


def generate_run_id(prefix: str = "run") -> str:
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{timestamp}_{uuid.uuid4().hex[:8]}"


def supervise(args: argparse.Namespace) -> int:
    run_id = args.run_id or generate_run_id()
    restarts = 0
    script = Path(__file__).resolve()
    while True:
        command = [
            sys.executable,
            str(script),
            "--config",
            args.config,
            "--run-id",
            run_id,
            "--resume",
            "--worker",
        ]
        if args.quick:
            command.append("--quick")
        if args.dry_run:
            command.append("--dry-run")
        if args.modules:
            command.extend(["--modules", args.modules])
        if args.stress_calls:
            command.extend(["--stress-calls", args.stress_calls])
        if args.structured_calls is not None:
            command.extend(["--structured-calls", str(args.structured_calls)])
        if args.image_count is not None:
            command.extend(["--image-count", str(args.image_count)])
        if args.vlm_count is not None:
            command.extend(["--vlm-count", str(args.vlm_count)])
        if args.simulate_crash_every is not None:
            command.extend(["--simulate-crash-every", str(args.simulate_crash_every)])
        if args.resume_total_calls is not None:
            command.extend(["--resume-total-calls", str(args.resume_total_calls)])
        completed = subprocess.run(command)
        if completed.returncode == EXIT_SIMULATED_CRASH:
            restarts += 1
            config = load_config(args.config)
            if args.quick:
                config = quick_config(config)
            apply_cli_overrides(config, args)
            if restarts > config.resume.max_auto_restarts:
                print("Maximum auto restarts exceeded", file=sys.stderr)
                return completed.returncode
            continue
        return completed.returncode


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark Codex CLI for autonomous pipelines.")
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--resume", action="store_true", help="Resume an existing run id.")
    parser.add_argument("--dry-run", action="store_true", help="Exercise framework without Codex calls.")
    parser.add_argument("--quick", action="store_true", help="Use tiny counts for smoke testing.")
    parser.add_argument(
        "--modules",
        default=None,
        help="Comma-separated subset: stress,structured,image,vlm,resume,cache.",
    )
    parser.add_argument(
        "--stress-calls",
        default=None,
        help="Override stress.call_counts. Use one integer like 20 or a comma list like 20,100.",
    )
    parser.add_argument(
        "--structured-calls",
        type=int,
        default=None,
        help="Override structured.count.",
    )
    parser.add_argument(
        "--image-count",
        type=int,
        default=None,
        help="Override image.count.",
    )
    parser.add_argument(
        "--vlm-count",
        type=int,
        default=None,
        help="Override vlm.count.",
    )
    parser.add_argument(
        "--auto-restart",
        action="store_true",
        help="Supervisor mode for simulated resume crashes.",
    )
    parser.add_argument(
        "--simulate-crash-every",
        type=int,
        default=None,
        help="Override resume.simulated_crash_every_calls for resume testing.",
    )
    parser.add_argument(
        "--resume-total-calls",
        type=int,
        default=None,
        help="Override resume.total_calls for resume testing.",
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def apply_cli_overrides(config: BenchmarkConfig, args: argparse.Namespace) -> None:
    if args.stress_calls:
        try:
            config.stress.call_counts = [
                int(item.strip()) for item in args.stress_calls.split(",") if item.strip()
            ]
        except ValueError as exc:
            raise ValueError("--stress-calls must be an integer or comma-separated integers") from exc
        if not config.stress.call_counts or any(count <= 0 for count in config.stress.call_counts):
            raise ValueError("--stress-calls values must be positive")
    if args.structured_calls is not None:
        if args.structured_calls <= 0:
            raise ValueError("--structured-calls must be positive")
        config.structured.count = args.structured_calls
    if args.image_count is not None:
        if args.image_count <= 0:
            raise ValueError("--image-count must be positive")
        config.image.count = args.image_count
    if args.vlm_count is not None:
        if args.vlm_count <= 0:
            raise ValueError("--vlm-count must be positive")
        config.vlm.count = args.vlm_count
    if args.simulate_crash_every is not None:
        config.resume.simulated_crash_every_calls = args.simulate_crash_every
    if args.resume_total_calls is not None:
        config.resume.total_calls = args.resume_total_calls


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.auto_restart and not args.worker:
        return supervise(args)

    config = load_config(args.config)
    if args.quick:
        config = quick_config(config)
    apply_cli_overrides(config, args)
    ensure_directories(config)

    if config.resume.auto_restart and not args.worker:
        args.auto_restart = True
        return supervise(args)

    modules = set(args.modules.split(",")) if args.modules else None
    run_id = args.run_id or generate_run_id()
    suite = BenchmarkSuite(
        config=config,
        run_id=run_id,
        resume=args.resume,
        dry_run=args.dry_run,
        modules=modules,
    )
    try:
        paths = suite.run()
    except SimulatedCrash:
        return EXIT_SIMULATED_CRASH
    finally:
        suite.close()

    print(json.dumps({"run_id": run_id, "artifacts": paths}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
